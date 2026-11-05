/**
 * Validating an import file — Task 21 Step 5.
 *
 * The two tests that earn their keep are the unknown column (A7/P9) and the
 * tri-state (§3.3). Both are cases where the *absence* of a check produces a
 * clean-looking import that writes wrong data, which is the failure mode this
 * whole layer exists to prevent.
 */
import { describe, expect, it } from "vitest";

import { schemas } from "../api/generated";
import { DESCRIPTORS } from "../descriptors";
import { parseFile } from "./parse";
import { DOCX_SUPERSEDE_ERROR, expectedColumns, validateFile } from "./validate";
import { templateFor } from "./template";

const csv = (d: keyof typeof DESCRIPTORS, text: string) =>
  validateFile(DESCRIPTORS[d], parseFile(DESCRIPTORS[d], text, "csv").rows, "csv");

const json = (d: keyof typeof DESCRIPTORS, rows: unknown) =>
  validateFile(DESCRIPTORS[d], parseFile(DESCRIPTORS[d], JSON.stringify(rows), "json").rows, "json");

describe("A7 — the unknown-column check runs before Zod", () => {
  it("rejects a typo'd column that Zod would happily accept", () => {
    // The exact scenario P9 names. Proved in two halves: the schema passes it,
    // and this layer does not.
    const verdict = csv(
      "programs",
      "name,code,descriptionn\nDatacentre,DC,Commissioning and handover.\n",
    );
    expect(verdict.canApply).toBe(false);
    expect(verdict.rows[0].errors.descriptionn).toContain('Unknown column "descriptionn"');
    expect(verdict.rows[0].errors.descriptionn).toContain("name, code, description");
  });

  it("proves the generated schema would NOT have caught it", () => {
    // If this ever fails, the generator has started emitting .strict() and the
    // column check could in principle be dropped — read P9 before doing so.
    const schema = schemas[DESCRIPTORS.programs.writeSchema];
    const result = (schema as unknown as { safeParse: (v: unknown) => { success: boolean } })
      .safeParse({ name: "X", code: "Y", descriptionn: "typo" });
    expect(result.success, "passthrough: an unknown key validates clean").toBe(true);
  });

  it("names every column the entity does accept, so the fix is obvious", () => {
    const verdict = csv("vendors", "name,phne\nNorthgate,123\n");
    const message = verdict.rows[0].errors.phne;
    for (const column of expectedColumns(DESCRIPTORS.vendors, false)) {
      expect(message).toContain(column);
    }
  });

  it("does not run Zod's complaints on top of a column error", () => {
    // One clear cause beats five downstream symptoms.
    const verdict = csv("staff", "emial,name,role\nx@y.com,Ravi,sales_agent\n");
    expect(Object.keys(verdict.rows[0].errors)).toEqual(["emial"]);
  });
});

describe("§3.3 — empty is not zero and not null", () => {
  const header = "code,label,unit,unit_price,default_quantity,notes\n";

  it("gives three distinct outcomes for '', '0' and '1'", () => {
    const verdict = csv(
      "pricing",
      header +
        "A,Rack,per rack,45000,,\n" +
        "B,Audit,per site,120000,0,\n" +
        "C,Survey,per site,9000,1,\n",
    );
    expect(verdict.errorCount).toBe(0);
    expect("default_quantity" in verdict.rows[0].body).toBe(false);
    expect(verdict.rows[1].body.default_quantity).toBe(0);
    expect(verdict.rows[2].body.default_quantity).toBe(1);
  });

  it("keeps a real zero price rather than dropping it as blank", () => {
    const verdict = csv("pricing", header + "A,Included,per site,0,,\n");
    expect(verdict.rows[0].body.unit_price).toBe(0);
  });

  it("drops a blank optional column instead of sending an empty string", () => {
    const verdict = csv("staff", "email,name,role,department\nx@y.com,Ravi,sales_agent,\n");
    expect("department" in verdict.rows[0].body).toBe(false);
  });

  it("refuses a numeric cell that is not a number", () => {
    const verdict = csv("pricing", header + "A,Rack,per rack,forty-five,,\n");
    expect(verdict.rows[0].errors.unit_price).toBe('"forty-five" is not a number');
  });
});

describe("a pricing CSV is one call, not one call per row", () => {
  it("groups the lines into a single versioned card", () => {
    const verdict = csv(
      "pricing",
      "code,label,unit,unit_price,default_quantity,notes\n" +
        "RACK,Rack commissioning,per rack,45000,4,\n" +
        "AUDIT,Capacity audit,per site,120000,,Two-day survey\n",
    );
    expect(verdict.shape).toBe("file-is-one-call");
    expect(verdict.grouped).toEqual({
      items: [
        { code: "RACK", label: "Rack commissioning", unit: "per rack", unit_price: 45000, default_quantity: 4 },
        { code: "AUDIT", label: "Capacity audit", unit: "per site", unit_price: 120000, notes: "Two-day survey" },
      ],
    });
  });

  it("but a pricing JSON file carries the entity shape and is one call per row", () => {
    const verdict = json("pricing", [
      { currency: "INR", items: [{ code: "A", label: "A", unit_price: 1 }] },
    ]);
    expect(verdict.shape).toBe("row-per-call");
    expect(verdict.rows[0].ok).toBe(true);
  });
});

