/**
 * The failures file — 07_BUILD_PLAN.md Task 22 Step 3, D21.
 *
 * The loop this closes: **import → fix the failures → re-import the failures
 * file → repeat until it comes back empty.** For that to work the emitted file
 * has to be a file the parser accepts without any editing at all, so:
 *
 *  - **the input's own format** — CSV in, CSV out; JSON in, JSON out. An
 *    operator who built a CSV should not be handed JSON to repair;
 *  - **the original columns, in the original order**, taken from what the file
 *    actually carried rather than from the descriptor's canonical order — a
 *    file that omitted three optional columns gets them back omitted;
 *  - **the original values, byte for byte**. The *source* row is re-emitted,
 *    never the coerced body: a blank `default_quantity` comes back blank rather
 *    than absent, and `mon|tue` comes back as `mon|tue` rather than as a JSON
 *    array. Round-tripping the body would quietly rewrite the operator's file
 *    each time they fixed one row of it;
 *  - **plus `_error`**, carrying the server's message verbatim. The parser
 *    drops every `_`-prefixed column, which is what makes the file re-importable
 *    without touching the header.
 *
 * `_error` is appended rather than prepended so the operator's own columns stay
 * where their eye expects them, and a spreadsheet opens with the familiar shape
 * and one extra column at the far right.
 */
import Papa from "papaparse";

import type { Descriptor } from "../descriptors/types";
import type { RowOutcome } from "./apply";
import type { Format } from "./parse";

/** The column the parser ignores, and the reason the loop closes. */
export const ERROR_COLUMN = "_error";

export type FailuresFile = {
  text: string;
  filename: string;
  rows: number;
} | null;

/**
 * Build the file, or `null` when nothing failed — the caller should offer no
 * download at all in that case rather than an empty file with a header, which
 * reads as "here is your problem" when there is none.
 */
export function failuresFile(opts: {
  descriptor: Descriptor;
  format: Format;
  /** Columns the input carried, `_` ones already removed, in file order. */
  columns: readonly string[];
  outcomes: readonly RowOutcome[];
}): FailuresFile {
  const { descriptor, format, columns, outcomes } = opts;
  const failed = outcomes.filter((o) => o.status === "refused");
  if (failed.length === 0) return null;

  const filename = `${descriptor.key}-failures.${format}`;

  if (format === "json") {
    const rows = failed.map((o) => ({ ...o.source, [ERROR_COLUMN]: o.message }));
    return { text: JSON.stringify(rows, null, 2) + "\n", filename, rows: failed.length };
  }

  // Papa.unparse does the quoting. A server message can contain a comma, a
  // quote or a newline — "3 open task(s) need 'x' and nobody else holds it." —
  // and a hand-rolled join would be right until the first one that does.
  const fields = [...columns, ERROR_COLUMN];
  const data = failed.map((o) => [
    ...columns.map((c) => o.source[c] ?? ""),
    o.message,
  ]);
  return {
    text: Papa.unparse({ fields, data }, { newline: "\n" }) + "\n",
    filename,
    rows: failed.length,
  };
}
