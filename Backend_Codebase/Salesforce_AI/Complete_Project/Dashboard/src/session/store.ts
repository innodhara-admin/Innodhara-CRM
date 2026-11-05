/**
 * Two sessions, one hand-off — 06_DESIGN.md §4.2.
 *
 * `POST /orgs` needs `super_admin`, and every `/admin/*` route **refuses**
 * `super_admin` by design (`deps.py · get_org_context`, D1/Q14 — verified
 * against the running server: a super-admin token on `GET /admin/users` returns
 * 403 "This endpoint is organisation-scoped"). The two identities are not
 * interchangeable, so the console holds both and picks per call.
 *
 * **`sessionStorage`, never `localStorage`** — the super-admin token especially,
 * and neither should survive the tab.
 */
import { useSyncExternalStore } from "react";

import { defaultBaseUrlForThisPage } from "./baseUrl";

export type Identity = "super" | "org";

export type OrgSession = {
  token: string;
  userId: string;
  name: string;
  role: string;
  orgId: string;
  orgName: string;
  /**
   * Held from `POST /orgs` when this tab created the organisation. No
   * org_admin-readable route returns it — `MeResponse` has `org_slug` but not
   * `email_domain`, and `GET /orgs` is super-admin only (P6/P7) — so the
   * go-live domain check (Task 23) falls back when this is absent.
   */
  emailDomain?: string;
};

export type SessionState = {
  baseUrl: string;
  superToken: string | null;
  org: OrgSession | null;
};

/**
 * Where to start: this page's own origin when the backend is serving the
 * console at `/dashboard`, and `config.py`'s default otherwise. Nothing
 * hard-codes 9010 — that is a demo-runbook override, not a default (Q19), and
 * the address remains a field in the app, editable. See `baseUrl.ts` for why
 * the previous unconditional `127.0.0.1:8000` was wrong everywhere but here.
 */
export const DEFAULT_BASE_URL = defaultBaseUrlForThisPage();

const KEY = "innodhara.session";

function load(): SessionState {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<SessionState>;
      return {
        baseUrl: parsed.baseUrl || DEFAULT_BASE_URL,
        superToken: parsed.superToken ?? null,
        org: parsed.org ?? null,
      };
    }
  } catch {
    // A corrupt session is not worth a crash on boot; start clean.
  }
  return { baseUrl: DEFAULT_BASE_URL, superToken: null, org: null };
}

let state: SessionState = load();
const listeners = new Set<() => void>();

function commit(next: SessionState): void {
  state = next;
  try {
    sessionStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    // Storage can be unavailable (private mode, quota). The session still works
    // for this page view; losing it on reload is preferable to failing here.
  }
  listeners.forEach((l) => l());
}

export const session = {
  get: (): SessionState => state,

  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },

  setBaseUrl(baseUrl: string): void {
    commit({ ...state, baseUrl: baseUrl.replace(/\/+$/, "") });
  },

  setSuperToken(token: string | null): void {
    commit({ ...state, superToken: token });
  },

  setOrg(org: OrgSession | null): void {
    commit({ ...state, org });
  },

  /**
   * Drop the super-admin token. §1.1: the console holds that identity for
   * exactly one call. Once the hand-off has completed there is no reason to
   * keep the most privileged token in the tab, so Task 14 calls this.
   */
  releaseSuper(): void {
    commit({ ...state, superToken: null });
  },

  clear(): void {
    commit({ baseUrl: state.baseUrl, superToken: null, org: null });
  },

  tokenFor(identity: Identity): string | null {
    return identity === "super" ? state.superToken : (state.org?.token ?? null);
  },
};

export function useSession(): SessionState {
  return useSyncExternalStore(session.subscribe, session.get, session.get);
}
