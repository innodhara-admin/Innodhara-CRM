/**
 * Item 9 — approval rules. Two hazards on one screen, both said out loud.
 *
 * ## 1. There is no `PATCH`, so "edit" is delete-then-create
 *
 * Two calls, **not atomic**. A failure between them leaves the organisation
 * with *no* rule where it had one — silently changing who approves
 * client-facing messages, in the direction of "nobody". Retries are off (D17),
 * so the console will not quietly try again either.
 *
 * The edit control therefore states the risk before it runs, keeps the original
 * rule's values in a local variable so the recreate can be attempted again by
 * hand, and **re-reads the rule list afterwards** to confirm the replacement
 * actually landed (§5.4). Nothing here infers success from a 200 on the create
 * alone.
 *
 * Change #9 removed the *other* half of this problem: `fallback_role` and
 * `auto_approve` now read back, so a delete-then-create round trip preserves
 * the whole rule. Before it, editing any rule silently dropped both.
 *
 * ## 2. Rank decides which rule fires, and the first match wins
 *
 * Lower rank is checked first. Rules are grouped by `entity_type` and shown in
 * rank order, because a rule's meaning is entirely relative to what sits above
 * it — a catch-all at rank 10 makes every rule below it dead, and nothing in
 * the API will say so.
 *
 * An `entity_type` with **no** catch-all `{}` rule is flagged: a request
 * matching none of its rules has no approver at all, which is item 9's `◐`.
 */
import { useState } from "react";

import { request } from "../api/client";
import { endpoints } from "../api/endpoints";
import { ApprovalRulesRead, type ApprovalRules as Rules } from "../api/reads";
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
import { Banner, Button, DataTable, StatusMarker, styles as s } from "../ui/primitives";

const descriptor = DESCRIPTORS.approvalRules;

/**
 * The 13 keys observed across the 16 working rules in `seed_workflows.py`.
 * A suggestion list, not a schema: `condition` is a free `dict` and a typo is
 * stored, never matched, and never reported.
 */
const CONDITION_KEYS = [
  "discount_pct_gt",
  "amount_gt",
  "date_shift_days_gt",
  "tasks_added_gte",
  "urgent",
  "new_project",
  "scope_change",
  "delivery_dates_moved",
  "conflict_resolved",
  "resubmission",
  "kind",
  "channel",
  "sender_is_thread_owner",
] as const;

type Rule = Rules[number];

/** Rules of one entity type, in the order the engine checks them. */
function byEntityType(rules: Rules): Array<{ entityType: string; rules: Rules }> {
  const groups = new Map<string, Rule[]>();
  for (const rule of rules) {
    const list = groups.get(rule.entity_type) ?? [];
    list.push(rule);
    groups.set(rule.entity_type, list);
  }
  return [...groups.entries()]
    .map(([entityType, list]) => ({
      entityType,
      rules: [...list].sort((a, b) => a.rank - b.rank),
    }))
    .sort((a, b) => a.entityType.localeCompare(b.entityType));
}

const isCatchAll = (rule: Rule) => Object.keys(rule.condition ?? {}).length === 0;

