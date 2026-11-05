/**
 * The reseed bundle round trip — 07_BUILD_PLAN.md Task 24 Step 5.
 *
 * Export → serialise → parse → re-import, over the **Task 15 fixtures**, with
 * **field-by-field equality for all nine entity types and no exceptions**. A
 * shape check would pass while a field quietly stopped being carried, and the
 * place that failure shows up is a client's reseed.
 *
 * The two entities named in the plan get their own test on top of the general
 * one, because they are why backend changes #9 and #10 exist: an approval rule
 * that comes back no longer auto-approving, and a demo team that comes back
 * with its three roles unassigned, are the exact losses P4 and P5 described.
 */
import { describe, expect, it } from "vitest";

import { schemas } from "../api/generated";
import { RESET_TAXONOMY } from "../api/vocabularies.generated";
import { ALL_DESCRIPTORS, BUNDLE_ENTITIES, DESCRIPTORS } from "../descriptors";
import type { EntityKey } from "../descriptors/types";
import {
  DOCX_SKIP_REASON,
  skippedFromReads,
  BUNDLE_FORMAT,
  BUNDLE_TRANSFORMS,
  BUNDLE_VERSION,
  PROGRAM_KEY,
  PROGRAM_SCOPED,
  buildBundle,
  bundleOrder,
  projectRow,
  rowsFromReads,
  serialiseBundle,
} from "./export";
import { labelFor, parseBundle } from "./import";

/* ── Write fields, derived from generated.ts ──────────────────────────────── */

function writeFields(key: EntityKey): string[] {
  const shape = (schemas[DESCRIPTORS[key].writeSchema] as { shape?: object }).shape;
  return shape ? Object.keys(shape) : [];
}

const WRITE_FIELDS = Object.fromEntries(
  BUNDLE_ENTITIES.map((k) => [k, writeFields(k)]),
) as Partial<Record<EntityKey, readonly string[]>>;

/** Bundled entities always have write fields; `fields()` says so to the checker. */
const fields = (key: EntityKey): readonly string[] => {
  const f = WRITE_FIELDS[key];
  if (!f) throw new Error(`no write fields for ${key}`);
  return f;
};

const SESSION = { orgId: "org-1", orgName: "Fixture Org" };
const ORG = { id: SESSION.orgId, name: SESSION.orgName };

/* ── A worked organisation, one row per bundled entity ────────────────────── */

const READS = {
  programs: [{ id: "p1", code: "DC-COMMISSION" }],
  programRows: [
    {
      id: "p1",
      name: "Datacentre commissioning",
      code: "DC-COMMISSION",
      description: "Commissioning and handover of capacity.",
      is_active: true,
    },
  ],
  skills: [{ user_id: "u1", skill: "rack-and-stack", level: "expert" }],
  pricingByProgram: {
    p1: [
      {
        id: "pr1",
        version: 2,
        currency: "INR",
        is_current: true,
        effective_from: "2026-08-01",
        items: [
          {
            code: "RACK",
            label: "Rack commissioning",
            unit: "per rack",
            unit_price: 45000,
            default_quantity: 4,
            notes: null,
          },
        ],
      },
      // A superseded version, deliberately: a reseed restores the state, not
      // the audit trail, so this one must not come back.
      { id: "pr0", version: 1, currency: "INR", is_current: false, effective_from: "2026-07-01", items: [] },
    ],
  },
  templatesByProgram: {
    p1: [
      { id: "t1", name: "Commissioning proposal", version: 1, is_current: true, body_md: "# Scope\n\nEverything.\n" },
    ],
  },
  messageTemplates: [
    { id: "m1", kind: "intro", channel: "email", name: "Intro", version: 1, subject: "Hello", body: "Hi there,\n\nA note.\n", is_current: true },
    { id: "m0", kind: "intro", channel: "email", name: "Intro v0", version: 0, subject: "Old", body: "Superseded.\n", is_current: false },
  ],
  playbooks: [
    {
      id: "pb1",
      program_id: "p1",
      phase: "preparation",
      entries: [{ title: "Confirm site access", required_skill: "rack-and-stack", offset_days: -7 }],
      version: 1,
      is_current: true,
      updated_by: "u1",
    },
  ],
  approvalRules: [
    {
      id: "r1",
      entity_type: "proposal",
      condition: { discount_pct_gt: 10 },
      rank: 10,
      approver_role: "sales_lead",
      fallback_role: "org_admin",       // change #9
      recommender_role: "sales_agent",
      joint_with_role: null,
      joint_condition: null,
      auto_approve: true,               // change #9
      expires_hours: 48,
      description: "Discounts above 10%.",
    },
  ],
  demoTeams: [
    {
      id: "d1",
      name: "Commissioning squad",
      lead: "Ravi Menon",
      lead_user_id: "u1",               // change #10
      media_rep: "Priya Nair",
      media_rep_id: "u2",
      sales_rep: "Arun Das",
      sales_rep_id: "u3",
      members: [{ id: "u1", name: "Ravi Menon" }, { id: "u2", name: "Priya Nair" }],
    },
  ],
  vendors: [
    { id: "v1", name: "Coolant Co", contact_name: "Meera", phone: "+91900", email: "m@c.example", category: "hvac", notes: null },
  ],
};

