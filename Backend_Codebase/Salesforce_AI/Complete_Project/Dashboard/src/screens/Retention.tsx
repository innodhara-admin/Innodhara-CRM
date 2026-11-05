/**
 * Item 12 — retention windows.
 *
 * The same `org_settings` row as item 10, and the one checklist row this
 * console can never verify (**P12**). `POST /orgs` seeds both columns from
 * `DEFAULT_AUDIO_RETENTION_DAYS` and `DEFAULT_TRANSCRIPT_RETENTION_DAYS`, and
 * **no route returns either env value** — `config.py` declares them,
 * `organisations.py` reads them, and that is the whole of it. So nothing the
 * API can say separates "the operator chose 90 days" from "the server's
 * environment said 90 days", and the row is `◐` whatever the numbers are.
 *
 * That is not a hedge about whether the windows apply. They apply: the columns
 * are NOT NULL, the retention service reads them, and recordings really are
 * deleted on that schedule. What is withheld is the claim that somebody chose
 * them — and this screen says which of the two it is asserting.
 *
 * A third window exists that the manual's checklist never mentions:
 * `assistant_history_retention_days` drops assistant conversations older than
 * 90 days. It is **env-only, not per-org**, and has no control anywhere.
 */
import { endpoints } from "../api/endpoints";
import { SettingsRead } from "../api/reads";
import type { ItemStatus } from "../checklist/status";
import { ITEM_BY_NUMBER } from "../checklist/items";
import { ItemHeading, ReadError, Section, useList } from "../ui/ItemScreen";
import { Banner, DataTable, Quote, styles as s } from "../ui/primitives";

export function Retention({ status }: { status: ItemStatus }) {
  const settings = useList("settings", endpoints.settings, SettingsRead);
  const row = ITEM_BY_NUMBER.get(12)!;

  return (
    <>
      <ItemHeading item={12} marker={status.marker} caption={status.caption} />

      <Section title="What is kept, and for how long" eyebrow="In force">
        {settings.isError ? (
          <ReadError error={settings.error} what="the retention windows" />
        ) : !settings.data ? (
          <p className={s.muted} style={{ margin: 0 }}>Reading…</p>
        ) : (
          <DataTable
            columns={["What", "Kept for", "Then"]}
            rows={[
              [
                "Recordings",
                <span key="a" className={s.mono}>{`${settings.data.audio_retention_days} days`}</span>,
                "the audio file is deleted",
              ],
              [
                "Transcripts",
                <span key="t" className={s.mono}>{`${settings.data.transcript_retention_days} days`}</span>,
                "the transcript is archived and scrubbed",
              ],
              [
                <span key="h">
                  Assistant conversations
                  <span className={s.muted}> · not on the checklist</span>
                </span>,
                <span key="hv" className={s.muted}>90 days, from the environment</span>,
                "dropped — a chat buffer must not quietly become a permanent store",
              ],
            ]}
          />
        )}
      </Section>

      <Section title="Why this row is amber and not green" eyebrow="P12">
        <Banner tone="note" title="The windows are real; the choice cannot be verified">
          <p style={{ margin: "0 0 var(--s2)" }}>
            Both numbers above are in force. What this console will not claim is
            that anybody <em>chose</em> them: <code>POST /orgs</code> writes both
            columns from environment variables, and no endpoint returns those
            variables, so a stored 90 is indistinguishable from a seeded 90.
          </p>
          <p style={{ margin: 0 }}>
            Set them deliberately on <strong>item 10</strong>, which edits the
            same row. The marker here will stay amber even then — not because the
            change did not take, but because no reading of the API could tell
            you it did.
          </p>
        </Banner>
      </Section>

      <Section title="The manual on this item" eyebrow="Verbatim">
        <Quote source={row.manualRef}>{row.quote}</Quote>
        <p style={{ maxInlineSize: "var(--measure)" }}>
          <strong>If you skip it: </strong>
          {row.ifSkipped}
        </p>
      </Section>
    </>
  );
}
