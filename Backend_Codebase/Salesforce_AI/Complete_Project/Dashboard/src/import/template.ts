/**
 * The downloadable template — 07_BUILD_PLAN.md Task 21 Step 4.
 *
 * Header plus one worked example, both straight from the descriptor, so the
 * file an operator downloads and the file the validator accepts cannot drift
 * apart. §3.4: the descriptor is the single declaration, and this is one of its
 * five consumers.
 *
 * ## CSV has one trap and the template walks into it on purpose
 *
 * `body_md` and a message `body` contain newlines. They survive CSV only under
 * correct quoting, and a hand-built file almost never quotes them — the row
 * splits, the columns shift, and the failure surfaces as an unrelated
 * validation error three fields away. So:
 *
 *  - the CSV example **ships with an embedded newline already quoted**, so the
 *    shape is visible rather than described;
 *  - `papaparse.unparse` does the quoting, rather than a hand-rolled join that
 *    would be right until the first field containing a comma;
 *  - and for the three entities whose bodies are prose, the format panel says
 *    plainly that JSON is the better choice.
 */
import Papa from "papaparse";

import type { Descriptor } from "../descriptors/types";
import type { Format } from "./parse";

/** Entities whose example carries a newline, so CSV is the harder road. */
export function csvIsAwkward(descriptor: Descriptor): boolean {
  return Object.values(descriptor.csv?.example ?? {}).some((v) => v.includes("\n"));
}

/**
 * The example row as JSON would carry it — numbers as numbers, JSON columns
 * parsed. The CSV example is all strings because CSV has no other type; the
 * JSON one should not pretend otherwise.
 */
function jsonExample(descriptor: Descriptor): Record<string, unknown> {
  // The three JSON-only entities carry their own worked example, because there
  // is no `csv.example` to derive one from. An earlier version invented one
  // from the field controls and produced a playbook with no programme and an
  // empty entry list — a template that failed its own validator. The
  // round-trip test caught it, and the fix is a real example rather than a
  // cleverer guess.
  if (!descriptor.csv) {
    if (!descriptor.jsonExample) {
      throw new Error(
        `${descriptor.key} is JSON-only and has no jsonExample — there is nothing to build a template from`,
      );
    }
    return descriptor.jsonExample;
  }
  const example = descriptor.csv.example;

  const byField = new Map(descriptor.fields.map((f) => [f.field, f]));

  // A CSV row of `pricing` is a rate-card LINE, not an entity, so its example
  // columns are line columns. The JSON template must still carry the entity
  // shape — `{items: [line]}` — or it describes a body no route accepts. Found
  // by the round-trip test, which is the third template it caught.
  const linesOf = descriptor.csv?.linesOf;
  if (linesOf) {
    const line: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(example)) {
      if (value === "") continue;
      line[key] = key === "unit_price" || key === "default_quantity" ? Number(value) : value;
    }
    return { [linesOf]: [line] };
  }

  const row: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(example)) {
    const control = byField.get(key)?.control;
    if (value === "") continue; // an omitted key, not an empty string (§3.3)
    if (control === "number" || control === "quantity" || key.endsWith("_price")) {
      row[key] = Number(value);
    } else if (control === "checkbox") {
      row[key] = value === "true";
    } else if (control === "json") {
      try {
        row[key] = JSON.parse(value);
      } catch {
        // The CSV example writes a list as `mon|tue|wed` — the convention both
        // list-bearing descriptors already use. JSON has real arrays, so the
        // JSON template must carry one; leaving the pipe string here produced a
        // template that failed its own validator, which the round-trip test
        // caught.
        row[key] = value.split("|").map((part) => part.trim()).filter(Boolean);
      }
    } else {
      row[key] = value;
    }
  }
  return row;
}

export function templateFor(descriptor: Descriptor, format: Format): string {
  if (format === "json") {
    const example = jsonExample(descriptor);
    // `settings` is one row, not a list (§5.5), so its template is an object.
    return JSON.stringify(descriptor.key === "settings" ? example : [example], null, 2) + "\n";
  }

  if (!descriptor.csv) {
    throw new Error(`${descriptor.key} has no CSV form — it is JSON only`);
  }

  const columns = [...descriptor.csv.columns];
  return (
    Papa.unparse(
      { fields: columns, data: [columns.map((c) => descriptor.csv!.example[c] ?? "")] },
      { newline: "\n" },
    ) + "\n"
  );
}

export function filenameFor(descriptor: Descriptor, format: Format): string {
  return `${descriptor.key}-template.${format}`;
}
