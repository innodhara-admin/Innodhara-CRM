/**
 * Reading an import file — Task 21 Step 5.
 *
 * Two of these are the reason the module exists at all: the CSV quoting trap
 * (a template body contains newlines, and an unquoted one shifts every column
 * after it) and D21's `_`-prefixed columns, which are what make a failures file
 * directly re-importable.
 */
import { describe, expect, it } from "vitest";

import { DESCRIPTORS } from "../descriptors";
import { detectFormat, formatsFor, parseFile } from "./parse";

describe("CSV", () => {
  it("reads a plain file", () => {
    const result = parseFile(
      DESCRIPTORS.staff,
      "email,name,role\nravi@x.com,Ravi Menon,operations_lead\n",
      "csv",
    );
    expect(result.fatal).toBeNull();
    expect(result.columns).toEqual(["email", "name", "role"]);
    expect(result.rows).toEqual([
      { email: "ravi@x.com", name: "Ravi Menon", role: "operations_lead" },
    ]);
  });

  it("survives an embedded newline inside a quoted field", () => {
    // The trap: `body_md` is prose. Quoted, this is ONE row of two columns.
    const csv = 'name,body_md\nStandard,"## Scope\n\nCommissioning for {client_name}.\n"\n';
    const result = parseFile(DESCRIPTORS.proposalTemplates, csv, "csv");
    expect(result.fatal).toBeNull();
    expect(result.rows).toHaveLength(1);
    expect(result.rows[0].body_md).toBe("## Scope\n\nCommissioning for {client_name}.\n");
  });

  it("keeps an unknown column rather than dropping it", () => {
    // The whole A7 check depends on this: a parser that quietly discarded
    // unknown columns would make the unknown-column error impossible to raise.
    const result = parseFile(DESCRIPTORS.programs, "name,code,nonsense\nX,Y,Z\n", "csv");
    expect(result.columns).toContain("nonsense");
    expect(result.rows[0].nonsense).toBe("Z");
  });

  it("does not type-convert: '0' and '' stay distinct strings", () => {
    // papaparse's dynamicTyping would make these 0 and null, and the tri-state
    // needs all three of "", "0" and "1" to survive to validate.ts (§3.3).
    const result = parseFile(
      DESCRIPTORS.pricing,
      "code,label,unit,unit_price,default_quantity,notes\nA,A,per rack,0,,\n",
      "csv",
    );
    expect(result.rows[0].unit_price).toBe("0");
    expect(result.rows[0].default_quantity).toBe("");
  });

  it("refuses CSV for the three JSON-only entities, and says why", () => {
    for (const key of ["playbooks", "approvalRules", "settings"] as const) {
      const result = parseFile(DESCRIPTORS[key], "a,b\n1,2\n", "csv");
      expect(result.fatal, key).toBeTruthy();
      expect(result.fatal, key).toContain("Use JSON");
    }
  });

  it("takes the accepted formats from the descriptor, not a list of its own", () => {
    expect(formatsFor(DESCRIPTORS.staff)).toEqual(["csv", "json"]);
    expect(formatsFor(DESCRIPTORS.settings)).toEqual(["json"]);
    // Every JSON-only entity is one whose descriptor says csv: null.
    const jsonOnly = Object.values(DESCRIPTORS)
      .filter((d) => d.csv === null)
      .map((d) => d.key)
      .sort();
    expect(jsonOnly).toEqual(["approvalRules", "playbooks", "settings"]);
  });
});

describe("`_` columns — D21's re-importable failures file", () => {
  it("ignores them and reports that it did", () => {
    const csv = "email,name,role,_error\nravi@x.com,Ravi,sales_agent,User already exists\n";
    const result = parseFile(DESCRIPTORS.staff, csv, "csv");
    expect(result.ignored).toEqual(["_error"]);
    expect(result.columns).not.toContain("_error");
    expect(result.rows[0]).not.toHaveProperty("_error");
    // And what remains is exactly the original row, ready to go back.
    expect(result.rows[0]).toEqual({ email: "ravi@x.com", name: "Ravi", role: "sales_agent" });
  });

  it("ignores them in JSON too", () => {
    const result = parseFile(
      DESCRIPTORS.programs,
      JSON.stringify([{ name: "X", code: "Y", _error: "boom" }]),
      "json",
    );
    expect(result.ignored).toEqual(["_error"]);
    expect(result.rows[0]).toEqual({ name: "X", code: "Y" });
  });
});

describe("JSON", () => {
  it("accepts an array of rows", () => {
    const result = parseFile(
      DESCRIPTORS.vendors,
      JSON.stringify([{ name: "A" }, { name: "B" }]),
      "json",
    );
    expect(result.rows).toHaveLength(2);
  });

  it("accepts a bare object as a one-row file", () => {
    const result = parseFile(DESCRIPTORS.vendors, JSON.stringify({ name: "A" }), "json");
    expect(result.rows).toEqual([{ name: "A" }]);
  });

  it("refuses a settings file holding more than one row", () => {
    const result = parseFile(
      DESCRIPTORS.settings,
      JSON.stringify([{ timezone: "Asia/Kolkata" }, { timezone: "UTC" }]),
      "json",
    );
    expect(result.fatal).toContain("one row, not a list");
  });

  it("reports bad JSON as fatal rather than as an empty file", () => {
    const result = parseFile(DESCRIPTORS.vendors, "{oops", "json");
    expect(result.fatal).toContain("Not valid JSON");
    expect(result.rows).toEqual([]);
  });

  it("refuses a list of things that are not objects", () => {
    const result = parseFile(DESCRIPTORS.vendors, JSON.stringify(["a", "b"]), "json");
    expect(result.fatal).toContain("must be a JSON object");
  });
});

describe("format detection", () => {
  it("reads the extension and defaults to JSON", () => {
    expect(detectFormat("staff.csv")).toBe("csv");
    expect(detectFormat("STAFF.CSV")).toBe("csv");
    expect(detectFormat("staff.json")).toBe("json");
    expect(detectFormat("staff")).toBe("json");
  });
});
