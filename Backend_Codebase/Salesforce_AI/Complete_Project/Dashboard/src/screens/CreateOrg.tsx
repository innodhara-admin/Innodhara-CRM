/**
 * Create an organisation, and hand off to its administrator in one submit.
 *
 * The form collects the intended admin password **up front** (D18): that is
 * what removes the human from the chain entirely. The temporary password the
 * server issues is never displayed on the happy path.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { z } from "zod";

import { CONSTRAINTS } from "../api/constraints.generated";
import { runHandoff, type HandoffState } from "../session/handoff";
import { useSession } from "../session/store";
import { HandoffModal } from "../ui/HandoffModal";
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

const C = CONSTRAINTS.CreateOrgRequest;

/**
 * Built from the lifted constraints, not hand-typed: `CreateOrgRequest`'s
 * bounds all survive into `generated.ts` (they sit on required fields), but
 * reading them from one place keeps this form honest if the backend moves.
 *
 * `adminPassword` is the exception — it belongs to no request schema. Its rule
 * lives in `auth.py · change_password`, which is why it is captioned
 * `backend-undeclared` rather than `schema`.
 */
const Form = z.object({
  name: z.string().min(C.name.minLength).max(C.name.maxLength),
  slug: z.string().min(C.slug.minLength).max(C.slug.maxLength).regex(new RegExp(C.slug.pattern)),
  email_domain: z
    .string()
    .min(C.email_domain.minLength)
    .max(C.email_domain.maxLength),
  admin_email: z.string().email(),
  admin_name: z.string().min(1),
  logo_url: z.string().optional(),
  adminPassword: z.string().min(8),
});

type FormValues = z.infer<typeof Form>;

const EMPTY: FormValues = {
  name: "",
  slug: "",
  email_domain: "",
  admin_email: "",
  admin_name: "",
  logo_url: "",
  adminPassword: "",
};

