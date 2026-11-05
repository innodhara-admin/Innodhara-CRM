/**
 * The drift tests — 06_DESIGN.md §3.2, mechanisms 2 and 3.
 *
 * A descriptor is hand-written, so it can name a field the backend no longer
 * has. These turn that into a failing test rather than a form control that
 * silently sends a key the server ignores.
 *
 * The round-trip test is the one worth reading. It is derived entirely from
 * `generated.ts`, and **it would have caught P4 and P5 by itself** — the two
 * defects that reopened the backend change list, where `GET /approval-rules`
 * omitted two fields the write accepted and `GET /admin/demo-teams` returned
 * names where the write took ids. Both were found by hand. They cannot recur
 * unnoticed now.
 */
import { describe, expect, it } from "vitest";
import { z } from "zod";

import { schemas } from "../api/generated";
import { READS, READ_SOURCE } from "../api/reads";
import { ALL_DESCRIPTORS, DESCRIPTORS, dependencyOrder } from "./index";
import type { Descriptor } from "./types";

/** Field names of a Zod object, unwrapping arrays and effects. */
function fieldsOf(schema: z.ZodTypeAny): string[] {
  let s: z.ZodTypeAny = schema;
  for (let i = 0; i < 6; i += 1) {
    if (s instanceof z.ZodArray) s = s.element;
    else if (s instanceof z.ZodOptional || s instanceof z.ZodNullable) s = s.unwrap();
    else if (s instanceof z.ZodEffects) s = s.innerType();
    else break;
  }
  return s instanceof z.ZodObject ? Object.keys(s.shape) : [];
}

const writeFields = (d: Descriptor) => fieldsOf(schemas[d.writeSchema] as z.ZodTypeAny);
const readFields = (d: Descriptor) =>
  d.read ? fieldsOf(READS[d.read] as z.ZodTypeAny) : [];

describe("descriptor → generated schema", () => {
  it.each(ALL_DESCRIPTORS.map((d) => [d.key, d] as const))(
    "%s names only fields its write schema has",
    (_key, d) => {
      const known = new Set(writeFields(d));
      const unknown = d.fields.map((f) => f.field).filter((f) => !known.has(f));
      expect(unknown, `not in ${d.writeSchema}`).toEqual([]);
    },
  );

  it("every descriptor resolves to a real generated schema", () => {
    for (const d of ALL_DESCRIPTORS) {
      expect(schemas, d.key).toHaveProperty(d.writeSchema);
    }
  });

  it("names no field twice", () => {
    for (const d of ALL_DESCRIPTORS) {
      const names = d.fields.map((f) => f.field);
      expect(new Set(names).size, d.key).toBe(names.length);
    }
  });
});

describe("enforcement is claimed honestly", () => {
  it("a `schema` rule really is in generated.ts as a constrained field", () => {
    // The failure this catches: labelling a field `schema` when the generator
    // dropped its constraint (P2), so the caption promises server enforcement
    // the console never validates.
    for (const d of ALL_DESCRIPTORS) {
      const shape = (schemas[d.writeSchema] as z.ZodObject<z.ZodRawShape>).shape;
      for (const rule of d.fields) {
        if (rule.enforcement.kind !== "schema") continue;
        expect(shape, `${d.key}.${rule.field}`).toHaveProperty(rule.field);
      }
    }
  });

  it("a `backend-undeclared` rule cites a file and a symbol", () => {
    for (const d of ALL_DESCRIPTORS) {
      for (const rule of d.fields) {
        if (rule.enforcement.kind !== "backend-undeclared") continue;
        // Captions cite file and symbol, never line numbers (§9).
        expect(rule.enforcement.source, `${d.key}.${rule.field}`).toMatch(
          /^[\w./]+\.py · \w+$/,
        );
        expect(rule.enforcement.source).not.toMatch(/:\d+/);
      }
    }
  });

  it("a `ui-only` rule says what the server does instead", () => {
    for (const d of ALL_DESCRIPTORS) {
      for (const rule of d.fields) {
        if (rule.enforcement.kind !== "ui-only") continue;
        expect(rule.enforcement.why.length, `${d.key}.${rule.field}`).toBeGreaterThan(15);
      }
    }
  });

  it("every option list comes from a vocabulary, not a literal", () => {
    // A4: no role or department list is ever typed by hand here.
    for (const d of ALL_DESCRIPTORS) {
      for (const rule of d.fields) {
        if (!rule.options) continue;
        expect(rule.options.length, `${d.key}.${rule.field}`).toBeGreaterThan(0);
        expect(rule.options, `${d.key}.${rule.field}`).not.toContain("super_admin");
      }
    }
  });
});

