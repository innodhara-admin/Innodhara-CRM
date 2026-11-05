/**
 * The validation an entity form runs before it posts — 07_BUILD_PLAN.md Task 17
 * Step 1.
 *
 * Deliberately a plain module and not part of `EntityForm.tsx`: this is where
 * the console decides what it will and will not send, which is the part worth
 * testing without a DOM (D11).
 *
 * ## Three layers, because one is not enough
 *
 * 1. **The generated schema** — `schemas[descriptor.writeSchema]`, straight from
 *    the backend's own OpenAPI. Types, required-ness, and the constraints the
 *    generator kept.
 * 2. **`CONSTRAINTS`** — the 16 console-relevant bounds the generator drops
 *    because FastAPI renders every optional field as an `anyOf` (P2). Without
 *    this layer the form silently permits values the server rejects: an
 *    `assignment_mode` of "nonsense", a `max_open_tasks` of 500.
 * 3. **The descriptor** — option lists from `VOCAB` (A4) and the cross-field
 *    rules OpenAPI has no way to say at all.
 *
 * **Every message names who enforces the rule**, in the same three-valued
 * vocabulary as the provenance line under the control (A2). A form that says
 * "invalid" without saying whose rule it is teaches the operator nothing about
 * whether the server would have accepted it.
 */
import { z } from "zod";

import { CONSTRAINTS } from "../api/constraints.generated";
import { schemas } from "../api/generated";
import type { Descriptor, Enforcement, FieldRule } from "../descriptors/types";

type Row = Record<string, unknown>;

/** Bounds as `constraints.generated.ts` writes them. */
type Bound = {
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  pattern?: string;
};

const CONSTRAINT_TABLE = CONSTRAINTS as Record<string, Record<string, Bound>>;

/**
 * Whose rule this is, in words, appended to every message.
 *
 * `ui-only` says so out loud. The operator is entitled to know that clearing
 * this message does not mean the server agrees — and, more usefully, that
 * ignoring it is not what will get the request refused.
 */
function attribution(enforcement: Enforcement | undefined): string {
  if (!enforcement) return "";
  if (enforcement.kind === "ui-only") return " (checked here only)";
  if (enforcement.kind === "backend-undeclared") return ` (${enforcement.source})`;
  return "";
}

/** The bounds this console knows for one field, from the lift. */
export function boundsFor(descriptor: Descriptor, field: string): Bound | undefined {
  return CONSTRAINT_TABLE[descriptor.writeSchema]?.[field];
}

function checkBound(
  value: unknown,
  bound: Bound,
  rule: FieldRule | undefined,
): string | null {
  const who = attribution(rule?.enforcement);
  if (typeof value === "string") {
    if (bound.minLength !== undefined && value.length < bound.minLength) {
      return `At least ${bound.minLength} characters${who}`;
    }
    if (bound.maxLength !== undefined && value.length > bound.maxLength) {
      return `At most ${bound.maxLength} characters — this is ${value.length}${who}`;
    }
    if (bound.pattern !== undefined && !new RegExp(bound.pattern).test(value)) {
      return `Must match ${bound.pattern}${who}`;
    }
  }
  if (typeof value === "number") {
    if (bound.minimum !== undefined && value < bound.minimum) {
      return `At least ${bound.minimum}${who}`;
    }
    if (bound.maximum !== undefined && value > bound.maximum) {
      return `At most ${bound.maximum}${who}`;
    }
  }
  return null;
}

/**
 * A value the operator has not supplied. Empty string is *not* the same as
 * `null` anywhere in this API — `PATCH /admin/settings` cannot write null at
 * all (§5.4), and `default_quantity`'s null carries meaning (§3.3) — so an
 * untouched text box is dropped from the body rather than sent as `""`.
 */
export function isBlank(value: unknown): boolean {
  return value === undefined || value === null || value === "";
}

/**
 * The body to send: blanks dropped, numbers coerced, nothing invented.
 *
 * Only fields the descriptor declares are carried, plus `writeOnly` directives
 * such as `make_current`. Everything the generator emits is `.passthrough()`
 * (P9), so an unknown key would sail through validation and be silently
 * ignored by the server — the form must not be the thing that introduces one.
 */
export function bodyFor(descriptor: Descriptor, values: Row): Row {
  const body: Row = {};
  for (const rule of descriptor.fields) {
    const value = values[rule.field];
    if (isBlank(value)) continue;
    body[rule.field] = value;
  }
  for (const directive of descriptor.writeOnly ?? []) {
    if (!isBlank(values[directive])) body[directive] = values[directive];
  }
  return body;
}

/**
 * Validate one row against all three layers.
 *
 * Returns field path → message. An empty object means the console has no
 * further objection — which is **not** the same as "the server will accept it",
 * and no caller may treat it that way: the domain rule on a staff email, the
 * uniqueness of a programme code and every conflict check live only on the
 * server, and their refusals are rendered verbatim when they arrive.
 */
export function validate(descriptor: Descriptor, values: Row): Record<string, string> {
  const errors: Record<string, string> = {};
  const body = bodyFor(descriptor, values);

  // Layer 1 — the generated schema.
  const schema = schemas[descriptor.writeSchema] as unknown as z.ZodType;
  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    for (const issue of parsed.error.issues) {
      const path = issue.path.join(".") || "(root)";
      if (!errors[path]) errors[path] = issue.message;
    }
  }

  // Layer 2 — the bounds the generator dropped (P2).
  const byField = new Map(descriptor.fields.map((f) => [f.field, f]));
  for (const [field, bound] of Object.entries(CONSTRAINT_TABLE[descriptor.writeSchema] ?? {})) {
    if (isBlank(body[field])) continue;
    const message = checkBound(body[field], bound, byField.get(field));
    if (message && !errors[field]) errors[field] = message;
  }

  // Layer 3a — option lists, always from VOCAB (A4).
  for (const rule of descriptor.fields) {
    // A suggestion list is not a closed set: `playbooks.phase` is accepted by
    // the server whatever it says, and refusing it here would be a rule this
    // console made up. The screen warns instead — see `optionsAreSuggestions`.
    if (rule.optionsAreSuggestions) continue;
    if (!rule.options || isBlank(body[rule.field])) continue;
    if (!rule.options.includes(String(body[rule.field]))) {
      errors[rule.field] ??=
        `Must be one of ${rule.options.join(", ")}${attribution(rule.enforcement)}`;
    }
  }

  // Layer 3b — the rules that span fields.
  for (const rule of descriptor.crossFieldRules ?? []) {
    const message = rule.check(body);
    if (message) errors[rule.field] ??= `${message}${attribution(rule.enforcement)}`;
  }

  return errors;
}

/** Blank values for a fresh form, one key per declared field. */
export function emptyRow(descriptor: Descriptor): Row {
  const row: Row = {};
  for (const rule of descriptor.fields) {
    row[rule.field] = rule.control === "checkbox" ? false : rule.control === "quantity" ? null : "";
  }
  return row;
}
