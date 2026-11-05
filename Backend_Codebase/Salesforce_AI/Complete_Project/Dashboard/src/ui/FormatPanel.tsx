/**
 * The in-app spec — 06_DESIGN.md §3.4.
 *
 * Rendered **from the descriptor**, never from a second hand-written copy of
 * the field list. That is the whole point: the thing the operator reads to
 * learn what a field wants and the thing the form validates against are the
 * same declaration, so they cannot disagree.
 *
 * It states, per field: the label, whether it is required, what the rule is,
 * and — in the same three-valued vocabulary the provenance line uses — **who
 * enforces it**. A field checked here only is marked as such, because "the
 * console will not let me type that" and "the server will refuse it" are
 * different facts and only one of them survives a CSV import through some
 * other tool.
 */
import { schemas } from "../api/generated";
import type { Descriptor } from "../descriptors/types";
import { ENFORCEMENT_LABEL } from "./enforcement";
import { boundsFor } from "./entityValidation";
import { DataTable, Panel, Quote, styles as s } from "./primitives";

/** Which fields the generated write schema treats as required. */
function requiredFields(descriptor: Descriptor): Set<string> {
  const shape = (schemas[descriptor.writeSchema] as unknown as {
    shape?: Record<string, { isOptional?: () => boolean }>;
  }).shape;
  const required = new Set<string>();
  for (const [name, field] of Object.entries(shape ?? {})) {
    if (typeof field?.isOptional === "function" && !field.isOptional()) required.add(name);
  }
  return required;
}

/** The rule in words, drawn from the lift and the descriptor — never typed. */
function ruleText(descriptor: Descriptor, field: string, options?: readonly string[]): string {
  const parts: string[] = [];
  const bound = boundsFor(descriptor, field);
  if (bound?.minLength !== undefined) parts.push(`at least ${bound.minLength} characters`);
  if (bound?.maxLength !== undefined) parts.push(`at most ${bound.maxLength} characters`);
  if (bound?.minimum !== undefined) parts.push(`at least ${bound.minimum}`);
  if (bound?.maximum !== undefined) parts.push(`at most ${bound.maximum}`);
  if (bound?.pattern !== undefined) parts.push(`matches ${bound.pattern}`);
  if (options) parts.push(`one of ${options.join(", ")}`);
  return parts.join(" · ") || "—";
}

export function FormatPanel({ descriptor }: { descriptor: Descriptor }) {
  const required = requiredFields(descriptor);

  return (
    <Panel eyebrow="What this needs" title="The format">
      <Quote source={descriptor.manualRef}>{descriptor.quote}</Quote>

      <p style={{ maxInlineSize: "var(--measure)" }}>
        <strong>If you skip it: </strong>
        {descriptor.ifSkipped}
      </p>

      <DataTable
        columns={["Field", "", "Rule", "Enforced by"]}
        rows={descriptor.fields.map((rule) => [
          <span key="f" className={s.mono}>
            {rule.field}
          </span>,
          required.has(rule.field) ? "required" : <span className={s.muted}>optional</span>,
          <span key="r" className={s.mono} style={{ fontSize: "var(--text-xs)" }}>
            {ruleText(descriptor, rule.field, rule.options)}
          </span>,
          <span key="e" style={{ fontSize: "var(--text-xs)" }}>
            {ENFORCEMENT_LABEL[rule.enforcement.kind]}
            {rule.enforcement.kind === "backend-undeclared" && (
              <span className={s.muted}>{` · ${rule.enforcement.source}`}</span>
            )}
            {rule.enforcement.kind === "ui-only" && (
              <span className={s.muted}>{` · ${rule.enforcement.why}`}</span>
            )}
          </span>,
        ])}
      />

      {(descriptor.crossFieldRules ?? []).length > 0 && (
        <div style={{ marginBlockStart: "var(--s4)" }}>
          <p className={s.eyebrow}>Rules that span fields</p>
          <ul style={{ margin: "var(--s2) 0 0", paddingInlineStart: "1.1rem" }}>
            {descriptor.crossFieldRules?.map((rule) => (
              <li key={rule.says} style={{ fontSize: "var(--text-sm)" }}>
                <span className={s.mono}>{rule.field}</span>
                {` — ${rule.says}`}
                <span className={s.muted}>
                  {` · ${ENFORCEMENT_LABEL[rule.enforcement.kind]}`}
                  {rule.enforcement.kind === "backend-undeclared" && ` · ${rule.enforcement.source}`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className={s.muted} style={{ fontSize: "var(--text-sm)", marginBlockStart: "var(--s4)" }}>
        <strong>Re-importing the same file: </strong>
        {descriptor.reimport}
      </p>
    </Panel>
  );
}