describe("round trip — every writable field is readable back", () => {
  // This is P4 and P5 turned into a guard. A bundle can only restore what the
  // API will hand back, so a write field with no read field is a silent loss
  // at reseed time.
  it.each(
    ALL_DESCRIPTORS.filter((d) => d.inBundle && d.read).map((d) => [d.key, d] as const),
  )("%s", (_key, d) => {
    const readable = new Set([
      ...readFields(d),
      ...Object.values(d.aliases ?? {}),
    ]);
    const writeOnly = new Set(d.writeOnly ?? []);
    const lost = writeFields(d).filter(
      (f) => !writeOnly.has(f) && !readable.has(f) && !readable.has(d.aliases?.[f] ?? f),
    );
    expect(
      lost,
      `${d.key}: the write accepts these and ${READ_SOURCE[d.read!]} does not return them, ` +
        "so the reseed bundle would drop them",
    ).toEqual([]);
  });

  it("covers approval rules and demo teams — the two that failed before", () => {
    // Named, so a future refactor that quietly stops iterating them fails here.
    const ruleReads = readFields(DESCRIPTORS.approvalRules);
    expect(ruleReads).toContain("fallback_role"); // change #9
    expect(ruleReads).toContain("auto_approve");  // change #9
    const teamReads = readFields(DESCRIPTORS.demoTeams);
    expect(teamReads).toContain("lead_user_id");  // change #10
    expect(teamReads).toContain("media_rep_id");
    expect(teamReads).toContain("sales_rep_id");
    // …and the names the Android app renders are still there (09 §2 rule 1).
    expect(teamReads).toContain("lead");
  });

  it("every alias points at a field the read actually has", () => {
    for (const d of ALL_DESCRIPTORS) {
      for (const [write, read] of Object.entries(d.aliases ?? {})) {
        expect(writeFields(d), `${d.key} alias source`).toContain(write);
        expect(readFields(d), `${d.key} alias target`).toContain(read);
      }
    }
  });
});

describe("coverage", () => {
  it("every read shape belongs to a descriptor or is accounted for", () => {
    const used = new Set(ALL_DESCRIPTORS.map((d) => d.read).filter(Boolean));
    // resetDryRun has no entity descriptor — it is Task 24's screen, not a
    // catalogue entity. Named rather than skipped by a wildcard.
    const standalone = new Set(["resetDryRun"]);
    const orphans = Object.keys(READS).filter(
      (k) => !used.has(k as never) && !standalone.has(k),
    );
    expect(orphans).toEqual([]);
  });

  it("every read shape cites the handler it was transcribed from", () => {
    for (const key of Object.keys(READS)) {
      expect(READ_SOURCE, key).toHaveProperty(key);
      expect(READ_SOURCE[key as keyof typeof READ_SOURCE]).toMatch(/\.py · \w+$/);
    }
  });

  it("all eleven entities are present and each carries the manual's words", () => {
    expect(ALL_DESCRIPTORS).toHaveLength(11);
    for (const d of ALL_DESCRIPTORS) {
      expect(d.quote.length, d.key).toBeGreaterThan(40);
      expect(d.ifSkipped.length, d.key).toBeGreaterThan(15);
      expect(d.manualRef, d.key).toMatch(/item \d+$/);
      expect(d.reimport.length, d.key).toBeGreaterThan(15);
    }
  });

  it("a CSV template lists exactly the columns its example fills", () => {
    for (const d of ALL_DESCRIPTORS) {
      if (!d.csv) continue;
      expect([...d.csv.columns].sort(), d.key).toEqual(
        Object.keys(d.csv.example).sort(),
      );
    }
  });
});

describe("dependency order", () => {
  it("puts every prerequisite before the entity that needs it", () => {
    const order = dependencyOrder();
    expect(order).toHaveLength(11);
    for (const d of ALL_DESCRIPTORS) {
      for (const parent of d.dependsOn) {
        expect(order.indexOf(parent), `${parent} before ${d.key}`).toBeLessThan(
          order.indexOf(d.key),
        );
      }
    }
  });

  it("matches the hard dependencies 02 §0 derived from the schema", () => {
    expect(DESCRIPTORS.skills.dependsOn).toEqual(["staff"]);
    expect(DESCRIPTORS.pricing.dependsOn).toEqual(["programs"]);
    expect(DESCRIPTORS.proposalTemplates.dependsOn).toEqual(["programs"]);
    expect(DESCRIPTORS.playbooks.dependsOn).toEqual(["programs"]);
    expect(DESCRIPTORS.demoTeams.dependsOn).toEqual(["staff"]);
    // Message templates are org-wide with no program FK — a real asymmetry
    // with the other three catalogue families.
    expect(DESCRIPTORS.messageTemplates.dependsOn).toEqual([]);
  });
});