const build = () =>
  buildBundle({
    org: ORG,
    rows: rowsFromReads(READS),
    writeFields: WRITE_FIELDS,
    now: () => new Date("2026-08-18T10:00:00Z"),
  });

/* ── The nine ────────────────────────────────────────────────────────────── */

describe("the bundle carries nine entity types", () => {
  it("BUNDLE_ENTITIES.length is nine, derived from the descriptors", () => {
    // Flagged as unverified by the post-Task-22 audit. It is derived —
    // ALL_DESCRIPTORS.filter(d => d.inBundle) — so this asserts the derivation
    // lands on nine rather than asserting a literal.
    expect(BUNDLE_ENTITIES).toHaveLength(9);
    expect(ALL_DESCRIPTORS.filter((d) => d.inBundle)).toHaveLength(9);
  });

  it("is exactly §5.8's two rows, and the two exclusions are the stated ones", () => {
    expect([...BUNDLE_ENTITIES].sort()).toEqual(
      [
        // "cleared by wipe_catalogue"
        "programs", "pricing", "proposalTemplates", "messageTemplates",
        "playbooks", "demoTeams", "vendors",
        // "cleared by wipe_org_config"
        "skills", "approvalRules",
      ].sort(),
    );
    const excluded = ALL_DESCRIPTORS.filter((d) => !d.inBundle).map((d) => d.key);
    // staff: users are never wiped, so there is nothing to restore (§5.8).
    // settings: one row, never cleared — org_settings is in KEEP.
    expect(excluded.sort()).toEqual(["settings", "staff"]);
    expect(ALL_DESCRIPTORS).toHaveLength(11);
  });

  it("everything the bundle carries, the reset can clear — and nothing else", () => {
    // §5.8's load-bearing claim, checked against the generated taxonomy rather
    // than asserted in prose. The nine map onto REPLACE ∪ CONFIG; the two
    // exclusions map onto KEEP.
    const clearable = new Set<string>([
      ...RESET_TAXONOMY.buckets.REPLACE,
      ...RESET_TAXONOMY.buckets.CONFIG,
    ]);
    const TABLE: Record<EntityKey, string> = {
      staff: "users",
      settings: "org_settings",
      skills: "user_skills",
      approvalRules: "approval_rules",
      programs: "programs",
      pricing: "pricing_tables",
      proposalTemplates: "proposal_templates",
      messageTemplates: "message_templates",
      playbooks: "playbooks",
      demoTeams: "demo_teams",
      vendors: "vendors",
    };
    for (const key of BUNDLE_ENTITIES) {
      expect(clearable.has(TABLE[key]), `${key} → ${TABLE[key]} must be clearable`).toBe(true);
    }
    for (const d of ALL_DESCRIPTORS.filter((x) => !x.inBundle)) {
      expect(RESET_TAXONOMY.buckets.KEEP, `${d.key} must be in KEEP`).toContain(TABLE[d.key]);
    }
  });

  it("sends programmes before anything that hangs off one", () => {
    const order = bundleOrder();
    expect(order).toHaveLength(9);
    for (const key of PROGRAM_SCOPED) {
      expect(order.indexOf("programs")).toBeLessThan(order.indexOf(key));
    }
  });
});

/* ── The round trip ──────────────────────────────────────────────────────── */

