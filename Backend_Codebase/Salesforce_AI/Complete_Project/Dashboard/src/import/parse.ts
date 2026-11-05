/**
 * Reading an import file — 07_BUILD_PLAN.md Task 21 Step 1.
 *
 * Parsing only. **Nothing here validates anything**, and that separation is the
 * point: `validate.ts` needs to know which columns the file actually carried,
 * including ones the descriptor has never heard of, and a parser that quietly
 * dropped those would make the unknown-column check (A7) impossible to write.
 *
 * ## `_`-prefixed columns are dropped, and that is what closes the loop
 *
 * D21: a failed row comes back as a file in its own format with the original
 * columns plus an appended `_error` carrying the server's message. Because the
 * parser ignores any column beginning with `_`, the operator fixes the rows in
 * place and drops **the same file** back in — no editing headers, no rebuilding
 * anything by hand. They are reported in `ignored` rather than silently
 * discarded, so the preview can say the file was recognised as a failures file.
 *
 * ## Which formats an entity accepts comes from its descriptor
 *
 * `descriptor.csv === null` means JSON only, and three entities are: playbooks
 * (a `list[dict]` per row), approval rules (two free dicts per row) and settings
 * (one row, not a list). This module reads that flag; it carries no list of its
 * own, which is the difference between one source of truth and two.
 */
import Papa from "papaparse";

import type { Descriptor } from "../descriptors/types";

export type Format = "csv" | "json";
export type Row = Record<string, unknown>;

export type ParseResult = {
  format: Format;
  /** Column names the file carried, `_` ones removed, in file order. */
  columns: string[];
  /** Columns dropped because they begin with `_` (D21). */
  ignored: string[];
  rows: Row[];
  /**
   * The file could not be read at all — bad JSON, an unparseable CSV, or a
   * format this entity does not accept. When set, `rows` is empty and nothing
   * downstream should run.
   */
  fatal: string | null;
};

const empty = (format: Format, fatal: string): ParseResult => ({
  format,
  columns: [],
  ignored: [],
  rows: [],
  fatal,
});

/** Which formats this entity accepts, from the descriptor alone. */
export function formatsFor(descriptor: Descriptor): Format[] {
  return descriptor.csv ? ["csv", "json"] : ["json"];
}

export function detectFormat(filename: string): Format {
  return filename.trim().toLowerCase().endsWith(".csv") ? "csv" : "json";
}

const isIgnored = (column: string) => column.startsWith("_");

/** Strip `_` columns from one row, keeping everything else exactly as it was. */
function stripIgnored(row: Row): Row {
  const kept: Row = {};
  for (const [key, value] of Object.entries(row)) {
    if (!isIgnored(key)) kept[key] = value;
  }
  return kept;
}

/** Union of keys across rows, in first-seen order. JSON has no header line. */
function columnsOf(rows: Row[]): string[] {
  const seen: string[] = [];
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (!seen.includes(key)) seen.push(key);
    }
  }
  return seen;
}

function parseJson(descriptor: Descriptor, text: string): ParseResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (cause) {
    return empty("json", `Not valid JSON — ${cause instanceof Error ? cause.message : cause}`);
  }

  // `settings` is one row rather than a list (§5.5). A bare object is the
  // natural shape for it and the wrong shape for everything else, so the
  // distinction is enforced here rather than left to produce a confusing
  // per-field error later.
  const isSingle = descriptor.key === "settings";
  let list: unknown[];
  if (Array.isArray(parsed)) {
    if (isSingle && parsed.length !== 1) {
      return empty(
        "json",
        `Settings is one row, not a list — this file holds ${parsed.length}. Send a single JSON object, or an array with exactly one.`,
      );
    }
    list = parsed;
  } else if (parsed && typeof parsed === "object") {
    list = [parsed];
  } else {
    return empty("json", "Expected a JSON array of rows, or a single object.");
  }

  if (list.some((row) => row === null || typeof row !== "object" || Array.isArray(row))) {
    return empty("json", "Every entry must be a JSON object.");
  }

  const raw = list as Row[];
  const ignored = columnsOf(raw).filter(isIgnored);
  const rows = raw.map(stripIgnored);
  return { format: "json", columns: columnsOf(rows), ignored, rows, fatal: null };
}

function parseCsv(descriptor: Descriptor, text: string): ParseResult {
  if (!descriptor.csv) {
    return empty(
      "csv",
      `${descriptor.title} cannot be imported as CSV — ${descriptor.key === "settings" ? "it is one row, not a list" : "its fields carry nested JSON that CSV cannot express"}. Use JSON.`,
    );
  }

  const result = Papa.parse<Row>(text.trim(), {
    header: true,
    skipEmptyLines: "greedy",
    // No dynamic typing: papaparse would turn "0" into 0 and "" into null, and
    // the tri-state (§3.3) needs those three to stay distinct until `validate.ts`
    // decides what each one means for the field it landed in.
    dynamicTyping: false,
    transformHeader: (h) => h.trim(),
  });

  // Papaparse reports quoting problems as errors and still returns rows. A
  // malformed quote is exactly the failure the format panel warns about for
  // template bodies, so it is fatal rather than a partial read.
  const structural = result.errors.filter((e) => e.type === "Quotes" || e.code === "TooManyFields" || e.code === "TooFewFields");
  if (structural.length > 0) {
    const first = structural[0];
    return empty(
      "csv",
      `The CSV could not be read${first.row === undefined ? "" : ` at row ${first.row + 1}`} — ${first.message}. Fields containing commas or line breaks must be wrapped in double quotes.`,
    );
  }

  const fields = (result.meta.fields ?? []).map((f) => f.trim());
  const ignored = fields.filter(isIgnored);
  const rows = result.data.map(stripIgnored);
  return {
    format: "csv",
    columns: fields.filter((f) => !isIgnored(f)),
    ignored,
    rows,
    fatal: null,
  };
}

export function parseFile(
  descriptor: Descriptor,
  text: string,
  format: Format,
): ParseResult {
  if (text.trim() === "") return empty(format, "The file is empty.");
  return format === "csv" ? parseCsv(descriptor, text) : parseJson(descriptor, text);
}