describe("per-row verdicts", () => {
  it("reports each row separately, by the line number the operator sees", () => {
    const verdict = csv(
      "staff",
      "email,name,role\n" +
        "good@x.com,Ravi Menon,operations_lead\n" +
        "bad@x.com,R,operations_lead\n" +
        "also@x.com,Asha Rao,wizard\n",
    );
    expect(verdict.rows.map((r) => [r.line, r.ok])).toEqual([
      [1, true],
      [2, false],
      [3, false],
    ]);
    expect(verdict.rows[1].errors.name).toContain("at least 2");
    expect(verdict.rows[2].errors.role).toContain("Must be one of");
    expect(verdict.okCount).toBe(1);
    expect(verdict.errorCount).toBe(2);
  });

  it("gates apply on ZERO errors, not on most of them", () => {
    // The backend has no bulk transaction, so a file applied with known-bad
    // rows leaves a half-written catalogue and no way to reason about it.
    const oneBad = csv("vendors", "name\nA\n\nB\n");
    expect(oneBad.canApply).toBe(true);
    const withBad = csv("staff", "email,name,role\nx@y.com,R,sales_agent\n");
    expect(withBad.errorCount).toBe(1);
    expect(withBad.canApply).toBe(false);
  });

  it("refuses an empty file", () => {
    expect(validateFile(DESCRIPTORS.vendors, [], "csv").canApply).toBe(false);
  });

  it("carries the cross-field rule into the file path", () => {
    // The same rule the interactive form enforces: an email template needs a
    // subject. A file must not be a way around a rule a form applies.
    const verdict = csv(
      "messageTemplates",
      "kind,channel,name,subject,body\nintro,email,Intro,,Hello there my friend\n",
    );
    expect(verdict.rows[0].errors.subject).toContain("Email templates need a subject");
  });
});

describe("every entity can produce a template at all", () => {
  it("the three JSON-only entities carry their own worked example", () => {
    // They have no `csv.example` to derive one from. An earlier version of
    // template.ts invented one from the field controls and produced a playbook
    // with no programme and an empty entry list, which the round-trip test
    // below caught. The example is now declared, so it is reviewable.
    const jsonOnly = Object.values(DESCRIPTORS).filter((d) => d.csv === null);
    expect(jsonOnly.map((d) => d.key).sort()).toEqual([
      "approvalRules",
      "playbooks",
      "settings",
    ]);
    for (const d of jsonOnly) {
      expect(d.jsonExample, d.key).toBeTruthy();
      expect(Object.keys(d.jsonExample ?? {}).length, d.key).toBeGreaterThan(2);
    }
  });

  it("and the CSV entities derive theirs, so nothing is declared twice", () => {
    for (const d of Object.values(DESCRIPTORS).filter((x) => x.csv !== null)) {
      expect(d.jsonExample, `${d.key} should derive from csv.example`).toBeUndefined();
    }
  });
});

describe("the template round-trips through the parser", () => {
  it("every entity's own template validates clean", () => {
    // The strongest thing this suite can say: the file the console hands the
    // operator is a file the console accepts. A template that failed its own
    // validator would be discovered by the operator, once, badly.
    for (const descriptor of Object.values(DESCRIPTORS)) {
      const formats = descriptor.csv ? (["csv", "json"] as const) : (["json"] as const);
      for (const format of formats) {
        const text = templateFor(descriptor, format);
        const parsed = parseFile(descriptor, text, format);
        expect(parsed.fatal, `${descriptor.key} ${format}`).toBeNull();
        const verdict = validateFile(descriptor, parsed.rows, format);
        const messages = verdict.rows.flatMap((r) => Object.entries(r.errors));
        expect(messages, `${descriptor.key} ${format}`).toEqual([]);
      }
    }
  });

  it("the proposal-template CSV example really does carry a quoted newline", () => {
    // Not a claim about quoting in the abstract: the example the operator
    // downloads has to be the one that demonstrates the trap.
    const text = templateFor(DESCRIPTORS.proposalTemplates, "csv");
    expect(text).toContain('"');
    const parsed = parseFile(DESCRIPTORS.proposalTemplates, text, "csv");
    expect(parsed.rows).toHaveLength(1);
    expect(String(parsed.rows[0].body_md)).toContain("\n");
  });
});

describe("importing over a Word-document template", () => {
  const rows = [{ name: "Standard", body_md: "## Scope\n\nEnough body text here." }];

  it("refuses the file rather than warning about it", () => {
    // Applying this would replace a branded document with a plain text one,
    // silently, on the way to a client. That is the failure the docx path
    // exists to remove, so it blocks the apply.
    const verdict = validateFile(DESCRIPTORS.proposalTemplates, rows, "json", {
      supersedesDocxTemplate: true,
    });
    expect(verdict.canApply).toBe(false);
    expect(verdict.errorCount).toBe(1);
    expect(Object.values(verdict.rows[0].errors)).toContain(DOCX_SUPERSEDE_ERROR);
  });

  it("is silent when the current template is markdown", () => {
    const verdict = validateFile(DESCRIPTORS.proposalTemplates, rows, "json", {
      supersedesDocxTemplate: false,
    });
    expect(verdict.canApply).toBe(true);
  });

  it("defaults to permitting, so every other entity is unaffected", () => {
    expect(validateFile(DESCRIPTORS.proposalTemplates, rows, "json").canApply).toBe(true);
  });
});
