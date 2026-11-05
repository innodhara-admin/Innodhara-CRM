/**
 * Item 16 — suppliers of inbound mail. **Permanently unavailable.**
 *
 * No form, no fields, no "coming soon". This screen exists to say why the item
 * cannot be done here and what to do instead, and it is the only one of the
 * sixteen with nothing to submit.
 *
 * Three separate reasons, and they compound:
 *
 *  - **No storage.** `INBOUND_EMAIL_MODE`, `IMAP_HOST`, `IMAP_PORT` and
 *    `INBOUND_POLL_SECONDS` are environment variables. There is no column, no
 *    endpoint and no per-organisation record of any of it — unlike email
 *    sending, where at least the credentials half is per-org.
 *  - **It is process-wide.** One switch for every organisation on the server,
 *    so even a route could not make it a per-tenant choice.
 *  - **It is open finding F35**, with a standing instruction to keep it off.
 *
 * The status derivation deliberately takes **no read at all** for this row —
 * `deriveStatus` ignores its argument for item 16 — so no response can move it
 * and no drift can make it look like something else.
 */
import { ITEM_BY_NUMBER } from "../checklist/items";
import type { ItemStatus } from "../checklist/status";
import { ItemHeading, Section } from "../ui/ItemScreen";
import { Banner, DataTable, Quote, styles as s } from "../ui/primitives";

export function InboundMail({ status }: { status: ItemStatus }) {
  const row = ITEM_BY_NUMBER.get(16)!;

  return (
    <>
      <ItemHeading item={16} marker={status.marker} caption={status.caption} />

      <Section title="What to do instead" eyebrow="The manual's own answer">
        <Quote source={row.manualRef}>{row.quote}</Quote>
        <Banner tone="note" title="This is not a workaround">
          <p style={{ margin: 0, maxInlineSize: "var(--measure)" }}>
            {row.ifSkipped}
          </p>
        </Banner>
        <p className={s.muted} style={{ fontSize: "var(--text-sm)", marginBlockStart: "var(--s4)", maxInlineSize: "var(--measure)" }}>
          Replies logged by hand are ordinary replies: they thread, they stop the
          nudge ladder, and they feed the same engines an automatically read one
          would. Nothing downstream is degraded by capturing them this way.
        </p>
      </Section>

      <Section title="Why there is no form here" eyebrow="Three reasons, all of them fatal">
        <DataTable
          columns={["", "Reason"]}
          rows={[
            [
              <span key="a" className={s.mono}>storage</span>,
              "No column, no endpoint, no per-organisation record. Unlike email sending, not even half of it is stored per tenant.",
            ],
            [
              <span key="b" className={s.mono}>scope</span>,
              "INBOUND_EMAIL_MODE, IMAP_HOST, IMAP_PORT and INBOUND_POLL_SECONDS are process-wide environment variables — one setting for every organisation on this server.",
            ],
            [
              <span key="c" className={s.mono}>policy</span>,
              "Open finding F35, with a standing instruction to keep it off. The demo runbook says so in bold.",
            ],
          ]}
        />
        <p className={s.muted} style={{ fontSize: "var(--text-sm)", marginBlockStart: "var(--s4)" }}>
          This row's marker takes no reading from the API at all — not even the{" "}
          <code>inbound_email_mode</code> the settings response happens to
          return. A status derived from a read can drift; this one is a fact
          about the API's shape and cannot.
        </p>
      </Section>
    </>
  );
}
