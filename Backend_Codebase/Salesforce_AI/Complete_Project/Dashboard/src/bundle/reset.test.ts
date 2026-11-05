/**
 * Reset — the derivation behind the destructive screen. Task 24 Steps 1–3.
 *
 * The plan names only `roundtrip.test.ts`; this file exists because the reset
 * derivation is the one place in the console where being wrong destroys data,
 * and "we read the endpoint carefully" is not a mechanism.
 */
import { describe, expect, it } from "vitest";

import { schemas } from "../api/generated";
import { READS } from "../api/reads";
import { RESET_TAXONOMY } from "../api/vocabularies.generated";
import {
  ALL_FLAGS,
  CATALOGUE_ONLY,
  NO_FLAGS,
  anyFlagSet,
  blockedReason,
  bucketsFor,
  edgesApplyTo,
  flagFor,
  selectedTotal,
} from "./reset";

const ORG = "Fixture Org";

/** A PREVIEW_ALL response: one row in a few tables, absent for KEEP. */
const preview = READS.resetDryRun.parse({
  org: { id: "org-1", name: ORG },
  counts: {
    ...Object.fromEntries(RESET_TAXONOMY.buckets.WIPE.map((t) => [t, 0])),
    ...Object.fromEntries(RESET_TAXONOMY.buckets.REPLACE.map((t) => [t, 0])),
    ...Object.fromEntries(RESET_TAXONOMY.buckets.CONFIG.map((t) => [t, 0])),
    proposals: 3,
    projects: 1,
    programs: 2,
    user_skills: 5,
    approval_rules: 2,
  },
  total: 13,
  applied: false,
  blocking_edges: [],
});

const EDGES = [
  { table: "proposals", column: "program_id", references: "programs", count: 3 },
];

describe("the four buckets", () => {
  it("renders all four, with KEEP last and never selected", () => {
    const views = bucketsFor(preview, ALL_FLAGS);
    expect(views.map((v) => v.bucket)).toEqual(["WIPE", "REPLACE", "CONFIG", "KEEP"]);
    const keep = views.find((v) => v.bucket === "KEEP")!;
    expect(keep.flag).toBeNull();
    expect(keep.selected).toBe(false);
  });

  it("covers all 59 tables exactly once — the console shows the whole schema", () => {
    // A table missing from the console's list simply does not appear in the
    // preview, so the operator approves a reset having been shown less than it
    // does. This is the assertion that makes that impossible.
    //
    // 59 since proposal_fill_sessions joined WIPE: a half-answered fill is a
    //
    // mou_documents (M2) and mou_revisions (F3) joined WIPE: a client's
    // contract and what it said before a correction are transactional work,
    // not catalogue. Both are deleted before the proposals a fill session may
    // also reference.
    // client's work in progress, not a catalogue entry.
    //
    // 56 since proposal_template_docs joined REPLACE beside
    // proposal_templates: a docx template's uploaded document is part of
    // the template, so a reset must clear both or leave a template row
    // pointing at a file that is gone.
    const tables = bucketsFor(preview, ALL_FLAGS).flatMap((v) => v.tables.map((t) => t.table));
    expect(tables).toHaveLength(59);
    expect(new Set(tables).size).toBe(59);
  });

  it("KEEP has no counts, because no reset response mentions its tables", () => {
    const keep = bucketsFor(preview, ALL_FLAGS).find((v) => v.bucket === "KEEP")!;
    expect(keep.total).toBeNull();
    for (const t of keep.tables) expect(t.count).toBeNull();
    expect(keep.note).toContain("no counts");
  });

  it("an absent table is unreported, not zero", () => {
    // The distinction matters: `counts` covers only the flags the dry run was
    // called with, so "missing" and "empty" are different facts.
    const partial = { ...preview, counts: { proposals: 3 } };
    const wipe = bucketsFor(partial, ALL_FLAGS).find((v) => v.bucket === "WIPE")!;
    expect(wipe.tables.find((t) => t.table === "proposals")!.count).toBe(3);
    expect(wipe.tables.find((t) => t.table === "projects")!.count).toBeNull();
  });

  it("with no preview yet, every count is null rather than zero", () => {
    const views = bucketsFor(null, ALL_FLAGS);
    for (const v of views) {
      expect(v.total).toBeNull();
      expect(v.nonEmpty).toEqual([]);
    }
  });

  it("totals and non-empty lists come from the counts, per bucket", () => {
    const views = bucketsFor(preview, ALL_FLAGS);
    const byName = Object.fromEntries(views.map((v) => [v.bucket, v]));
    expect(byName.WIPE.total).toBe(4);         // proposals 3 + projects 1
    expect(byName.REPLACE.total).toBe(2);      // programs 2
    expect(byName.CONFIG.total).toBe(7);       // skills 5 + rules 2
    expect(byName.CONFIG.nonEmpty.map((t) => t.table).sort())
      .toEqual(["approval_rules", "user_skills"]);
  });
});

