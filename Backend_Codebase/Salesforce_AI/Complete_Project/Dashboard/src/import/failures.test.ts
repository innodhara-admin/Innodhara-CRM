/**
 * The failures file — Task 22 Steps 3–4.
 *
 * The claim being tested is the whole of D21: **the emitted file goes straight
 * back into the parser and yields exactly the failed rows, unchanged.** Not
 * "roughly the same fields" — byte-identical values, embedded newlines
 * included, because the operator edits that file in place and re-imports it.
 */
import { describe, expect, it } from "vitest";

import { DESCRIPTORS } from "../descriptors";
import type { RowOutcome } from "./apply";
import { ERROR_COLUMN, failuresFile } from "./failures";
import { parseFile } from "./parse";
import { validateFile } from "./validate";

const outcome = (
  line: number,
  status: RowOutcome["status"],
  source: Record<string, unknown>,
  message: string,
): RowOutcome => ({ line, status, source, message });

describe("what the file contains", () => {
  it("is null when nothing failed", () => {
    // Not an empty file with a header: offering a download called
    // "failures.csv" after a clean run reads as "here is your problem".
    expect(
      failuresFile({
        descriptor: DESCRIPTORS.vendors,
        format: "csv",
        columns: ["name"],
        outcomes: [outcome(1, "applied", { name: "A" }, "applied")],
      }),
    ).toBeNull();
  });

  it("holds only the failed rows", () => {
    const file = failuresFile({
      descriptor: DESCRIPTORS.vendors,
      format: "csv",
      columns: ["name", "category"],
      outcomes: [
        outcome(1, "applied", { name: "A", category: "x" }, "applied"),
        outcome(2, "refused", { name: "B", category: "y" }, "already exists"),
        outcome(3, "applied", { name: "C", category: "z" }, "applied"),
      ],
    });
    expect(file?.rows).toBe(1);
    expect(file?.text).toContain("B,y,already exists");
    expect(file?.text).not.toContain("name,x");
  });

  it("keeps the input's own columns and order, not the descriptor's", () => {
    // A file that omitted the optional columns gets them back omitted.
    const file = failuresFile({
      descriptor: DESCRIPTORS.vendors,
      format: "csv",
      columns: ["category", "name"],
      outcomes: [outcome(1, "refused", { category: "transport", name: "B" }, "no")],
    });
    expect(file?.text.split("\n")[0]).toBe(`category,name,${ERROR_COLUMN}`);
  });

  it("comes back in the input's own format", () => {
    const asJson = failuresFile({
      descriptor: DESCRIPTORS.vendors,
      format: "json",
      columns: ["name"],
      outcomes: [outcome(1, "refused", { name: "B" }, "already exists")],
    });
    expect(asJson?.filename).toBe("vendors-failures.json");
    expect(JSON.parse(asJson!.text)).toEqual([{ name: "B", [ERROR_COLUMN]: "already exists" }]);
  });

  it("quotes a server message that itself contains a comma and a quote", () => {
    // The skill-delete guard's real refusal. A hand-rolled join would split the
    // row here and the failures file would be unreadable.
    const message = `3 open task(s) need 'rack-and-stack' and nobody else holds it. Give the skill to someone else first, or close that work.`;
    const file = failuresFile({
      descriptor: DESCRIPTORS.vendors,
      format: "csv",
      columns: ["name"],
      outcomes: [outcome(1, "refused", { name: "B" }, message)],
    });
    const reparsed = parseFile(DESCRIPTORS.vendors, file!.text, "csv");
    expect(reparsed.fatal).toBeNull();
    expect(reparsed.rows).toHaveLength(1);
  });
});

