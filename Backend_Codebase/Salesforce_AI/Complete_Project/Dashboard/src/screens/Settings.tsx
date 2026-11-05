/**
 * Item 10 — the behaviour dials. (Item 12 reads the same row; see `Retention`.)
 *
 * ## The bounds only `CONSTRAINTS` knows
 *
 * `SettingsRequest` is all-optional, so FastAPI renders every field as an
 * `anyOf` and the generator drops every constraint inside one — **14 of the 25
 * dials** (P2). Without the lift the form would silently accept
 * `assignment_mode: "nonsense"`, `max_unanswered_nudges: 99`,
 * `workday_start: "9am"`, and let the server refuse each in turn. `EntityForm`'s
 * layer 2 is what closes that, and the format panel prints the real pattern.
 *
 * ## A field cannot be cleared, and there is no control that pretends otherwise
 *
 * `admin.py · update_org_settings` applies `body.model_dump(exclude_none=True)`
 * over a blind `setattr` loop. An omitted field is left as it was, and **there
 * is no value that writes null**. So this screen sends only what changed and
 * offers no reset — a "clear" button that silently did nothing would be worse
 * than its absence (§5.4).
 *
 * ## What green means here, and what it cannot
 *
 * Item 10 goes `●` when a dial differs from its model default — **excluding the
 * three that `POST /orgs` seeds from the server's environment** (P11). Changing
 * one of those three here is a real choice, but the API cannot distinguish it
 * from the value org creation wrote, so it does not count towards the tick. The
 * banner says so, because otherwise editing the LLM budget and watching nothing
 * change reads as a bug.
 */
import { useMemo, useState } from "react";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { SettingsRead } from "../api/reads";
import { SETTINGS_DEFAULTS } from "../api/vocabularies.generated";
import type { ItemStatus } from "../checklist/status";
import { DESCRIPTORS } from "../descriptors";
import { EntityForm } from "../ui/EntityForm";
import {
  FormatFor,
  ItemHeading,
  ReadError,
  Section,
  asApiError,
  useList,
  useWrite,
} from "../ui/ItemScreen";
import { JsonField } from "../ui/JsonField";
import { Banner, DataTable, StatusMarker, styles as s } from "../ui/primitives";

const descriptor = DESCRIPTORS.settings;

/** P11/P12: written by `POST /orgs` from env, so a change here cannot be seen. */
const ENV_SEEDED = ["audio_retention_days", "transcript_retention_days", "llm_monthly_budget_usd"];

const JSON_EXAMPLES: Record<string, { example: unknown; keys: readonly string[]; note: string }> = {
  nudge_gap_days: {
    example: SETTINGS_DEFAULTS.nudge_gap_days,
    keys: Object.keys(SETTINGS_DEFAULTS.nudge_gap_days),
    note: "Days between the first, second and third nudge.",
  },
  reply_nudge_after_days: {
    example: SETTINGS_DEFAULTS.reply_nudge_after_days,
    keys: Object.keys(SETTINGS_DEFAULTS.reply_nudge_after_days),
    note: "How long silence waits before each follow-up, and before a call task is raised.",
  },
  payment_reminder_schedule: {
    example: SETTINGS_DEFAULTS.payment_reminder_schedule,
    keys: ["offset", "tone", "cc", "action"],
    note: "offset is days relative to the due date and may be negative; cc may name an influence level or a client-vocabulary stakeholder role.",
  },
  working_days: {
    example: SETTINGS_DEFAULTS.working_days,
    keys: [],
    note: "",
  },
};

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

