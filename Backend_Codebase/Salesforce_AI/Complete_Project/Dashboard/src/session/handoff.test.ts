/**
 * The hand-off state machine — Task 14, D18.
 *
 * This is the highest-consequence code in the console: a bug here strands an
 * organisation permanently, with no API able to recover it. So the tests are
 * about the *secret*, not just the happy path — where it goes, where it must
 * never go, and whether it is revealed at exactly the moment it becomes the
 * only way in.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  remainingCalls,
  runHandoff,
  type HandoffState,
  type HandoffTransport,
} from "./handoff";
import { session } from "./store";
import type { ApiError } from "../api/errors";

const TEMP = "tEmP-paSSw0rd-from-server";
const CHOSEN = "the-operator-chose-this";

const INPUT = {
  name: "Meridian Data",
  slug: "meridian-data",
  email_domain: "meridian.example.com",
  admin_email: "ops@meridian.example.com",
  admin_name: "Asha Rao",
  adminPassword: CHOSEN,
};

const CREATED = {
  id: "org-1",
  name: "Meridian Data",
  slug: "meridian-data",
  email_domain: "meridian.example.com",
  is_active: true,
  admin_email: "ops@meridian.example.com",
  admin_temp_password: TEMP,
};

const LOGGED_IN = {
  access_token: "org-token",
  user_id: "user-1",
  name: "Asha Rao",
  role: "org_admin",
  org_id: "org-1",
  org_name: "Meridian Data",
  must_change_password: true,
};

const refusal = (detail: string, status = 422): ApiError => ({
  status,
  detail,
  kind: "http",
});

function transport(over: Partial<HandoffTransport> = {}): HandoffTransport {
  return {
    createOrg: vi.fn(async () => CREATED),
    login: vi.fn(async () => LOGGED_IN),
    changePassword: vi.fn(async () => ({ changed: true })),
    ...over,
  };
}

afterEach(() => {
  session.clear();
});

describe("the happy path", () => {
  it("runs all three calls in order, from one submit", async () => {
    const states: HandoffState[] = [];
    const t = transport();
    const result = await runHandoff(INPUT, (s) => states.push(s), t);

    expect(states.map((s) => (s.phase === "running" ? s.step : s.phase))).toEqual([
      "create",
      "login",
      "password",
      "done",
    ]);
    expect(t.createOrg).toHaveBeenCalledTimes(1);
    expect(t.login).toHaveBeenCalledTimes(1);
    expect(t.changePassword).toHaveBeenCalledTimes(1);
    expect(result.phase).toBe("done");
  });

  it("signs in with the temporary password and changes it to the chosen one", async () => {
    const t = transport();
    await runHandoff(INPUT, () => {}, t);

    expect(t.login).toHaveBeenCalledWith(
      expect.objectContaining({ email: CREATED.admin_email, password: TEMP }),
    );
    // Step 3 is not optional: must_change_password is read by no dependency, so
    // if this console does not force the change, nothing does.
    expect(t.changePassword).toHaveBeenCalledWith(
      LOGGED_IN.access_token,
      { current_password: TEMP, new_password: CHOSEN },
    );
  });

  it("never exposes the temporary password to the caller or the store", async () => {
    // The whole point of D18: on the happy path there is no secret to copy,
    // paste, lose or leave on a clipboard.
    const states: HandoffState[] = [];
    await runHandoff(INPUT, (s) => states.push(s), transport());

    const serialised = JSON.stringify({
      states,
      session: session.get(),
      storage: sessionStorage.getItem("innodhara.session"),
    });
    expect(serialised).not.toContain(TEMP);
  });

  it("establishes the org session and carries email_domain forward", async () => {
    await runHandoff(INPUT, () => {}, transport());
    const org = session.get().org;
    expect(org).toMatchObject({
      token: LOGGED_IN.access_token,
      orgId: CREATED.id,
      orgName: CREATED.name,
      // P7: no org_admin-readable route returns email_domain, and Task 23's
      // domain check needs it. This is the only moment it can be captured.
      emailDomain: CREATED.email_domain,
    });
  });

  it("releases the super-admin token once its one call is done", async () => {
    session.setSuperToken("super-token");
    await runHandoff(INPUT, () => {}, transport());
    expect(session.get().superToken).toBeNull();
    expect(session.get().org).not.toBeNull();
  });
});

describe("step 1 fails — nothing was created", () => {
  it("offers no recovery key, because there is nothing to recover", async () => {
    const t = transport({
      createOrg: vi.fn(async () => {
        throw refusal("Organisation slug 'meridian-data' already exists", 409);
      }),
    });
    const result = await runHandoff(INPUT, () => {}, t);

    expect(result).toMatchObject({
      phase: "failed",
      step: "create",
      recovery: null,
    });
    // An empty password box here would read as "the recovery key is missing",
    // which is far more alarming than the truth.
    expect(t.login).not.toHaveBeenCalled();
    expect(t.changePassword).not.toHaveBeenCalled();
    expect(session.get().org).toBeNull();
  });

  it("surfaces the server's own refusal, unaltered", async () => {
    const detail = "A user with email ops@meridian.example.com already exists";
    const result = await runHandoff(
      INPUT,
      () => {},
      transport({ createOrg: vi.fn(async () => { throw refusal(detail, 409); }) }),
    );
    expect(result.phase === "failed" && result.error.detail).toBe(detail);
  });
});

describe("a step after the first fails — the organisation exists", () => {
  it("reveals the temporary password when login fails", async () => {
    const t = transport({
      login: vi.fn(async () => {
        throw refusal("Wrong email or password", 401);
      }),
    });
    const result = await runHandoff(INPUT, () => {}, t);

    expect(result.phase).toBe("failed");
    if (result.phase !== "failed" || !result.recovery) throw new Error("expected recovery");
    // Hiding it here would convert a recoverable failure into a stranded
    // organisation — §4.2, and the reason this branch exists at all.
    expect(result.recovery.tempPassword).toBe(TEMP);
    expect(result.recovery.orgName).toBe(CREATED.name);
    expect(result.recovery.adminEmail).toBe(CREATED.admin_email);
    expect(result.recovery.intendedPassword).toBe(CHOSEN);
    expect(t.changePassword).not.toHaveBeenCalled();
  });

  it("reveals it when the password change fails", async () => {
    const result = await runHandoff(
      INPUT,
      () => {},
      transport({
        changePassword: vi.fn(async () => {
          throw refusal("New password must be at least 8 characters");
        }),
      }),
    );
    expect(result.phase === "failed" && result.recovery?.tempPassword).toBe(TEMP);
    expect(result.phase === "failed" && result.step).toBe("password");
  });

  it("leaves no org session behind when the chain broke", async () => {
    // A half-established session would let the operator wander into the
    // checklist against an organisation whose password was never set.
    await runHandoff(
      INPUT,
      () => {},
      transport({ changePassword: vi.fn(async () => { throw refusal("no"); }) }),
    );
    expect(session.get().org).toBeNull();
  });

  it("keeps the super-admin token when the chain broke", async () => {
    // The opposite of the happy path: the operator may need to try again, and
    // POST /orgs is the one call that token exists for.
    session.setSuperToken("super-token");
    await runHandoff(
      INPUT,
      () => {},
      transport({ login: vi.fn(async () => { throw refusal("no"); }) }),
    );
    expect(session.get().superToken).toBe("super-token");
  });

  it("names the two calls the operator must finish by hand", async () => {
    const result = await runHandoff(
      INPUT,
      () => {},
      transport({ login: vi.fn(async () => { throw refusal("no"); }) }),
    );
    if (result.phase !== "failed" || !result.recovery) throw new Error("expected recovery");
    const calls = remainingCalls(result.recovery);
    expect(calls).toHaveLength(2);
    expect(calls[0]).toContain("/api/v1/auth/login");
    expect(calls[0]).toContain(CREATED.admin_email);
    expect(calls[1]).toContain("/api/v1/auth/change-password");
  });
});

describe("a response that does not match its schema", () => {
  it("fails the step rather than continuing with a half-parsed reply", async () => {
    // CreateOrgResponse is one of the four typed responses in the whole API, so
    // this one really can be checked — and a missing admin_temp_password must
    // stop the chain, not produce a login attempt with `undefined`.
    const result = await runHandoff(
      INPUT,
      () => {},
      transport({ createOrg: vi.fn(async () => ({ id: "x", name: "y" })) }),
    );
    expect(result.phase).toBe("failed");
    expect(result.phase === "failed" && result.step).toBe("create");
    expect(result.phase === "failed" && result.recovery).toBeNull();
  });
});