describe("the round trip — import, fix, re-import", () => {
  it("re-parses to exactly the failed rows, with `_error` ignored", () => {
    const input =
      "name,contact_name,category\n" +
      "Northgate,Asha Rao,transport\n" +
      "Ashcroft,Ravi Menon,plant\n" +
      "Dorset,Priya Nair,transport\n";
    const parsed = parseFile(DESCRIPTORS.vendors, input, "csv");

    // Rows 2 and 3 refused, 1 applied.
    const outcomes: RowOutcome[] = parsed.rows.map((row, i) =>
      outcome(i + 1, i === 0 ? "applied" : "refused", row, i === 0 ? "applied" : "already exists"),
    );

    const file = failuresFile({
      descriptor: DESCRIPTORS.vendors,
      format: "csv",
      columns: parsed.columns,
      outcomes,
    })!;

    const again = parseFile(DESCRIPTORS.vendors, file.text, "csv");
    expect(again.fatal).toBeNull();
    expect(again.ignored).toEqual([ERROR_COLUMN]);
    // Exactly the failed rows, and exactly the values that went in.
    expect(again.rows).toEqual([parsed.rows[1], parsed.rows[2]]);
    // And it validates, so it is ready to send the moment it is fixed.
    expect(validateFile(DESCRIPTORS.vendors, again.rows, "csv").canApply).toBe(true);
  });

  it("survives an embedded newline in a template body", () => {
    // The CSV trap, now on the way OUT as well as in. A body_md that split
    // across rows here would corrupt the operator's file the first time a
    // template import failed.
    const body = "## Scope\n\nCommissioning and handover for {client_name}.\n";
    const input = Papaish("name,body_md", [["Standard commissioning", body]]);
    const parsed = parseFile(DESCRIPTORS.proposalTemplates, input, "csv");
    expect(parsed.rows[0].body_md).toBe(body);

    const file = failuresFile({
      descriptor: DESCRIPTORS.proposalTemplates,
      format: "csv",
      columns: parsed.columns,
      outcomes: [outcome(1, "refused", parsed.rows[0], "Program not found")],
    })!;

    const again = parseFile(DESCRIPTORS.proposalTemplates, file.text, "csv");
    expect(again.rows).toHaveLength(1);
    expect(again.rows[0].body_md).toBe(body);
    expect(again.rows[0]).toEqual(parsed.rows[0]);
  });

  it("re-emits what the operator wrote, not what the console coerced", () => {
    // The reason RowVerdict keeps `source` alongside `body`. A blank
    // default_quantity must come back BLANK — coming back absent would change
    // the file's meaning, and coming back as `null` would change its shape.
    const input =
      "code,label,unit,unit_price,default_quantity,notes\n" +
      "RACK,Rack,per rack,45000,4,\n" +
      "AUDIT,Audit,per site,120000,,\n";
    const parsed = parseFile(DESCRIPTORS.pricing, input, "csv");
    const verdict = validateFile(DESCRIPTORS.pricing, parsed.rows, "csv");

    // The coerced body has dropped the blank; the source has not.
    expect("default_quantity" in verdict.rows[1].body).toBe(false);
    expect(verdict.rows[1].source.default_quantity).toBe("");

    const file = failuresFile({
      descriptor: DESCRIPTORS.pricing,
      format: "csv",
      columns: parsed.columns,
      outcomes: verdict.rows.map((r) => outcome(r.line, "refused", r.source, "Program not found")),
    })!;
    const again = parseFile(DESCRIPTORS.pricing, file.text, "csv");
    expect(again.rows).toEqual(parsed.rows);
  });

  it("round-trips a JSON file too", () => {
    const rows = [
      { name: "A", contact_name: "One" },
      { name: "B", contact_name: "Two" },
    ];
    const parsed = parseFile(DESCRIPTORS.vendors, JSON.stringify(rows), "json");
    const file = failuresFile({
      descriptor: DESCRIPTORS.vendors,
      format: "json",
      columns: parsed.columns,
      outcomes: parsed.rows.map((r, i) => outcome(i + 1, "refused", r, "nope")),
    })!;
    const again = parseFile(DESCRIPTORS.vendors, file.text, "json");
    expect(again.rows).toEqual(rows);
    expect(again.ignored).toEqual([ERROR_COLUMN]);
  });

  it("closes the loop: a fixed failures file re-imports clean", () => {
    // The whole point, end to end. Two rows fail on a bad role; the operator
    // edits the role in place and drops the same file back in.
    const input =
      "email,name,role\n" +
      "a@x.com,Ravi Menon,operations_lead\n" +
      "b@x.com,Asha Rao,wizard\n" +
      "c@x.com,Priya Nair,sorcerer\n";
    const parsed = parseFile(DESCRIPTORS.staff, input, "csv");
    const verdict = validateFile(DESCRIPTORS.staff, parsed.rows, "csv");
    expect(verdict.errorCount).toBe(2);

    const file = failuresFile({
      descriptor: DESCRIPTORS.staff,
      format: "csv",
      columns: parsed.columns,
      outcomes: verdict.rows
        .filter((r) => !r.ok)
        .map((r) => outcome(r.line, "refused", r.source, "Unknown role")),
    })!;

    // The operator fixes the two roles in place — nothing else about the file.
    const fixed = file.text.replace(/wizard/, "sales_agent").replace(/sorcerer/, "sales_lead");
    const again = parseFile(DESCRIPTORS.staff, fixed, "csv");
    const rerun = validateFile(DESCRIPTORS.staff, again.rows, "csv");

    expect(again.rows).toHaveLength(2);
    expect(rerun.errorCount).toBe(0);
    expect(rerun.canApply).toBe(true);
  });
});

/** A tiny CSV builder that quotes, so the fixtures above stay readable. */
function Papaish(header: string, rows: string[][]): string {
  const quote = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  return [header, ...rows.map((r) => r.map(quote).join(","))].join("\n") + "\n";
}