export function ApprovalRules({ status }: { status: ItemStatus }) {
  const rules = useList("approvalRules", endpoints.approvalRules, ApprovalRulesRead);
  const [editing, setEditing] = useState<Rule | null>(null);
  const [replaceReport, setReplaceReport] = useState<string | null>(null);

  const create = useWrite<Record<string, unknown>>(["approvalRules"], (body) =>
    request(endpoints.approvalRules, { as: "org", method: "POST", body }),
  );

  const remove = useWrite<string>(["approvalRules"], (id) =>
    request(endpoints.approvalRule(id), { as: "org", method: "DELETE" }),
  );

  /**
   * Delete, then create. The window between them is the hazard, so the report
   * distinguishes the three outcomes rather than collapsing them into
   * "saved" / "failed".
   */
  const replace = useWrite<{ original: Rule; body: Record<string, unknown> }>(
    ["approvalRules"],
    async ({ original, body }) => {
      setReplaceReport(null);
      await request(endpoints.approvalRule(original.id), { as: "org", method: "DELETE" });
      try {
        await request(endpoints.approvalRules, { as: "org", method: "POST", body });
      } catch (cause) {
        setReplaceReport(
          `The old rule was deleted and the replacement was REFUSED. This ${original.entity_type} rule no longer exists. Create it again below before anything is submitted for approval.`,
        );
        throw cause;
      }
      // Not inferred from the 200: re-read and check the rule is really there.
      const after = await request(endpoints.approvalRules, {
        as: "org",
        shape: ApprovalRulesRead,
      });
      const landed = after.some(
        (r) => r.entity_type === body.entity_type && r.rank === body.rank,
      );
      setReplaceReport(
        landed
          ? `Replaced. The rule has a new id — re-read confirms one ${String(body.entity_type)} rule at rank ${String(body.rank)}.`
          : `The replacement returned success but does not appear in the rule list. Treat this organisation as having no such rule until you have looked.`,
      );
      setEditing(null);
      return after;
    },
  );

  const groups = byEntityType(rules.data ?? []);
  const uncovered = groups.filter((g) => !g.rules.some(isCatchAll));

  return (
    <>
      <ItemHeading item={9} marker={status.marker} caption={status.caption} />

      {uncovered.length > 0 && (
        <Section title="Some requests have no approver at all" eyebrow="Gap">
          <Banner tone="warn" title="No catch-all rule">
            <p style={{ margin: 0 }}>
              {uncovered.map((g) => g.entityType).join(", ")} — every rule for
              these carries a condition, so a request matching none of them
              matches nothing and is approved by nobody. A rule with an empty
              condition <code>{"{}"}</code> at a high rank is the catch-all;
              give it the highest number so it is checked last.
            </p>
          </Banner>
        </Section>
      )}

      <Section title={editing ? "Replace this rule" : "Add a rule"} eyebrow={editing ? "Edit" : "Create"}>
        {editing && (
          <div style={{ marginBlockEnd: "var(--s4)" }}>
            <Banner tone="warn" title="Editing means deleting and recreating">
              <p style={{ margin: "0 0 var(--s2)" }}>
                There is no route that edits an approval rule. Saving will{" "}
                <strong>delete</strong> the existing one and then{" "}
                <strong>create</strong> a replacement. Those are two calls and
                they are not atomic: if the second fails, this organisation is
                left with <strong>no {editing.entity_type} rule at rank{" "}
                {editing.rank}</strong> until you create one.
              </p>
              <p style={{ margin: 0 }}>
                The replacement gets a new id. Everything else is preserved —
                including the fallback approver and the auto-approve flag, which
                only became readable in backend change #9.
              </p>
            </Banner>
          </div>
        )}

        {replaceReport && (
          <div style={{ marginBlockEnd: "var(--s4)" }}>
            <Banner
              tone={replaceReport.startsWith("Replaced") ? "note" : "blocked"}
              title={replaceReport.startsWith("Replaced") ? "Replaced" : "The replacement did not land"}
            >
              <p style={{ margin: 0 }}>{replaceReport}</p>
            </Banner>
          </div>
        )}

        <EntityForm
          key={editing?.id ?? "new"}
          descriptor={descriptor}
          submitLabel={editing ? "Delete and recreate" : "Create rule"}
          busy={create.isPending || replace.isPending}
          serverError={asApiError(create.error) ?? asApiError(replace.error)}
          resetSignal={create.submittedAt}
          initial={editing ? (editing as unknown as Record<string, unknown>) : undefined}
          onSubmit={(body) =>
            editing
              ? replace.mutate({ original: editing, body: body as Record<string, unknown> })
              : create.mutate(body as Record<string, unknown>)
          }
          slots={{
            condition: ({ value, onChange, id, invalid }) => (
              <JsonField
                id={id}
                value={value}
                onChange={onChange}
                invalid={invalid}
                example={{ discount_pct_gt: 10 }}
                knownKeys={CONDITION_KEYS}
                keysNote="An empty object {} is the catch-all and matches everything."
              />
            ),
            joint_condition: ({ value, onChange, id, invalid }) => (
              <JsonField
                id={id}
                value={value}
                onChange={onChange}
                invalid={invalid}
                example={{ amount_gt: 500000 }}
                knownKeys={CONDITION_KEYS}
                keysNote="The joint approver is required only when this also matches."
              />
            ),
          }}
        >
          {editing && (
            <div style={{ marginBlockStart: "var(--s4)" }}>
              <Button variant="quiet" onClick={() => setEditing(null)}>
                Cancel and leave the existing rule alone
              </Button>
            </div>
          )}
        </EntityForm>
      </Section>

      {rules.isError ? (
        <Section title="Rules" eyebrow="Current">
          <ReadError error={rules.error} what="the approval rules" />
        </Section>
      ) : (
        groups.map((group) => (
          <Section
            key={group.entityType}
            title={group.entityType}
            eyebrow="Checked in this order — the first match decides"
          >
            <DataTable
              columns={["", "Rank", "Condition", "Approver", "Fallback", "Auto", "Expires", ""]}
              rows={group.rules.map((rule, index) => {
                // A catch-all above other rules makes everything below it dead:
                // the first match decides, and {} matches everything.
                const deadBelow = group.rules.slice(0, index).some(isCatchAll);
                return [
                  <StatusMarker
                    key="m"
                    status={deadBelow ? "blocked" : isCatchAll(rule) ? "done" : "none"}
                    label={
                      deadBelow
                        ? "never reached"
                        : isCatchAll(rule)
                          ? "catch-all"
                          : "conditional"
                    }
                  />,
                  <span key="r" className={s.mono}>
                    {rule.rank}
                    {deadBelow && (
                      <span style={{ color: "var(--status-blocked)" }}>
                        {" · never reached"}
                      </span>
                    )}
                  </span>,
                  <span key="c" className={s.mono} style={{ fontSize: "var(--text-xs)" }}>
                    {isCatchAll(rule) ? "{} — everything" : JSON.stringify(rule.condition)}
                  </span>,
                  rule.approver_role,
                  rule.fallback_role ?? <span key="f" className={s.muted}>none</span>,
                  rule.auto_approve ? "yes" : <span key="a" className={s.muted}>no</span>,
                  <span key="e" className={s.mono}>{`${rule.expires_hours}h`}</span>,
                  <span key="x" style={{ display: "flex", gap: "var(--s2)" }}>
                    <Button onClick={() => setEditing(rule)}>Edit</Button>
                    <Button
                      variant="danger"
                      disabled={remove.isPending}
                      onClick={() => remove.mutate(rule.id)}
                    >
                      Remove
                    </Button>
                  </span>,
                ];
              })}
            />
          </Section>
        ))
      )}

      {(rules.data ?? []).length === 0 && !rules.isError && (
        <Section title="No rules" eyebrow="Current">
          <p className={s.muted} style={{ margin: 0 }}>
            Everything falls to one default approver, and nothing is escalated by
            value or risk.
          </p>
        </Section>
      )}

      {remove.error && (
        <Section title="That rule could not be removed" eyebrow="Refused">
          <Banner
            tone="blocked"
            title="The server refused"
            serverMessage={asApiError(remove.error)?.detail ?? String(remove.error)}
          />
        </Section>
      )}

      <FormatFor descriptor={descriptor} />
    </>
  );
}