export function Settings({ status }: { status: ItemStatus }) {
  const settings = useList("settings", endpoints.settings, SettingsRead);
  const [sent, setSent] = useState<string[] | null>(null);

  const save = useWrite<Record<string, unknown>>(["settings"], async (patch) => {
    const reply = await request(endpoints.settings, { as: "org", method: "PATCH", body: patch });
    setSent(Object.keys(patch));
    return reply;
  });

  const live = settings.data as unknown as Record<string, unknown> | undefined;

  const changed = useMemo(() => {
    if (!live) return [];
    return (Object.keys(SETTINGS_DEFAULTS) as Array<keyof typeof SETTINGS_DEFAULTS>).filter(
      (k) => !same(live[k], SETTINGS_DEFAULTS[k]),
    );
  }, [live]);

  if (settings.isError) {
    return (
      <>
        <ItemHeading item={10} marker={status.marker} caption={status.caption} />
        <Section title="Dials" eyebrow="Current">
          <ReadError error={settings.error} what="the organisation settings" />
        </Section>
      </>
    );
  }

  const chosen = changed.filter((k) => !ENV_SEEDED.includes(k));

  return (
    <>
      <ItemHeading item={10} marker={status.marker} caption={status.caption} />

      <Section title="What differs from the model default" eyebrow="Right now">
        {!live ? (
          <p className={s.muted} style={{ margin: 0 }}>Reading…</p>
        ) : (
          <>
            <DataTable
              columns={["", "Dial", "Now", "Model default"]}
              empty="Every dial is at its model default."
              rows={changed.map((k) => [
                <StatusMarker
                  key="m"
                  status={ENV_SEEDED.includes(k) ? "partial" : "done"}
                  label={ENV_SEEDED.includes(k) ? "seeded, not chosen" : "chosen"}
                />,
                <span key="k" className={s.mono}>
                  {k}
                </span>,
                <span key="n" className={s.mono} style={{ fontSize: "var(--text-xs)" }}>
                  {JSON.stringify(live[k])}
                </span>,
                <span key="d" className={s.mono} style={{ fontSize: "var(--text-xs)" }}>
                  {JSON.stringify(SETTINGS_DEFAULTS[k])}
                </span>,
              ])}
            />
            {changed.some((k) => ENV_SEEDED.includes(k)) && (
              <div style={{ marginBlockStart: "var(--s4)" }}>
                <Banner tone="note" title="Three of these do not count towards the tick">
                  <p style={{ margin: 0 }}>
                    <span className={s.mono}>{ENV_SEEDED.join(", ")}</span> are
                    written by <code>POST /orgs</code> from the server's own
                    environment, so a difference in them is not evidence that
                    anybody chose anything. Changing one here is a real choice —
                    the API just cannot tell it apart from the seeded value, and
                    this console does not pretend otherwise. {chosen.length === 0
                      ? "Change any other dial to turn item 10 green."
                      : `${chosen.length} other dial${chosen.length === 1 ? "" : "s"} differ, which is what turns item 10 green.`}
                  </p>
                </Banner>
              </div>
            )}
          </>
        )}
      </Section>

      <Section title="Change a dial" eyebrow="Edit">
        {sent && (
          <div style={{ marginBlockEnd: "var(--s4)" }}>
            <Banner tone="note" title="Saved">
              <p style={{ margin: 0 }}>
                {sent.length === 0
                  ? "Nothing had changed, so nothing was sent."
                  : `Sent: ${sent.join(", ")}. Everything else was left out of the body and is untouched.`}
              </p>
            </Banner>
          </div>
        )}

        {live && (
          <EntityForm
            descriptor={descriptor}
            submitLabel="Save changed dials"
            busy={save.isPending}
            serverError={asApiError(save.error)}
            initial={live}
            onSubmit={(body) => {
              // Only what differs from what was read. PATCH leaves an omitted
              // field alone, so sending everything would be harmless but would
              // write an audit row claiming 25 edits.
              const patch = Object.fromEntries(
                Object.entries(body).filter(([k, v]) => !same(v, live[k])),
              );
              setSent(Object.keys(patch));
              if (Object.keys(patch).length > 0) save.mutate(patch);
            }}
            slots={Object.fromEntries(
              Object.entries(JSON_EXAMPLES).map(([field, spec]) => [
                field,
                ({ value, onChange, id, invalid }: {
                  value: unknown;
                  onChange: (n: unknown) => void;
                  id: string;
                  invalid: boolean;
                }) => (
                  <JsonField
                    id={id}
                    value={value}
                    onChange={onChange}
                    invalid={invalid}
                    example={spec.example}
                    knownKeys={spec.keys}
                    keysNote={spec.note}
                  />
                ),
              ]),
            )}
          >
            <Banner tone="warn" title="A dial cannot be cleared">
              <p style={{ margin: 0 }}>
                <code>PATCH /admin/settings</code> applies with{" "}
                <code>exclude_none=True</code>, so an omitted field is left
                exactly as it was and <strong>no value writes null</strong>.
                There is deliberately no reset control here: one that silently
                did nothing would be worse than its absence.
              </p>
            </Banner>
          </EntityForm>
        )}
      </Section>

      <FormatFor descriptor={descriptor} />
    </>
  );
}