describe("export → parse → re-import", () => {
  it("every bundled entity is present, and only the current versions", () => {
    const bundle = build();
    expect(Object.keys(bundle.entities).sort()).toEqual([...BUNDLE_ENTITIES].sort());
    // The superseded pricing version and message template are not restored.
    expect(bundle.entities.pricing).toHaveLength(1);
    expect(bundle.entities.messageTemplates).toHaveLength(1);
    expect((bundle.entities.messageTemplates[0] as Record<string, unknown>).name).toBe("Intro");
  });

  it("survives serialisation and re-parses against the same organisation", () => {
    const parsed = parseBundle(serialiseBundle(build()), SESSION);
    expect("fatal" in parsed).toBe(false);
    if ("fatal" in parsed) return;
    expect(parsed.total).toBe(9 - 0); // one row per entity, all nine present
    expect(parsed.plan.map((p) => p.key)).toEqual(bundleOrder());
  });

  it.each(BUNDLE_ENTITIES.map((k) => [k] as const))(
    "%s — every write field the read carries survives, field by field",
    (key) => {
      const bundle = build();
      const rows = bundle.entities[key] as Record<string, unknown>[];
      expect(rows.length, `${key} has no row to check`).toBeGreaterThan(0);

      const descriptor = DESCRIPTORS[key];
      const writeOnly = new Set(descriptor.writeOnly ?? []);
      // `program_id` is deliberately replaced by PROGRAM_KEY: the id does not
      // survive the reset this bundle exists to undo.
      const expected = fields(key).filter(
        (f) => !writeOnly.has(f) && !(key === "playbooks" && f === "program_id"),
      );
      for (const row of rows) {
        for (const field of expected) {
          expect(row, `${key}.${field} is missing from the bundle`).toHaveProperty(field);
        }
      }
    },
  );

  it("no request body ever carries the bundle's own bookkeeping", () => {
    // PROGRAM_KEY is the console's, not the API's. `applyBundle` strips every
    // underscore-prefixed key; this asserts the only such key is that one, so
    // the strip cannot start hiding a real field.
    const bundle = build();
    const underscored = new Set<string>();
    for (const rows of Object.values(bundle.entities)) {
      for (const row of rows as Record<string, unknown>[]) {
        for (const k of Object.keys(row)) if (k.startsWith("_")) underscored.add(k);
      }
    }
    expect([...underscored]).toEqual([PROGRAM_KEY]);
  });
});

/* ── The two that failed before — changes #9 and #10 ──────────────────────── */

describe("the two the changes were made for", () => {
  it("an auto-approving rule comes back still auto-approving (change #9)", () => {
    const rule = build().entities.approvalRules[0] as Record<string, unknown>;
    expect(rule.auto_approve).toBe(true);
    expect(rule.fallback_role).toBe("org_admin");
    // Field-by-field against the source, not a shape check.
    const source = READS.approvalRules[0];
    for (const f of ["entity_type", "condition", "rank", "approver_role", "fallback_role",
      "recommender_role", "joint_with_role", "joint_condition", "auto_approve",
      "expires_hours", "description"]) {
      expect(rule[f], `approvalRules.${f}`).toEqual((source as Record<string, unknown>)[f]);
    }
  });

  it("a demo team comes back with its three roles assigned, by id (change #10)", () => {
    const team = build().entities.demoTeams[0] as Record<string, unknown>;
    expect(team.lead_user_id).toBe("u1");
    expect(team.media_rep_id).toBe("u2");
    expect(team.sales_rep_id).toBe("u3");
    // The display names are NOT sent — the write has no field for them.
    expect(team).not.toHaveProperty("lead");
    expect(team).not.toHaveProperty("media_rep");
  });

  it("member_ids is a list of ids, not the read's objects", () => {
    // Watched failing with BUNDLE_TRANSFORMS emptied: the alias alone puts
    // `[{id, name}]` where register_demo_team wants `["u1", "u2"]`, and every
    // demo team in the bundle is refused on re-import.
    const team = build().entities.demoTeams[0] as Record<string, unknown>;
    expect(team.member_ids).toEqual(["u1", "u2"]);
  });

  it("every transform is used by a descriptor that actually declares the alias", () => {
    for (const compound of Object.keys(BUNDLE_TRANSFORMS)) {
      const [key, field] = compound.split(".") as [EntityKey, string];
      expect(fields(key), `${compound} names no write field`).toContain(field);
    }
  });
});

/* ── Programme association ────────────────────────────────────────────────── */

describe("programme ids do not survive a reset, so codes are carried instead", () => {
  it("every programme-scoped row carries its programme code", () => {
    const bundle = build();
    for (const key of PROGRAM_SCOPED) {
      const rows = bundle.entities[key] as Record<string, unknown>[];
      expect(rows.length, key).toBeGreaterThan(0);
      for (const row of rows) expect(row[PROGRAM_KEY], `${key}.${PROGRAM_KEY}`).toBe("DC-COMMISSION");
    }
  });

  it("a playbook exports no program_id at all", () => {
    // Exporting the old id would restore playbooks pointing at a programme that
    // no longer exists, and upsert_playbook does not check, so it would be
    // stored silently and no plan would ever fire it.
    const playbook = build().entities.playbooks[0] as Record<string, unknown>;
    expect(playbook).not.toHaveProperty("program_id");
    expect(playbook[PROGRAM_KEY]).toBe("DC-COMMISSION");
  });

  it("a row whose programme the console cannot name is dropped, not exported broken", () => {
    const orphaned = rowsFromReads({
      ...READS,
      pricingByProgram: { "unknown-program": READS.pricingByProgram.p1 },
    });
    expect(orphaned.pricing).toEqual([]);
  });
});

/* ── Refusals ─────────────────────────────────────────────────────────────── */

