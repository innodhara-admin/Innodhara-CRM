/**
 * The org hand-off — 06_DESIGN.md §4.2, D18.
 *
 * `POST /orgs` returns `admin_temp_password` **once**, and it is stored nowhere
 * the console can read back. Lose it and the organisation is unreachable: there
 * is no `PATCH /orgs/{id}`, and `POST /admin/users/{id}/reset-password` needs
 * `manage_staff` — which only that lost account holds. A `super_admin` can
 * deactivate the org; nobody can recover it.
 *
 * So **no human ever handles it on the happy path.** One submit runs the whole
 * chain and the password lives in a local variable for the length of it.
 *
 * Step 3 is not optional. `must_change_password` is set by `organisations.py`
 * and `admin.py`, returned by `auth.py`, and **read by no dependency** — the
 * flag enforces nothing. If this console does not force the change, nothing
 * does.
 *
 * This module is deliberately free of React: the state machine is the risky
 * part, so it is testable without rendering anything.
 */
import { z } from "zod";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { schemas } from "../api/generated";
import { isApiError, type ApiError } from "../api/errors";
import { session, type OrgSession } from "./store";

/** Where the chain is, or where it stopped. */
export type HandoffStep = "create" | "login" | "password";

export const STEP_LABEL: Record<HandoffStep, string> = {
  create: "Creating the organisation",
  login: "Signing in as its administrator",
  password: "Setting the password you chose",
};

/**
 * Revealed **only** when a step after the first has failed. At that point the
 * organisation exists and this string is the only way into it, so hiding it
 * would convert a recoverable failure into a stranded organisation (§4.2).
 */
export type Recovery = {
  orgId: string;
  orgName: string;
  adminEmail: string;
  tempPassword: string;
  intendedPassword: string;
};

export type HandoffState =
  | { phase: "running"; step: HandoffStep }
  | { phase: "done"; org: OrgSession }
  /**
   * `recovery: null` means step 1 itself failed, so **nothing was created** and
   * there is nothing to recover — a materially different situation from a
   * half-built organisation, and the modal says so rather than showing an empty
   * password box.
   */
  | { phase: "failed"; step: HandoffStep; error: ApiError; recovery: Recovery | null };

export type HandoffInput = {
  name: string;
  slug: string;
  email_domain: string;
  admin_email: string;
  admin_name: string;
  logo_url?: string;
  /** The password the operator chose. Never sent to `POST /orgs`. */
  adminPassword: string;
};

/** Injectable so the state machine can be tested without a server. */
export type HandoffTransport = {
  createOrg: (body: unknown) => Promise<unknown>;
  login: (body: unknown) => Promise<unknown>;
  changePassword: (token: string, body: unknown) => Promise<unknown>;
};

export const httpTransport: HandoffTransport = {
  createOrg: (body) =>
    request(endpoints.orgs, { as: "super", method: "POST", body }),
  login: (body) => request(endpoints.login, { as: "none", method: "POST", body }),
  changePassword: (token, body) =>
    // Not `as: "org"`: the org session does not exist yet at this point in the
    // chain, and storing the temp-password token would put it somewhere
    // readable. The token is passed explicitly and never leaves this function.
    request(endpoints.changePassword, {
      as: "none",
      method: "POST",
      body,
      bearer: token,
    }),
};

const CreateOrgResponse = schemas.CreateOrgResponse;
const LoginResponse = schemas.LoginResponse;

function asApiError(cause: unknown, fallback: string): ApiError {
  if (isApiError(cause)) return cause;
  return {
    status: 0,
    kind: "http",
    detail: cause instanceof Error ? cause.message : fallback,
  };
}

/**
 * Run the chain. Reports every state change through `onState` so the modal can
 * show which step it is on, and resolves to the established org session.
 */
export async function runHandoff(
  input: HandoffInput,
  onState: (state: HandoffState) => void,
  transport: HandoffTransport = httpTransport,
): Promise<HandoffState> {
  // Held here and nowhere else. Not in React state, not in the session store,
  // not in sessionStorage — the happy path must leave no copy behind.
  let tempPassword = "";
  let created: z.infer<typeof CreateOrgResponse> | null = null;

  const recovery = (): Recovery | null =>
    created && {
      orgId: created.id,
      orgName: created.name,
      adminEmail: created.admin_email,
      tempPassword,
      intendedPassword: input.adminPassword,
    };

  const fail = (step: HandoffStep, cause: unknown, fallback: string): HandoffState => {
    const state: HandoffState = {
      phase: "failed",
      step,
      error: asApiError(cause, fallback),
      recovery: recovery(),
    };
    onState(state);
    return state;
  };

  // ── 1 · POST /orgs as super_admin ───────────────────────────────────────
  onState({ phase: "running", step: "create" });
  try {
    const body = {
      name: input.name,
      slug: input.slug,
      email_domain: input.email_domain,
      admin_email: input.admin_email,
      admin_name: input.admin_name,
      ...(input.logo_url ? { logo_url: input.logo_url } : {}),
    };
    created = CreateOrgResponse.parse(await transport.createOrg(body));
    tempPassword = created.admin_temp_password;
  } catch (cause) {
    // created is still null, so recovery() returns null: nothing exists yet and
    // the operator can simply try again.
    return fail("create", cause, "The organisation could not be created.");
  }

  // ── 2 · Log in as the new org_admin with the temp password ──────────────
  onState({ phase: "running", step: "login" });
  let login: z.infer<typeof LoginResponse>;
  try {
    login = LoginResponse.parse(
      await transport.login({
        email: created.admin_email,
        password: tempPassword,
        org_slug: created.slug,
      }),
    );
  } catch (cause) {
    return fail("login", cause, "The new administrator could not sign in.");
  }

  // ── 3 · Change to the password the operator chose ───────────────────────
  onState({ phase: "running", step: "password" });
  try {
    await transport.changePassword(login.access_token, {
      current_password: tempPassword,
      new_password: input.adminPassword,
    });
  } catch (cause) {
    return fail("password", cause, "The password could not be changed.");
  }

  const org: OrgSession = {
    token: login.access_token,
    userId: login.user_id,
    name: login.name,
    role: login.role,
    orgId: created.id,
    orgName: created.name,
    // The only place any session can learn this: no org_admin-readable route
    // returns email_domain (P7), and Task 23's domain check needs it.
    emailDomain: created.email_domain,
  };
  session.setOrg(org);
  // §1.1: the console holds super_admin for exactly one call, and that call is
  // now behind us. Keeping the most privileged token in the tab has no upside.
  session.releaseSuper();

  const done: HandoffState = { phase: "done", org };
  onState(done);
  return done;
}

/**
 * What the operator must do by hand if the chain broke after step 1.
 * Listed as real calls, because at that point the console cannot help.
 */
export function remainingCalls(recovery: Recovery): string[] {
  return [
    `POST /api/v1/auth/login  {"email": "${recovery.adminEmail}", "password": "<the temporary password above>"}`,
    `POST /api/v1/auth/change-password  {"current_password": "<the temporary password above>", "new_password": "<the password you chose>"}`,
  ];
}
