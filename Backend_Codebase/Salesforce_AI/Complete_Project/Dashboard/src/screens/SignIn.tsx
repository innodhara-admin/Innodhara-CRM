/**
 * Sign in — the entry point for a returning operator (P6 / A5).
 *
 * `POST /auth/login` is the same route for both identities, so this one form
 * serves both: a `super_admin` reply opens the organisation screen, an org role
 * opens the checklist. `GET /orgs` is super-admin-only, so nothing here depends
 * on it.
 *
 * If the server says `must_change_password`, the change is forced before
 * anything else — the same rule as the hand-off's step 3, for the same reason:
 * **the flag enforces nothing on its own.**
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { schemas } from "../api/generated";
import { isApiError } from "../api/errors";
import { session } from "../session/store";
import {
  Banner,
  Button,
  Field,
  Masthead,
  Panel,
  TextInput,
  styles as s,
} from "../ui/primitives";
import { SessionBar } from "../ui/SessionBar";

const LoginResponse = schemas.LoginResponse;

export function SignIn() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [mustChange, setMustChange] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const reply = LoginResponse.parse(
        await request(endpoints.login, {
          as: "none",
          method: "POST",
          body: { email, password },
        }),
      );

      if (reply.must_change_password) {
        if (!mustChange) {
          // Ask for the new password rather than letting them in: nothing in
          // the backend enforces this flag, so this screen is the enforcement.
          setMustChange(true);
          setBusy(false);
          return;
        }
        await request(endpoints.changePassword, {
          as: "none",
          method: "POST",
          bearer: reply.access_token,
          body: { current_password: password, new_password: newPassword },
        });
      }

      if (reply.role === "super_admin") {
        session.setSuperToken(reply.access_token);
        navigate("/orgs");
        return;
      }

      session.setOrg({
        token: reply.access_token,
        userId: reply.user_id,
        name: reply.name,
        role: reply.role,
        orgId: reply.org_id ?? "",
        orgName: reply.org_name ?? "",
      });
      navigate("/checklist");
    } catch (cause) {
      setError(isApiError(cause) ? cause.detail : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{ maxInlineSize: "34rem", margin: "0 auto", padding: "var(--s7) var(--s4)" }}>
      <Masthead />
      <Panel eyebrow="Sign in" title="Who is setting this up?">
        {error && (
          <div style={{ marginBlockEnd: "var(--s4)" }}>
            <Banner tone="blocked" title="Could not sign in" serverMessage={error} />
          </div>
        )}
        <form onSubmit={submit}>
          <Field label="Email" htmlFor="signin-email" required>
            <TextInput
              id="signin-email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </Field>
          <Field label="Password" htmlFor="signin-password" required>
            <TextInput
              id="signin-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </Field>

          {mustChange && (
            <Field
              label="New password"
              htmlFor="signin-new-password"
              required
              enforcement={{ kind: "backend-undeclared", source: "auth.py · change_password" }}
              caption="at least 8 characters"
            >
              <TextInput
                id="signin-new-password"
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                minLength={8}
                required
              />
            </Field>
          )}

          <div style={{ display: "flex", gap: "var(--s3)", marginBlockStart: "var(--s4)" }}>
            <Button variant="primary" type="submit" disabled={busy}>
              {busy ? "Signing in…" : mustChange ? "Change password and continue" : "Sign in"}
            </Button>
          </div>
        </form>

        {mustChange && (
          <p className={s.muted} style={{ fontSize: "var(--text-sm)", marginBlockStart: "var(--s4)" }}>
            This account is still on a temporary password. Nothing in the backend
            enforces that it be changed, so it is enforced here.
          </p>
        )}
      </Panel>

      <div style={{ marginBlockStart: "var(--s5)" }}>
        <Panel eyebrow="Connection">
          <SessionBar />
        </Panel>
      </div>
    </main>
  );
}