export function CreateOrg() {
  const navigate = useNavigate();
  const { superToken } = useSession();
  const [values, setValues] = useState<FormValues>(EMPTY);
  const [errors, setErrors] = useState<Partial<Record<keyof FormValues, string>>>({});
  const [handoff, setHandoff] = useState<HandoffState | null>(null);

  function set<K extends keyof FormValues>(key: K, value: FormValues[K]) {
    setValues((v) => ({ ...v, [key]: value }));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const parsed = Form.safeParse(values);
    if (!parsed.success) {
      const next: Partial<Record<keyof FormValues, string>> = {};
      for (const issue of parsed.error.issues) {
        next[issue.path[0] as keyof FormValues] = issue.message;
      }
      setErrors(next);
      return;
    }
    setErrors({});
    const result = await runHandoff(parsed.data, setHandoff);
    if (result.phase === "done") navigate("/checklist");
  }

  if (!superToken) {
    return (
      <main style={{ maxInlineSize: "40rem", margin: "0 auto", padding: "var(--s7) var(--s4)" }}>
        <Masthead />
        <Banner tone="note" title="A platform session is needed to create an organisation">
          <p style={{ margin: 0 }}>
            <code>POST /orgs</code> is the only route in this console that needs
            the super-admin session. Sign in as the platform operator first.
          </p>
        </Banner>
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Button variant="primary" onClick={() => navigate("/sign-in")}>
            Go to sign in
          </Button>
        </div>
      </main>
    );
  }

  return (
    <main style={{ maxInlineSize: "44rem", margin: "0 auto", padding: "var(--s6) var(--s4) var(--s7)" }}>
      <Masthead />

      <Panel eyebrow="Checklist item 1" title="Organisation and its first administrator">
        <Banner tone="warn" title="One submit, three calls, and no secret to carry">
          <p style={{ margin: 0 }}>
            The server issues a temporary password for the administrator and
            returns it exactly once. This console signs in with it and replaces it
            with the password you choose below, without showing it to anyone. If a
            step fails after the organisation exists, it is revealed then — as a
            recovery key.
          </p>
        </Banner>

        <form onSubmit={submit} style={{ marginBlockStart: "var(--s4)" }}>
          <Field
            label="Organisation name"
            htmlFor="org-name"
            required
            enforcement={{ kind: "schema" }}
            caption={`${C.name.minLength}–${C.name.maxLength} characters · you type this back to confirm a reset`}
            error={errors.name}
          >
            <TextInput
              id="org-name"
              value={values.name}
              onChange={(e) => set("name", e.target.value)}
            />
          </Field>

          <Field
            label="Slug"
            htmlFor="org-slug"
            required
            enforcement={{ kind: "schema" }}
            caption={`${C.slug.pattern} · lowercase, digits and hyphens`}
            error={errors.slug}
          >
            <TextInput
              id="org-slug"
              mono
              value={values.slug}
              onChange={(e) => set("slug", e.target.value)}
            />
          </Field>

          <Field
            label="Email domain"
            htmlFor="org-domain"
            required
            enforcement={{
              kind: "backend-undeclared",
              source: "organisations.py · create_organisation",
            }}
            caption="a leading @ is stripped and the result must look like a domain · every staff email must end with it"
            error={errors.email_domain}
          >
            <TextInput
              id="org-domain"
              mono
              placeholder="example.com"
              value={values.email_domain}
              onChange={(e) => set("email_domain", e.target.value)}
            />
          </Field>

          <Field
            label="Administrator name"
            htmlFor="org-admin-name"
            required
            enforcement={{ kind: "schema" }}
            caption="the person who will run this organisation's setup"
            error={errors.admin_name}
          >
            <TextInput
              id="org-admin-name"
              value={values.admin_name}
              onChange={(e) => set("admin_name", e.target.value)}
            />
          </Field>

          <Field
            label="Administrator email"
            htmlFor="org-admin-email"
            required
            enforcement={{ kind: "schema" }}
            caption="must not already exist on any organisation"
            error={errors.admin_email}
          >
            <TextInput
              id="org-admin-email"
              type="email"
              value={values.admin_email}
              onChange={(e) => set("admin_email", e.target.value)}
            />
          </Field>

          <Field
            label="Administrator password"
            htmlFor="org-admin-password"
            required
            enforcement={{ kind: "backend-undeclared", source: "auth.py · change_password" }}
            caption="at least 8 characters · set on this account immediately, replacing the server's temporary one"
            error={errors.adminPassword}
          >
            <TextInput
              id="org-admin-password"
              type="password"
              autoComplete="new-password"
              value={values.adminPassword}
              onChange={(e) => set("adminPassword", e.target.value)}
            />
          </Field>

          <Field
            label="Logo URL"
            htmlFor="org-logo"
            enforcement={{
              kind: "ui-only",
              why: "organisations.py stores it unvalidated, and there is no PATCH /orgs/{id} — branding is write-once and cannot be corrected through any API",
            }}
            caption="optional · set now or never"
          >
            <TextInput
              id="org-logo"
              mono
              value={values.logo_url ?? ""}
              onChange={(e) => set("logo_url", e.target.value)}
            />
          </Field>

          <div style={{ marginBlockStart: "var(--s5)" }}>
            <Button variant="primary" type="submit" disabled={handoff?.phase === "running"}>
              Create organisation and hand off
            </Button>
          </div>
        </form>

        <p className={s.muted} style={{ fontSize: "var(--text-xs)", marginBlockStart: "var(--s4)" }}>
          A crash between the organisation being created and the password being
          changed still strands it — this removes every window a person could lose
          the secret through, not the last one the process itself can hit.
        </p>
      </Panel>

      <div style={{ marginBlockStart: "var(--s5)" }}>
        <Panel eyebrow="Connection">
          <SessionBar />
        </Panel>
      </div>

      {handoff && (
        <HandoffModal state={handoff} onDismissFailure={() => setHandoff(null)} />
      )}
    </main>
  );
}
