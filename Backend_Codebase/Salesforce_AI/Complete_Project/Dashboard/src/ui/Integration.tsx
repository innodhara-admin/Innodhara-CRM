/**
 * The shared half of items 11 and 14 — Task 19 Step 4 / Task 20 Step 2.
 *
 * Both are the same fact with different nouns: **stored credentials plus a
 * process-wide mode**, and nothing leaves unless both hold. `email_service.py`
 * returns a `dry_run:<path>` file unless `email_mode == "smtp"` *and* creds
 * exist; `calendar_service.py` mirrors nothing unless `calendar_mode ==
 * "google"` *and* a credentials file and calendar id are set.
 *
 * Three things every integration panel must say, because each is a way the
 * operator gets a false impression:
 *
 *  1. **The mode is an environment variable this console cannot change.** It is
 *     shown read-only, with its live value, next to a form that *can* change
 *     the other half. Without that, storing credentials looks like finishing
 *     the job — which is the exact failure the manual warns about twice.
 *  2. **None of the three PUT routes returns what it stored.** After saving,
 *     the console re-reads `GET /admin/settings` and reports the boolean it
 *     gets back. It never echoes what was typed.
 *  3. **Credentials are write-only.** Nothing returns a stored username or
 *     token, so the form is always blank and saving always replaces.
 */
import { useState } from "react";
import type { ReactNode } from "react";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { SettingsRead, type Settings } from "../api/reads";
import { asApiError, ReadError, Section, useList, useWrite } from "./ItemScreen";
import {
  Banner,
  Button,
  DataTable,
  Field,
  StatusMarker,
  TextInput,
  styles as s,
} from "./primitives";

export type CredentialField = {
  name: string;
  label: string;
  caption: string;
};

export function IntegrationPanel({
  title,
  route,
  fields,
  modeVar,
  credentialsStored,
  configured,
  modeValue,
  note,
}: {
  title: string;
  /** The PUT this panel writes to. */
  route: string;
  fields: readonly CredentialField[];
  /** The env var that carries the other half, e.g. `EMAIL_MODE`. */
  modeVar: string;
  credentialsStored: (s: Settings) => boolean;
  /** Both halves — read from the settings response, never assumed. */
  configured: (s: Settings) => boolean;
  /** The env var's live value, for the read-only row. */
  modeValue: (s: Settings) => string;
  note?: ReactNode;
}) {
  const settings = useList("settings", endpoints.settings, SettingsRead);
  const [values, setValues] = useState<Record<string, string>>({});
  const [afterSave, setAfterSave] = useState<string | null>(null);

  const save = useWrite<Record<string, string>>(["settings"], async (body) => {
    const reply = await request(route, { as: "org", method: "PUT", body });
    // The PUT returns nothing useful. Re-read and report what the server says
    // now, rather than echoing what was typed.
    const after = await request(endpoints.settings, { as: "org", shape: SettingsRead });
    setAfterSave(
      credentialsStored(after)
        ? configured(after)
          ? `Stored. ${modeVar}=${modeValue(after)} on this server, so this really does leave.`
          : `Stored — and still OFF. ${modeVar}=${modeValue(after)} on this server, so nothing leaves. This console cannot change that; it is a process-wide environment variable.`
        : "The server accepted the request but still reports no credentials stored. Look before relying on this.",
    );
    setValues({});
    return reply;
  });

  if (settings.isError) return <ReadError error={settings.error} what="the integration state" />;
  if (!settings.data) {
    return (
      <Section title={title} eyebrow="Reading">
        <p className={s.muted} style={{ margin: 0 }}>Reading…</p>
      </Section>
    );
  }

  const live = settings.data;
  const stored = credentialsStored(live);
  const on = configured(live);

  return (
    <Section title={title} eyebrow="Two halves, both required">
      <DataTable
        columns={["", "Half", "State", "Who controls it"]}
        rows={[
          [
            <StatusMarker
              key="a"
              status={stored ? "done" : "none"}
              label={stored ? "stored" : "not stored"}
            />,
            "Credentials",
            stored ? "stored" : "not stored",
            "this console, below",
          ],
          [
            <StatusMarker
              key="b"
              status={on ? "done" : "partial"}
              label={on ? "on" : "off"}
            />,
            "Sending",
            <span key="m" className={s.mono}>{`${modeVar}=${modeValue(live)}`}</span>,
            <span key="w">
              the server's environment —{" "}
              <strong>this console cannot change it</strong>
            </span>,
          ],
        ]}
      />

      {stored && !on && (
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Banner tone="warn" title="Credentials stored · sending is OFF on this server">
            <p style={{ margin: 0 }}>
              This is the state the product manual warns about twice. Everything
              looks configured, approvals go through, and the messages are
              written to a file. Only a change to <code>{modeVar}</code> in the
              server's environment turns it on — no screen in this console can.
            </p>
          </Banner>
        </div>
      )}

      {afterSave && (
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Banner tone={afterSave.includes("really does leave") ? "note" : "warn"} title="Saved">
            <p style={{ margin: 0 }}>{afterSave}</p>
          </Banner>
        </div>
      )}

      {note && <div style={{ marginBlockStart: "var(--s4)" }}>{note}</div>}

      <div style={{ marginBlockStart: "var(--s5)" }}>
        {fields.map((field) => (
          <Field
            key={field.name}
            label={field.label}
            htmlFor={`integration-${field.name}`}
            enforcement={{ kind: "ui-only", why: "the server stores whatever it is sent and never returns it" }}
            caption={field.caption}
          >
            <TextInput
              id={`integration-${field.name}`}
              mono
              autoComplete="off"
              value={values[field.name] ?? ""}
              onChange={(e) => setValues({ ...values, [field.name]: e.target.value })}
            />
          </Field>
        ))}

        <p className={s.muted} style={{ fontSize: "var(--text-xs)" }}>
          Nothing here is ever read back — no route returns a stored username,
          token or path — so these boxes start empty every time and saving
          replaces whatever was there.
        </p>

        <Button
          variant="primary"
          disabled={save.isPending || fields.some((f) => !values[f.name]?.trim())}
          onClick={() => save.mutate(values)}
        >
          {save.isPending ? "Saving…" : "Store credentials"}
        </Button>
      </div>

      {save.error && (
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Banner
            tone="blocked"
            title="The server refused"
            serverMessage={asApiError(save.error)?.detail ?? String(save.error)}
          />
        </div>
      )}
    </Section>
  );
}