describe("flags", () => {
  it("every bucket but KEEP names a real field of the generated ResetRequest", () => {
    // RESET_TAXONOMY.clearedBy holds deletion_order's PARAMETER names; the
    // request field is that with a `wipe_` prefix. That prefix is the one link
    // in the chain that is neither imported nor AST-read, so it is asserted
    // against the generated schema rather than trusted.
    const requestFields = Object.keys(
      (schemas.ResetRequest as unknown as { shape: object }).shape,
    );
    for (const bucket of ["WIPE", "REPLACE", "CONFIG"] as const) {
      const flag = flagFor(bucket);
      expect(flag, `${bucket} must name a flag`).not.toBeNull();
      expect(requestFields, `${bucket} → ${flag}`).toContain(flag);
    }
    expect(flagFor("KEEP")).toBeNull();
  });

  it("maps each bucket to the flag reset_taxonomy.deletion_order actually uses", () => {
    expect(flagFor("WIPE")).toBe("wipe_transactional");
    expect(flagFor("REPLACE")).toBe("wipe_catalogue");
    expect(flagFor("CONFIG")).toBe("wipe_org_config");
  });

  it("selectedTotal sums only the ticked buckets, never preview.total", () => {
    // preview.total is the total for ALL THREE flags and would overstate any
    // narrower selection — the number beside a destructive button.
    expect(selectedTotal(preview, ALL_FLAGS)).toBe(13);
    expect(selectedTotal(preview, { ...NO_FLAGS, wipe_org_config: true })).toBe(7);
    expect(selectedTotal(preview, CATALOGUE_ONLY)).toBe(2);
    expect(selectedTotal(preview, NO_FLAGS)).toBe(0);
    expect(preview.total).toBe(13);
  });

  it("anyFlagSet is false only when nothing is chosen", () => {
    expect(anyFlagSet(NO_FLAGS)).toBe(false);
    expect(anyFlagSet(CATALOGUE_ONLY)).toBe(true);
  });
});

describe("D22 — the conditional refusal", () => {
  it("applies only to catalogue-without-transactional, the server's own condition", () => {
    expect(edgesApplyTo(CATALOGUE_ONLY)).toBe(true);
    expect(edgesApplyTo(ALL_FLAGS)).toBe(false);
    expect(edgesApplyTo(NO_FLAGS)).toBe(false);
    // With both set, WIPE precedes REPLACE in deletion_order, so the children
    // are gone first and nothing can be orphaned.
    expect(edgesApplyTo({ ...CATALOGUE_ONLY, wipe_transactional: true })).toBe(false);
  });

  it("blocks the apply before sending when edges exist", () => {
    const why = blockedReason({
      flags: CATALOGUE_ONLY,
      blockingEdges: EDGES,
      typedName: ORG,
      orgName: ORG,
    });
    expect(why).toContain("orphan");
    expect(why).toContain("transactional");
  });

  it("does NOT block the same edges when transactional is also ticked", () => {
    expect(
      blockedReason({
        flags: ALL_FLAGS,
        blockingEdges: EDGES,
        typedName: ORG,
        orgName: ORG,
      }),
    ).toBeNull();
  });

  it("does not block a catalogue-only reset with no edges — that org is who it is for", () => {
    // `_catalogue_blocking_edges` counts only NOT NULL references, and a
    // pre-go-live org with none of those rows must not be refused.
    expect(
      blockedReason({ flags: CATALOGUE_ONLY, blockingEdges: [], typedName: ORG, orgName: ORG }),
    ).toBeNull();
  });
});

describe("the confirmation", () => {
  it("requires the organisation's own name, exactly", () => {
    const base = { flags: ALL_FLAGS, blockingEdges: [], orgName: ORG };
    expect(blockedReason({ ...base, typedName: "" })).toContain(ORG);
    expect(blockedReason({ ...base, typedName: "fixture org" })).toContain(ORG);
    expect(blockedReason({ ...base, typedName: ` ${ORG} ` })).toBeNull();
  });

  it("asks for a flag before it asks for a name", () => {
    // Ordering, not cosmetics: a screen that demands the name first makes the
    // operator type it and then discover nothing was selected.
    expect(
      blockedReason({ flags: NO_FLAGS, blockingEdges: [], typedName: ORG, orgName: ORG }),
    ).toContain("at least one");
  });

  it("reports the orphan problem before the name, since typing cannot fix it", () => {
    expect(
      blockedReason({ flags: CATALOGUE_ONLY, blockingEdges: EDGES, typedName: "", orgName: ORG }),
    ).toContain("orphan");
  });
});
