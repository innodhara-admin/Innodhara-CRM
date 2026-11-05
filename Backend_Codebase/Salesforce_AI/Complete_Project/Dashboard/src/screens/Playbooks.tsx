/**
 * Item 8 — standard task waves for each offering and phase.
 *
 * This screen exists because of backend change #3. Before it there was no
 * `GET /playbooks` at all: the console could write a playbook and never read
 * one back, which is why `02` still carries a 🔴 against this item.
 *
 * ## `phase` is `ui-only`, and it is the dangerous kind
 *
 * `ops.py · upsert_playbook` stores whatever string it is sent. A phase outside
 * `VOCAB.phase` produces a playbook that is written, listed, versioned — and
 * that **no plan will ever fire**, because the planner only ever asks for the
 * six it knows. Nothing anywhere reports that. So the select offers the six,
 * the free value is still allowed, and the caption says exactly what happens if
 * you use one.
 *
 * `program_id` has the same shape of hazard and is worse hidden: the handler
 * does not check that the programme exists. This screen therefore offers a
 * picker of real offerings rather than a text box.
 *
 * ## Versioning
 *
 * `POST /playbooks` supersedes the current row for that `(program_id, phase)`
 * and returns `{"id", "version"}` — one of the few writes that says what it
 * did. Delete promotes the predecessor and, like the catalogue deletes, says
 * only `{"deleted": true}`, so the screen re-reads.
 */
import { useState } from "react";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { PlaybooksRead, ProgramsRead } from "../api/reads";
import { VOCAB } from "../api/vocabularies.generated";
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
import {
  Banner,
  Button,
  DataTable,
  Select,
  StatusMarker,
  TextInput,
  styles as s,
} from "../ui/primitives";

const descriptor = DESCRIPTORS.playbooks;

/**
 * The entry shape, from `project.py`'s model comment and confirmed against the
 * 15 working entries in `seed_workflows.py`. Nothing validates any of it.
 */
const EXAMPLE = [
  {
    title: "Confirm site access",
    required_skill: "rack-and-stack",
    offset_days: -7,
    priority: "P1",
    visible_to_client: false,
  },
];

const ENTRY_KEYS = [
  "title",
  "required_skill",
  "offset_days",
  "priority",
  "visible_to_client",
] as const;

