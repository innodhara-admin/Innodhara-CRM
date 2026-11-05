/**
 * Validating an import file — 07_BUILD_PLAN.md Task 21 Step 2 (A7 / P9).
 *
 * ## The order is the whole finding
 *
 * **Column set first, then coerce, then Zod.** Not because it reads better —
 * because the other order does not work at all. Every schema the generator
 * emits is `z.object({…}).passthrough()` (P9), so an unknown key **passes**
 * validation. A CSV whose header says `unit_pirce` would parse clean, validate
 * clean, and write a rate-card line with no price, and the first anyone hears
 * of it is a proposal quoting nothing.
 *
 * `.strict()` on the generated schemas is not the fix: they are regenerated
 * from the backend on every `npm run gen:api`, and a field the backend *adds*
 * must not break a running console (`reads.ts` makes the same choice in the
 * other direction). So the column check lives here, against the descriptor,
 * where it is this console's rule and is written down as one.
 *
 * ## Empty is not zero and not null
 *
 * CSV gives strings, and every absent cell arrives as `""`. Coercing that to
 * `0` would collapse `default_quantity` into exactly the pre-filled `1` the
 * tri-state exists to prevent (§3.3) — and `0` and "not stated" are different
 * facts about a rate card. An empty cell means **the column was left blank**,
 * so the key is dropped from the body and the server applies its own default.
 * Three distinct outcomes, and the tests pin all three:
 *
 * | Cell | Body |
 * |---|---|
 * | `""` | key absent |
 * | `"0"` | `0` |
 * | `"1"` | `1` |
 */
import { z } from "zod";

import { schemas } from "../api/generated";
import type { Descriptor, FieldRule } from "../descriptors/types";
import { bodyFor, validate as validateRow } from "../ui/entityValidation";
import type { Row } from "./parse";

export type RowVerdict = {
  /** 1-based, as the operator counts rows — header excluded. */
  line: number;
  /** Column or field → message. Empty means this row is ready to send. */
  errors: Record<string, string>;
  /** What would go on the wire. Task 22 sends exactly this. */
  body: Row;
  /**
   * The row exactly as the parser produced it — original columns, original
   * strings, `_` columns already removed.
   *
   * Kept alongside `body` rather than derived from it, because the failures
   * file has to re-emit **what the operator wrote**, not what this console
   * coerced it into. A rate-card line whose `default_quantity` was blank must
   * come back blank, not absent; a `working_days` of `mon|tue` must come back
   * as `mon|tue`, not as `["mon","tue"]`. Round-tripping the body would quietly
   * rewrite the operator's file every time they fixed one row in it.
   */
  source: Row;
  ok: boolean;
};

export type FileVerdict = {
  /**
   * `row-per-call` — the normal case, one HTTP write per row.
   * `file-is-one-call` — a `pricing` CSV, whose rows are rate-card *lines* and
   * whose whole file is one versioned card.
   */
  shape: "row-per-call" | "file-is-one-call";
  rows: RowVerdict[];
  /** Only set for `file-is-one-call`: the single body the file amounts to. */
  grouped?: Row;
  okCount: number;
  errorCount: number;
  /** §5.5: apply is gated on **zero** validation errors, not on "mostly fine". */
  canApply: boolean;
};

/** Everything the descriptor will accept as a column, in template order. */
export function expectedColumns(descriptor: Descriptor, lineLevel: boolean): string[] {
  if (lineLevel && descriptor.csv) return [...descriptor.csv.columns];
  return [...descriptor.fields.map((f) => f.field), ...(descriptor.writeOnly ?? [])];
}

const BLANK = (value: unknown) =>
  value === undefined || value === null || (typeof value === "string" && value.trim() === "");

/**
 * A CSV cell holding a list — `mon|tue|wed`, `<id>|<id>`.
 *
 * **Not invented here.** Both descriptors that expose a list field to CSV,
 * `staff.working_days` and `demoTeams.member_ids`, already ship a
 * pipe-delimited example, so the convention was the project's before this
 * module existed; it simply had nowhere to be implemented until now. It was
 * found by the round-trip test — the staff template failed its own validator,
 * because `JSON.parse("mon|tue|wed|thu|fri")` is not JSON.
 *
 * JSON is still accepted for the same cell. A value that *looks* like JSON —
 * it opens with `[` or `{` — and does not parse is a genuine error rather than
 * a one-element list, or a typo'd array would import as a single nonsense
 * string.
 */
function csvList(text: string): { value: unknown } | { error: string } {
  if (text.startsWith("[") || text.startsWith("{")) {
    try {
      return { value: JSON.parse(text) };
    } catch (cause) {
      return { error: `not valid JSON — ${cause instanceof Error ? cause.message : cause}` };
    }
  }
  return { value: text.split("|").map((part) => part.trim()).filter((part) => part !== "") };
}

/**
 * One cell → one value, by the control the descriptor declares.
 *
 * Returns `{ absent: true }` for a blank cell rather than a value, because
 * "not supplied" has to survive all the way to `bodyFor`, which drops the key.
 */
function coerce(
  control: FieldRule["control"] | "auto",
  raw: unknown,
  format: "csv" | "json" = "json",
): { absent: true } | { value: unknown } | { error: string } {
  if (BLANK(raw)) return { absent: true };
  if (typeof raw !== "string") return { value: raw };
  const text = raw.trim();

  // A JSON file already carries real types; only a CSV cell needs the list
  // convention, because CSV has no way to say "array".
  if (control === "json" && format === "csv") return csvList(text);

  switch (control) {
    case "number":
    case "quantity": {
      const n = Number(text);
      if (!Number.isFinite(n)) return { error: `"${text}" is not a number` };
      return { value: n };
    }
    case "checkbox": {
      const truthy = ["true", "yes", "1"];
      const falsy = ["false", "no", "0"];
      const lower = text.toLowerCase();
      if (truthy.includes(lower)) return { value: true };
      if (falsy.includes(lower)) return { value: false };
      return { error: `"${text}" is not true or false` };
    }
    case "json": {
      try {
        return { value: JSON.parse(text) };
      } catch (cause) {
        return {
          error: `not valid JSON — ${cause instanceof Error ? cause.message : cause}`,
        };
      }
    }
    default:
      return { value: text };
  }
}

