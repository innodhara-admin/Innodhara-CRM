/**
 * The persistent session bar — 06_DESIGN.md §4.2.
 *
 * Names which identity the current action runs as, because the two are not
 * interchangeable: `POST /orgs` needs `super_admin`, and every `/admin/*` route
 * refuses it. An operator who cannot see which session is live will read a 403
 * as a bug in the console.
 *
 * It also carries the base-URL field (Q19) — the backend address is a field in
 * the app, defaulting to `config.py`'s own `127.0.0.1:8000`.
 */
import { useState } from "react";

import { useDrifts } from "../api/drift";
import { session, useSession } from "../session/store";
import { Banner, Button, TextInput, styles as s } from "./primitives";

export function SessionBar() {
  const { baseUrl, superToken, org } = useSession();
  const [draft, setDraft] = useState(baseUrl);
  const dirty = draft.replace(/\/+$/, "") !== baseUrl;

  return (
    <div style={{ display: "grid", gap: "var(--s3)" }}>
      <div>
        <p className={s.eyebrow}>Acting as</p>
        <p style={{ margin: "var(--s1) 0 0", fontSize: "var(--text-sm)" }}>
          {org ? (
            <>
              <strong>{org.name}</strong>
              <span className={s.muted}>{` · ${org.role} · ${org.orgName}`}</span>
            </>
          ) : superToken ? (
            <>
              <strong>Platform operator</strong>
              <span className={s.muted}> · super_admin · no organisation selected</span>
            </>
          ) : (
            <span className={s.muted}>Not signed in</span>
          )}
        </p>
        {superToken && org && (
          <p className={s.muted} style={{ fontSize: "var(--text-xs)", margin: "var(--s1) 0 0" }}>
            A super-admin session is still open. It can only create organisations;
            every organisation route refuses it.
          </p>
        )}
      </div>

      <div>
        <label className={s.eyebrow} htmlFor="session-base-url">
          Backend address
        </label>
        <div style={{ display: "flex", gap: "var(--s2)", marginBlockStart: "var(--s1)" }}>
          <TextInput
            id="session-base-url"
            mono
            value={draft}
            spellCheck={false}
            onChange={(e) => setDraft(e.target.value)}
          />
          <Button disabled={!dirty} onClick={() => session.setBaseUrl(draft)}>
            Use
          </Button>
        </div>
      </div>

      {(org || superToken) && (
        <Button variant="quiet" onClick={() => session.clear()}>
          Sign out
        </Button>
      )}
    </div>
  );
}

/**
 * The drift banner (A1). A read whose shape no longer matches is announced,
 * never swallowed — and the statuses that depend on it show `—`, not `○`.
 */
export function DriftBanner() {
  const drifts = useDrifts();
  if (drifts.length === 0) return null;

  return (
    <Banner tone="blocked" title="This console can no longer read part of the API">
      <p style={{ margin: "0 0 var(--s2)" }}>
        A response no longer matches the shape this console expects. Anything
        derived from it is shown as “cannot be verified”, not as “not started”.
        Regenerate the client with <code>npm run gen:api</code>; if the shape is
        one of the eleven the spec does not declare, update{" "}
        <code>src/api/reads.ts</code>.
      </p>
      <ul style={{ margin: 0, paddingInlineStart: "1.1rem" }}>
        {drifts.map((d) => (
          <li key={d.route} className={s.mono} style={{ fontSize: "var(--text-xs)" }}>
            {d.route} → {d.path}: {d.message}
            {d.receivedKeys.length > 0 && (
              <span className={s.muted}>{` · received: ${d.receivedKeys.join(", ")}`}</span>
            )}
          </li>
        ))}
      </ul>
    </Banner>
  );
}