export function Playbooks({ status }: { status: ItemStatus }) {
  const programs = useList("programs", endpoints.programs, ProgramsRead);
  const playbooks = useList("playbooks", endpoints.playbooks, PlaybooksRead);
  const [outcome, setOutcome] = useState<string | null>(null);

  const active = (programs.data ?? []).filter((p) => p.is_active);
  const nameOf = new Map((programs.data ?? []).map((p) => [p.id, p.code]));

  const publish = useWrite<Record<string, unknown>>(["playbooks"], async (body) => {
    const reply = (await request(endpoints.playbooks, {
      as: "org",
      method: "POST",
      body,
    })) as { version: number };
    setOutcome(
      `Published v${reply.version} for ${nameOf.get(String(body.program_id)) ?? "that offering"} · ${String(body.phase)}.` +
        (reply.version > 1 ? " The previous version is superseded, not deleted." : ""),
    );
    return reply;
  });

  const remove = useWrite<{ id: string; version: number; program_id: string; phase: string }>(
    ["playbooks"],
    async (row) => {
      const reply = await request(endpoints.playbook(row.id), { as: "org", method: "DELETE" });
      const after = await request(endpoints.playbooks, { as: "org", shape: PlaybooksRead });
      const current = after.find(
        (p) => p.program_id === row.program_id && p.phase === row.phase && p.is_current,
      );
      setOutcome(
        current
          ? `v${row.version} is gone. v${current.version} is current again for ${nameOf.get(row.program_id) ?? row.program_id} · ${row.phase}.`
          : `v${row.version} is gone. ${nameOf.get(row.program_id) ?? row.program_id} · ${row.phase} now has no playbook — that phase will be derived from scratch by the AI.`,
      );
      return reply;
    },
  );

  if (active.length === 0) {
    return (
      <>
        <ItemHeading item={8} marker={status.marker} caption={status.caption} />
        <Section title="Nothing to write task waves for yet" eyebrow="Blocked">
          <Banner tone="note" title="Item 4 comes first">
            <p style={{ margin: 0 }}>A playbook hangs off an offering.</p>
          </Banner>
        </Section>
        <FormatFor descriptor={descriptor} />
      </>
    );
  }

  return (
    <>
      <ItemHeading item={8} marker={status.marker} caption={status.caption} />

      <Section title="Publish a wave" eyebrow="Create">
        {outcome && (
          <div style={{ marginBlockEnd: "var(--s4)" }}>
            <Banner tone="note" title="Done">
              <p style={{ margin: 0 }}>{outcome}</p>
            </Banner>
          </div>
        )}
        <EntityForm
          descriptor={descriptor}
          submitLabel="Publish new version"
          busy={publish.isPending}
          serverError={asApiError(publish.error)}
          initial={{ entries: EXAMPLE }}
          onSubmit={(body) => publish.mutate(body as Record<string, unknown>)}
          slots={{
            program_id: ({ value, onChange, id }) => (
              <Select
                id={id}
                placeholder="Choose an offering"
                options={active.map((p) => ({ value: p.id, label: `${p.code} — ${p.name}` }))}
                value={String(value ?? "")}
                onChange={(e) => onChange(e.target.value)}
              />
            ),
            // Free text with the six as suggestions, not a select: the server
            // takes any string, so this console refusing one would be a rule it
            // invented. The warning below is the honest alternative.
            phase: ({ value, onChange, id, invalid }) => (
              <>
                <TextInput
                  id={id}
                  list="known-phases"
                  invalid={invalid}
                  value={String(value ?? "")}
                  onChange={(e) => onChange(e.target.value)}
                />
                <datalist id="known-phases">
                  {VOCAB.phase.map((phase) => (
                    <option key={phase} value={phase} />
                  ))}
                </datalist>
                {String(value ?? "").trim() !== "" &&
                  !VOCAB.phase.includes(String(value) as never) && (
                    <p
                      className={s.mono}
                      style={{
                        fontSize: "var(--text-xs)",
                        color: "var(--status-blocked)",
                        margin: "var(--s2) 0 0",
                      }}
                    >
                      {`"${String(value)}" is not one of the six the planner asks for. The server will store this playbook and no plan will ever fire it.`}
                    </p>
                  )}
              </>
            ),
            entries: ({ value, onChange, id, invalid }) => (
              <JsonField
                id={id}
                value={value}
                onChange={onChange}
                invalid={invalid}
                example={EXAMPLE}
                knownKeys={ENTRY_KEYS}
                keysNote="offset_days is relative to the phase anchor and may be negative; required_skill must match a skill somebody actually holds, character for character."
              />
            ),
          }}
        >
          <Banner tone="warn" title="A phase outside the six is written and never fired">
            <p style={{ margin: 0 }}>
              The server accepts any string for the phase. The planner only ever
              asks for {VOCAB.phase.join(", ")}, so a playbook filed under
              anything else is stored, listed and versioned here and will
              silently never run. Nothing else in the system reports that.
            </p>
          </Banner>
        </EntityForm>
      </Section>

      <Section title="Waves you have" eyebrow="Current and superseded">
        {playbooks.isError ? (
          <ReadError error={playbooks.error} what="the playbook list" />
        ) : (
          <DataTable
            columns={["", "Offering", "Phase", "Entries", "Version", ""]}
            empty="No playbooks. Every phase is derived from scratch by the AI instead of following your known-good routine."
            rows={(playbooks.data ?? []).map((p) => [
              <StatusMarker
                key="m"
                status={p.is_current ? "done" : "none"}
                label={p.is_current ? "current" : "superseded"}
              />,
              <span key="pg" className={s.mono}>
                {nameOf.get(p.program_id) ?? p.program_id}
              </span>,
              VOCAB.phase.includes(p.phase as never) ? (
                <span key="ph" className={s.mono}>
                  {p.phase}
                </span>
              ) : (
                <span key="ph" className={s.mono} style={{ color: "var(--status-blocked)" }}>
                  {`${p.phase} · no plan will fire this`}
                </span>
              ),
              <span key="e" className={s.mono} style={{ fontSize: "var(--text-xs)" }}>
                {p.entries.length === 0
                  ? "none"
                  : p.entries
                      .map((entry) => String((entry as Record<string, unknown>).title ?? "?"))
                      .join(", ")}
              </span>,
              <span key="v" className={s.mono}>{`v${p.version}`}</span>,
              <Button
                key="d"
                variant="danger"
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate({
                    id: p.id,
                    version: p.version,
                    program_id: p.program_id,
                    phase: p.phase,
                  })
                }
              >
                Remove
              </Button>,
            ])}
          />
        )}
        {remove.error && (
          <div style={{ marginBlockStart: "var(--s4)" }}>
            <Banner
              tone="blocked"
              title="That playbook could not be removed"
              serverMessage={asApiError(remove.error)?.detail ?? String(remove.error)}
            />
          </div>
        )}
      </Section>

      <FormatFor descriptor={descriptor} />
    </>
  );
}