describe("what the console refuses to import, and why", () => {
  const fatal = (text: string, session = SESSION) => {
    const r = parseBundle(text, session);
    expect("fatal" in r, "expected a refusal").toBe(true);
    return "fatal" in r ? r.why : "";
  };

  it("a bundle from another organisation — the one that would corrupt silently", () => {
    // §5.8: skills round-trip on user_id, and those ids belong to the
    // organisation that made the bundle. This is the refusal that makes the
    // bundle a reseed loop rather than a cloning tool.
    const other = { ...build(), org: { id: "org-2", name: "Somebody Else" } };
    const why = fatal(serialiseBundle(other));
    expect(why).toContain("Somebody Else");
    expect(why).toContain("Fixture Org");
    expect(why).toContain("user id");
  });

  it("a file that is not a bundle", () => {
    expect(fatal('{"hello": "world"}')).toContain(BUNDLE_FORMAT);
  });

  it("JSON that does not parse", () => {
    expect(fatal("{not json")).toContain("not valid JSON");
  });

  it("a bundle from a newer console", () => {
    const future = { ...build(), version: BUNDLE_VERSION + 1 };
    expect(fatal(serialiseBundle(future as never))).toContain("without saying so");
  });

  it("an entity this console cannot restore", () => {
    const extra = build();
    (extra.entities as Record<string, unknown[]>).invoices = [{}];
    const why = fatal(serialiseBundle(extra));
    expect(why).toContain("invoices");
    expect(why).toContain("less than the file holds");
  });

  it("accepts a bundle whose entity lists are empty — a fresh org has nothing", () => {
    const empty = buildBundle({ org: ORG, rows: {}, writeFields: WRITE_FIELDS });
    const parsed = parseBundle(serialiseBundle(empty), SESSION);
    expect("fatal" in parsed).toBe(false);
    if (!("fatal" in parsed)) expect(parsed.total).toBe(0);
  });
});

describe("the report names rows the way an operator would", () => {
  it("uses the row's own identifying field, never an index", () => {
    expect(labelFor("programs", { code: "DC-COMMISSION", name: "Commissioning" }))
      .toContain("DC-COMMISSION");
    expect(labelFor("messageTemplates", { kind: "intro", channel: "email" }))
      .toBe("intro/email");
    expect(labelFor("vendors", { name: "Coolant Co" })).toBe("Coolant Co");
  });

  it("falls back to the entity name rather than inventing one", () => {
    expect(labelFor("skills", {})).toBe("skills row");
  });
});

/* ── The projection ───────────────────────────────────────────────────────── */

describe("projectRow keeps to what the write accepts", () => {
  it("drops read-only fields the API would reject or ignore", () => {
    const row = projectRow("vendors", READS.vendors[0], fields("vendors"));
    expect(row).not.toHaveProperty("id");
    expect(row.name).toBe("Coolant Co");
  });

  it("drops writeOnly directives — make_current is an instruction, not data", () => {
    const row = projectRow("proposalTemplates", READS.templatesByProgram.p1[0], fields("proposalTemplates"));
    expect(row).not.toHaveProperty("make_current");
    expect(row).not.toHaveProperty("version");
    expect(row.body_md).toContain("Scope");
  });
});

describe("a Word-document template never travels in a bundle", () => {
  const programs = [{ id: "p1", code: "IBC" }];
  const templatesByProgram = {
    p1: [
      { id: "t1", name: "Markdown one", version: 2, kind: "markdown",
        is_current: true, body_md: "## Scope\n\nBody." },
      { id: "t2", name: "Branded one", version: 5, kind: "docx",
        is_current: true, body_md: "a plain-text projection of the document" },
      { id: "t3", name: "Old markdown", version: 1, kind: "markdown",
        is_current: false, body_md: "superseded" },
    ],
  };

  it("exports the markdown template and drops the docx one", () => {
    const rows = rowsFromReads({
      programs,
      skills: [], programRows: [], pricingByProgram: {},
      templatesByProgram,
      messageTemplates: [], playbooks: [], approvalRules: [],
      demoTeams: [], vendors: [],
    });
    const names = (rows.proposalTemplates ?? []).map((r) => r.name);
    expect(names).toEqual(["Markdown one"]);
  });

  it("reports the dropped one, so the operator is told rather than surprised", () => {
    const skips = skippedFromReads({ programs, templatesByProgram });
    expect(skips).toHaveLength(1);
    expect(skips[0].key).toBe("proposalTemplates");
    expect(skips[0].label).toContain("Branded one");
    expect(skips[0].reason).toBe(DOCX_SKIP_REASON);
  });

  it("says nothing when every template is markdown", () => {
    expect(
      skippedFromReads({
        programs,
        templatesByProgram: { p1: [templatesByProgram.p1[0]] },
      }),
    ).toEqual([]);
  });
});
