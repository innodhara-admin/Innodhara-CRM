/**
 * WhatsApp on item 11 (4 Nov 2026): choose Off / Wati / Meta, store that
 * provider's credentials, switch staff updates on per kind, send a test, and
 * check the templates the provider holds.
 *
 * The same rules as `IntegrationPanel`: credentials are write-only (the boxes
 * always start empty and saving replaces), and after every write the panel
 * re-reads `GET /admin/settings` and reports what the server says, never what
 * was typed. Decisions live in `whatsappPanel.ts`.
 */
import { useState } from "react";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { SettingsRead } from "../api/reads";
import { asApiError, ReadError, Section, useList, useWrite } from "../ui/ItemScreen";
import {
  Banner,
  Button,
  Checkbox,
  DataTable,
  Field,
  Select,
  StatusMarker,
  TextInput,
  styles as s,
} from "../ui/primitives";
import {
  kindLabel,
  PROVIDER_OPTIONS,
  TemplatesRead,
  testOutcome,
  TestRead,
  whatsappState,
  type Provider,
  type TemplatesCheck,
} from "./whatsappPanel";

type Fields = Record<string, string>;

const WATI_FIELDS = [
  { name: "wati_token", label: "Wati API token", caption: "from Wati, API Docs page · encrypted at rest, never shown again" },
  { name: "wati_channel", label: "Sending number", caption: "the WhatsApp number in Wati, with country code, e.g. 917975779676 · blank uses Wati's default" },
  { name: "wati_host", label: "API host", caption: "leave blank for https://live-mt-server.wati.io" },
  { name: "country_code", label: "Country code for 10-digit numbers", caption: "blank keeps the current one (91 for India)" },
];
const META_FIELDS = [
  { name: "access_token", label: "Access token", caption: "encrypted at rest" },
  { name: "phone_number_id", label: "Phone number id", caption: "from the WhatsApp Cloud API console" },
  { name: "country_code", label: "Country code for 10-digit numbers", caption: "blank keeps the current one (91 for India)" },
];