/** The controls a rate-card line's columns use, since they are not fields. */
const LINE_CONTROLS: Record<string, FieldRule["control"] | "auto"> = {
  unit_price: "number",
  default_quantity: "quantity",
};

function checkColumns(
  row: Row,
  expected: string[],
  errors: Record<string, string>,
): void {
  // A7, and it runs FIRST. Everything the generator emits is .passthrough(),
  // so an unknown key would otherwise validate clean and be dropped in silence.
  for (const column of Object.keys(row)) {
    if (expected.includes(column)) continue;
    errors[column] =
      `Unknown column "${column}". This entity takes: ${expected.join(", ")}. ` +
      `Nothing here would reject it — the generated schemas accept unknown keys — ` +
      `so it would be sent, ignored, and the field you meant left empty.`;
  }
}

/** A rate-card line, validated against the generated `PricingItem` schema. */
function verdictForLine(descriptor: Descriptor, row: Row, line: number): RowVerdict {
  const errors: Record<string, string> = {};
  checkColumns(row, expectedColumns(descriptor, true), errors);

  const body: Row = {};
  for (const column of descriptor.csv?.columns ?? []) {
    const outcome = coerce(LINE_CONTROLS[column] ?? "auto", row[column], "csv");
    if ("error" in outcome) errors[column] = outcome.error;
    else if ("value" in outcome) body[column] = outcome.value;
    // absent: the key is not written, so "" stays "not supplied" (§3.3).
  }

  if (Object.keys(errors).length === 0) {
    const parsed = (schemas.PricingItem as unknown as z.ZodType).safeParse(body);
    if (!parsed.success) {
      for (const issue of parsed.error.issues) {
        const path = issue.path.join(".") || "(row)";
        errors[path] ??= issue.message;
      }
    }
  }

  return { line, errors, body, source: row, ok: Object.keys(errors).length === 0 };
}

function verdictForRow(
  descriptor: Descriptor,
  row: Row,
  line: number,
  format: "csv" | "json",
): RowVerdict {
  const errors: Record<string, string> = {};
  checkColumns(row, expectedColumns(descriptor, false), errors);

  // Coerce every declared field, then let the shared three-layer validator do
  // the rest — the same function the interactive forms use, so a file and a
  // form cannot disagree about what the server will take.
  const coerced: Row = {};
  const byField = new Map(descriptor.fields.map((f) => [f.field, f]));
  for (const [column, raw] of Object.entries(row)) {
    const rule = byField.get(column);
    const outcome = coerce(rule?.control ?? "auto", raw, format);
    if ("error" in outcome) errors[column] = outcome.error;
    else if ("value" in outcome) coerced[column] = outcome.value;
  }

  if (Object.keys(errors).length === 0) {
    Object.assign(errors, validateRow(descriptor, coerced));
  }

  return {
    line,
    errors,
    body: bodyFor(descriptor, coerced),
    source: row,
    ok: Object.keys(errors).length === 0,
  };
}

/**
 * What the console already knows about the organisation being imported into.
 *
 * Only one thing today, and it is a refusal rather than a warning: a
 * proposal-template import that would supersede a current **Word-document**
 * template replaces a branded document with a text one, silently, on the way
 * to a client. That is the exact failure the docx path exists to remove, so it
 * blocks the apply instead of colouring a row amber.
 */
export type ImportContext = {
  /** True when the current proposal template for the target is `kind: "docx"`. */
  supersedesDocxTemplate?: boolean;
};

export const DOCX_SUPERSEDE_ERROR =
  "The current template for this offering is a Word document. Importing this " +
  "row would replace it with a plain text one and the branding would be lost. " +
  "Upload a .docx instead, or remove that template first.";

export function validateFile(
  descriptor: Descriptor,
  rows: Row[],
  format: "csv" | "json",
  context: ImportContext = {},
): FileVerdict {
  // Only a CSV of `pricing` is line-level: a JSON file for the same entity
  // carries the entity shape, `{currency, items: [...]}`, and goes down the
  // ordinary path.
  const lineLevel = format === "csv" && Boolean(descriptor.csv?.linesOf);

  const verdicts = rows.map((row, i) =>
    lineLevel
      ? verdictForLine(descriptor, row, i + 1)
      : verdictForRow(descriptor, row, i + 1, format),
  );

  if (descriptor.key === "proposalTemplates" && context.supersedesDocxTemplate) {
    for (const verdict of verdicts) {
      verdict.errors = { ...verdict.errors, name: DOCX_SUPERSEDE_ERROR };
      verdict.ok = false;
    }
  }

  const okCount = verdicts.filter((v) => v.ok).length;
  const errorCount = verdicts.length - okCount;
  const base = {
    rows: verdicts,
    okCount,
    errorCount,
    // Zero errors, not "most of them". The backend has no bulk transaction, so
    // a file applied with known-bad rows leaves a half-written catalogue.
    canApply: errorCount === 0 && verdicts.length > 0,
  };

  if (!lineLevel) return { shape: "row-per-call", ...base };

  return {
    shape: "file-is-one-call",
    ...base,
    grouped: {
      // Currency is not a per-line column; the rate card takes the server's
      // default unless the screen offers one.
      [descriptor.csv!.linesOf!]: verdicts.map((v) => v.body),
    },
  };
}
