/**
 * Item 3 — a skill on every person's record. The manual calls it "the single
 * highest-value entry in this list", and the assignment engine agrees:
 * `action_items.required_skill` is matched against `user_skills.skill`
 * **exactly**, so a typo here is a task that routes to the phase lead forever.
 *
 * Three things this screen has to get right:
 *
 *  - **The skill name is free text, and stays free text (Q12).** The
 *    autocomplete offers what this organisation already holds — never a
 *    built-in taxonomy. A shipped list of skills would be a domain assumption
 *    in a product that has none, and `test_genericity.py` and
 *    `check_hardcoded_strings.py` exist precisely to stop that reappearing.
 *  - **`POST /skills` upserts** on `(user_id, skill)` and answers
 *    `{"updated": true}` when it overwrote a level rather than adding a row.
 *    Saying which happened is the difference between "I added Ravi's
 *    scheduling" and "I just changed it from expert to basic".
 *  - **`DELETE /skills` takes the natural key, not a row id**, because
 *    `GET /skills` returns no id — and it is guarded. When the guard fires its
 *    refusal is rendered word for word: it names the count, the skill and what
 *    to do, and no paraphrase of it would be an improvement.
 */
import { useMemo, useState } from "react";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { schemas } from "../api/generated";
import { SkillsRead } from "../api/reads";
import { VOCAB } from "../api/vocabularies.generated";
import { DESCRIPTORS } from "../descriptors";
import type { ItemStatus } from "../checklist/status";
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
import {
  Banner,
  Button,
  DataTable,
  Select,
  StatusMarker,
  TextInput,
  styles as s,
} from "../ui/primitives";

const StaffRead = schemas.UserResponse.array();
const descriptor = DESCRIPTORS.skills;

export function Skills({ status }: { status: ItemStatus }) {
  const staff = useList("staff", endpoints.staff, StaffRead);
  const skills = useList("skills", endpoints.skills, SkillsRead);
  const [outcome, setOutcome] = useState<string | null>(null);

  const active = (staff.data ?? []).filter((u) => u.is_active);
  const nameOf = useMemo(
    () => new Map((staff.data ?? []).map((u) => [u.id, u.name])),
    [staff.data],
  );

  /** Q12: the suggestion list is what this org already holds, and nothing else. */
  const known = useMemo(
    () => [...new Set((skills.data ?? []).map((row) => row.skill))].sort(),
    [skills.data],
  );

  const upsert = useWrite<Record<string, unknown>>(["skills"], async (body) => {
    const reply = (await request(endpoints.skills, {
      as: "org",
      method: "POST",
      body,
    })) as { updated: boolean };
    setOutcome(
      reply.updated
        ? `Updated the level on an existing ${String(body.skill)} row — POST /skills upserts on (person, skill), so nothing was duplicated.`
        : `Added ${String(body.skill)}.`,
    );
    return reply;
  });

  const remove = useWrite<{ user_id: string; skill: string }>(["skills"], (key) => {
    setOutcome(null);
    return request(endpoints.skills, {
      as: "org",
      method: "DELETE",
      query: key,
    });
  });

  const held = new Set((skills.data ?? []).map((row) => row.user_id));
  const uncovered = active.filter((u) => !held.has(u.id));

  return (
    <>
      <ItemHeading item={3} marker={status.marker} caption={status.caption} />

      <Section title="Give somebody a skill" eyebrow="Create or update">
        {outcome && (
          <div style={{ marginBlockEnd: "var(--s4)" }}>
            <Banner tone="note" title="Done">
              <p style={{ margin: 0 }}>{outcome}</p>
            </Banner>
          </div>
        )}
        <EntityForm
          descriptor={descriptor}
          submitLabel="Save skill"
          busy={upsert.isPending}
          serverError={asApiError(upsert.error)}
          onSubmit={(values) => upsert.mutate(values as Record<string, unknown>)}
          slots={{
            // Deactivated people are deliberately absent: `ops.py · delete_skill`
            // counts active holders only, so a skill on a deactivated account is
            // not coverage and offering to add one would be misleading.
            user_id: ({ value, onChange, id }) => (
              <Select
                id={id}
                placeholder="Choose a person"
                options={active.map((u) => ({ value: u.id, label: `${u.name} · ${u.role}` }))}
                value={String(value ?? "")}
                onChange={(e) => onChange(e.target.value)}
              />
            ),
            skill: ({ value, onChange, id, invalid }) => (
              <>
                <TextInput
                  id={id}
                  list="known-skills"
                  invalid={invalid}
                  value={String(value ?? "")}
                  onChange={(e) => onChange(e.target.value)}
                />
                <datalist id="known-skills">
                  {known.map((skill) => (
                    <option key={skill} value={skill} />
                  ))}
                </datalist>
              </>
            ),
          }}
        >
          <p className={s.muted} style={{ fontSize: "var(--text-xs)", margin: "var(--s2) 0 0" }}>
            The suggestions are the {known.length} skill name
            {known.length === 1 ? "" : "s"} this organisation already uses. There
            is no built-in list: a playbook entry's <code>required_skill</code>{" "}
            is matched against this string exactly, so what matters is that the
            two agree, not that either matches somebody else's taxonomy.
          </p>
        </EntityForm>
      </Section>

      <Section title="Who holds what" eyebrow="Current">
        {skills.isError ? (
          <ReadError error={skills.error} what="the skills list" />
        ) : (
          <DataTable
            columns={["Person", "Skill", "Level", ""]}
            empty="Nobody holds a skill — every task will route to the phase lead."
            rows={(skills.data ?? []).map((row) => [
              nameOf.get(row.user_id) ?? (
                <span key="u" className={s.mono}>
                  {row.user_id}
                </span>
              ),
              <span key="s" className={s.mono}>
                {row.skill}
              </span>,
              VOCAB.skill_level.includes(row.level as never) ? (
                row.level
              ) : (
                // ui-only means the server stored it: an unrecognised level is
                // real data, and the engine scores it as nothing.
                <span key="l" className={s.muted}>
                  {row.level} · not one of {VOCAB.skill_level.join(", ")}
                </span>
              ),
              <Button
                key="d"
                variant="danger"
                disabled={remove.isPending}
                onClick={() => remove.mutate({ user_id: row.user_id, skill: row.skill })}
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
              title="The skill could not be removed"
              serverMessage={asApiError(remove.error)?.detail ?? String(remove.error)}
            >
              <p style={{ margin: 0 }}>
                The server refused, and its message is shown exactly as it
                arrived. It counts <strong>active</strong> holders only, which is
                the same definition item 3 above uses.
              </p>
            </Banner>
          </div>
        )}
      </Section>

      {uncovered.length > 0 && (
        <Section title="Nobody has given these people a skill" eyebrow="Gap">
          <DataTable
            columns={["", "Name", "Role"]}
            rows={uncovered.map((u) => [
              <StatusMarker key="m" status="none" label="no skill" />,
              u.name,
              u.role,
            ])}
          />
          <p className={s.muted} style={{ fontSize: "var(--text-sm)", marginBlockStart: "var(--s4)" }}>
            The manual's own advice is to give everybody the neutral skill{" "}
            <code>general</code> plus their real specialisms. Until then, work
            needing a skill they would have matched routes to the phase lead
            flagged "no skill match", at low confidence.
          </p>
        </Section>
      )}

      <FormatFor descriptor={descriptor} />
    </>
  );
}