export function WhatsAppPanel() {
  const settings = useList("settings", endpoints.settings, SettingsRead);
  const [provider, setProvider] = useState<Provider | null>(null);
  const [values, setValues] = useState<Fields>({});
  const [kindsOff, setKindsOff] = useState<string[] | null>(null);
  const [staffOn, setStaffOn] = useState<boolean | null>(null);
  const [testTo, setTestTo] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [templates, setTemplates] = useState<TemplatesCheck | null>(null);

  const store = useWrite<Fields>(["settings"], async (body) => {
    await request(endpoints.whatsappIntegration, { as: "org", method: "PUT", body });
    const after = await request(endpoints.settings, { as: "org", shape: SettingsRead });
    setNotice(
      after.whatsapp_credentials_stored
        ? `Stored. Provider is ${after.whatsapp_provider}.`
        : `Saved, but the server still reports no ${after.whatsapp_provider} credentials. Look before relying on this.`,
    );
    setValues({});
  });
  const saveStaff = useWrite<{ enabled: boolean; kinds_off: string[] }>(["settings"], async (body) => {
    await request(endpoints.whatsappStaffUpdates, { as: "org", method: "PATCH", body });
    setNotice(body.enabled ? "Staff updates are on." : "Staff updates are off.");
  });
  const sendTest = useWrite<{ to: string }>([], async (body) => {
    const r = await request(endpoints.whatsappTest, { as: "org", method: "POST", body, shape: TestRead });
    setNotice(testOutcome(r));
  });
  const check = useWrite<void>([], async () => {
    setTemplates(await request(endpoints.whatsappTemplates, { as: "org", shape: TemplatesRead }));
  });

  if (settings.isError) return <ReadError error={settings.error} what="the WhatsApp settings" />;
  if (!settings.data) {
    return (
      <Section title="WhatsApp" eyebrow="Reading">
        <p className={s.muted} style={{ margin: 0 }}>Reading…</p>
      </Section>
    );
  }

  const live = settings.data;
  const state = whatsappState(live, window.location.origin);
  const chosen: Provider = provider ?? state.provider;
  const fields = chosen === "wati" ? WATI_FIELDS : chosen === "meta" ? META_FIELDS : [];
  const off = new Set(kindsOff ?? live.whatsapp_kinds_off);
  const enabled = staffOn ?? live.whatsapp_staff_updates;
  const error = store.error ?? saveStaff.error ?? sendTest.error ?? check.error;

  return (
    <Section title="WhatsApp" eyebrow="Provider, staff updates, test">
      <DataTable
        columns={["", "What", "State", "Who controls it"]}
        rows={[
          [
            <StatusMarker key="p" status={state.provider === "off" ? "none" : "done"} label={state.provider} />,
            "Provider",
            state.provider,
            "this console, below",
          ],
          [
            <StatusMarker key="c" status={live.whatsapp_credentials_stored ? "done" : "none"} label="credentials" />,
            "Credentials",
            live.whatsapp_credentials_stored ? "stored" : "not stored",
            "this console, below",
          ],
          [
            <StatusMarker key="m" status={state.sending ? "done" : "partial"} label={state.sending ? "on" : "off"} />,
            "Sending",
            <span key="v" className={s.mono}>{`WHATSAPP_MODE=${live.whatsapp_mode}`}</span>,
            "the server's settings, not this console",
          ],
          [
            <StatusMarker key="u" status={live.public_base_url_set ? "done" : "partial"} label="documents" />,
            "Documents (PDF)",
            live.public_base_url_set ? "PUBLIC_BASE_URL set" : "PUBLIC_BASE_URL not set",
            "the server's settings, not this console",
          ],
        ]}
      />

      {state.warning && (
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Banner tone="warn" title="Before WhatsApp works">
            <p style={{ margin: 0 }}>{state.warning}</p>
          </Banner>
        </div>
      )}
      {notice && (
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Banner tone="note" title="Done">
            <p style={{ margin: 0 }}>{notice}</p>
          </Banner>
        </div>
      )}
      {error && (
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <Banner tone="blocked" title="The server refused" serverMessage={asApiError(error)?.detail ?? String(error)} />
        </div>
      )}

      <h3>Provider</h3>
      <Field label="Send WhatsApp through" htmlFor="wa-provider">
        <Select
          id="wa-provider"
          options={PROVIDER_OPTIONS}
          value={chosen}
          onChange={(e) => {
            setProvider(e.target.value as Provider);
            setValues({});
          }}
        />
      </Field>
      {fields.map((f) => (
        <Field
          key={f.name}
          label={f.label}
          htmlFor={`wa-${f.name}`}
          enforcement={{ kind: "ui-only", why: "the server stores whatever it is sent and never returns it" }}
          caption={f.caption}
        >
          <TextInput
            id={`wa-${f.name}`}
            mono
            autoComplete="off"
            value={values[f.name] ?? ""}
            onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
          />
        </Field>
      ))}
      <Button
        variant="primary"
        disabled={store.isPending}
        onClick={() => store.mutate({ provider: chosen, ...values })}
      >
        {store.isPending ? "Saving…" : "Store"}
      </Button>
      {state.webhookUrl && (
        <p className={s.muted} style={{ fontSize: "var(--text-sm)" }}>
          Delivery reports: paste this address into Wati's webhook settings.{" "}
          <span className={s.mono}>{state.webhookUrl}</span>
        </p>
      )}

      <h3>Staff updates</h3>
      <p className={s.muted} style={{ fontSize: "var(--text-sm)" }}>
        Every update a person sees in the app also goes to their WhatsApp (their WhatsApp number, or
        their phone when that is empty), during working hours and never while they are on leave. Untick
        a kind to stop sending it.
      </p>
      <Checkbox
        id="wa-staff-on"
        label="Send staff updates on WhatsApp"
        checked={enabled}
        onChange={(e) => setStaffOn(e.target.checked)}
      />
      {live.whatsapp_notification_kinds.map((k) => (
        <Checkbox
          key={k}
          id={`wa-kind-${k}`}
          label={kindLabel(k)}
          checked={!off.has(k)}
          disabled={!enabled}
          onChange={(e) => {
            const next = new Set(off);
            if (e.target.checked) next.delete(k);
            else next.add(k);
            setKindsOff([...next].sort());
          }}
        />
      ))}
      <Button
        disabled={saveStaff.isPending}
        onClick={() => saveStaff.mutate({ enabled, kinds_off: [...off].sort() })}
      >
        {saveStaff.isPending ? "Saving…" : "Save staff updates"}
      </Button>

      <h3>Test</h3>
      <Field label="Send the test message to" htmlFor="wa-test-to" caption="a mobile number, e.g. 9310524629">
        <TextInput id="wa-test-to" mono value={testTo} onChange={(e) => setTestTo(e.target.value)} />
      </Field>
      <Button disabled={sendTest.isPending || !testTo.trim()} onClick={() => sendTest.mutate({ to: testTo.trim() })}>
        {sendTest.isPending ? "Sending…" : "Send a test message"}
      </Button>

      <h3>Templates</h3>
      <p className={s.muted} style={{ fontSize: "var(--text-sm)" }}>
        WhatsApp only lets a business start a conversation with templates it approved in advance. This
        compares the six this system sends with what Wati holds.
      </p>
      <Button disabled={check.isPending} onClick={() => check.mutate()}>
        {check.isPending ? "Checking…" : "Check templates"}
      </Button>
      {templates && (
        <div style={{ marginBlockStart: "var(--s4)" }}>
          {!templates.checked && (
            <p className={s.muted}>
              {templates.error ?? "Only Wati can be checked from here. For Meta, look in Meta Business Manager."}
            </p>
          )}
          <DataTable
            columns={["Template", "Values", "In the provider", "Status"]}
            rows={templates.templates.map((t) => [
              <span key="n" className={s.mono}>{t.name}</span>,
              (t.document ? "PDF + " : "") + t.values.join(", "),
              t.found === null ? "not checked" : t.found ? (t.values_match ? "yes" : "yes, but its values differ") : "missing",
              t.status ?? "",
            ])}
          />
        </div>
      )}
    </Section>
  );
}
