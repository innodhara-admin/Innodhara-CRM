/**
 * The generated layer is only worth having if it is provably the backend's.
 *
 * This suite exists because of 07_BUILD_PLAN.md P2: openapi-zod-client silently
 * drops every constraint declared inside an `anyOf` branch, which is how
 * FastAPI renders every optional field. A console that trusted `generated.ts`
 * alone would let an operator type an `audio_retention_days` of 99999 with no
 * client-side complaint, and — far worse — would let a descriptor label that
 * rule `ui-only` ("the server accepts anything"), which is false.
 */
import { describe, expect, it } from "vitest";

import spec from "./openapi.json";
import { schemas } from "./generated";
import { CONSTRAINTS, DROPPED_BY_GENERATOR } from "./constraints.generated";
import { APPROVAL_NO_RULE, VOCAB } from "./vocabularies.generated";

const CONSTRAINT_KEYS = [
  "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
  "minLength", "maxLength", "pattern", "minItems", "maxItems",
] as const;

type AnySchema = Record<string, any>;
const components = (spec as AnySchema).components.schemas as Record<string, AnySchema>;

function declaredDirectly(prop: AnySchema): string[] {
  return CONSTRAINT_KEYS.filter((k) => prop?.[k] !== undefined);
}

function declaredAnywhere(prop: AnySchema): string[] {
  const here = declaredDirectly(prop);
  const inBranches = (prop?.anyOf ?? []).flatMap(declaredDirectly);
  return [...new Set([...here, ...inBranches])];
}

describe("coverage", () => {
  it("exports every component schema the spec declares", () => {
    const missing = Object.keys(components).filter((n) => !(n in schemas));
    expect(missing).toEqual([]);
    expect(Object.keys(components).length).toBeGreaterThan(80);
  });

  it("names the schemas the console writes through", () => {
    // A rename in the backend turns into a failure here rather than a dead
    // import three tasks later.
    for (const name of [
      "CreateUserRequest", "UpdateUserRequest", "UserResponse", "SkillRequest",
      "ProgramRequest", "PricingRequest", "PricingItem", "ProposalTemplateRequest",
      "MessageTemplateRequest", "PlaybookRequest", "ApprovalRuleRequest",
      "DemoTeamRequest", "VendorRequest", "SettingsRequest", "ResetRequest",
      "CreateOrgRequest", "CreateOrgResponse", "LoginRequest", "LoginResponse",
      "MeResponse", "ChangePasswordRequest",
    ]) {
      expect(schemas, name).toHaveProperty(name);
    }
  });
});

describe("constraints", () => {
  it("carries every constraint in the spec, in generated.ts or in the lift", () => {
    // Whichever side holds a rule, one of them must. A rule in neither is a
    // server rule the console does not know about — which is how a form comes
    // to permit a value the API will reject, or worse, to caption it "the
    // server accepts anything".
    const missing: string[] = [];
    for (const [name, schema] of Object.entries(components)) {
      for (const [field, prop] of Object.entries(schema.properties ?? {})) {
        if (!declaredAnywhere(prop as AnySchema).length) continue;
        const survivesIntoZod = declaredDirectly(prop as AnySchema).length > 0;
        const lifted = (CONSTRAINTS as AnySchema)[name]?.[field];
        if (!survivesIntoZod && !lifted) missing.push(`${name}.${field}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it("lifts every constraint the generator is known to drop", () => {
    // Named explicitly. The test above only asserts "one side has it", so a
    // lift that regressed to {} would still pass it as long as the zod side
    // held — and for these fields the zod side never does.
    const dropped = DROPPED_BY_GENERATOR as AnySchema;
    expect(dropped.SettingsRequest.assignment_mode.pattern)
      .toBe("^(auto|lead_confirm)$");
    expect(dropped.SettingsRequest.ai_confidence_threshold)
      .toEqual({ minimum: 0, maximum: 1 });
    expect(dropped.CreateUserRequest.max_open_tasks)
      .toEqual({ minimum: 1, maximum: 100 });
    expect(dropped.UpdateUserRequest.max_open_tasks)
      .toEqual({ minimum: 1, maximum: 100 });

    // 14 SettingsRequest dials carry a bound or pattern that only the lift
    // knows about. Recomputed from the spec rather than hard-coded, so this
    // tracks a backend that adds a fifteenth instead of going stale.
    const expectedSettings = Object.entries(
      components.SettingsRequest.properties as Record<string, AnySchema>,
    ).filter(([, p]) => !declaredDirectly(p).length && declaredAnywhere(p).length)
     .map(([f]) => f);
    expect(Object.keys(dropped.SettingsRequest).sort())
      .toEqual(expectedSettings.sort());
    expect(expectedSettings).toHaveLength(14);
  });

  it("proves the drop is real, not a theory about the generator", () => {
    // P2 asserted as behaviour. If a future generator version starts carrying
    // anyOf constraints, THIS test fails — and that is the signal to simplify
    // the descriptor layer back to two enforcement values, not a nuisance.
    const settings = schemas.SettingsRequest as AnySchema;
    expect(settings.safeParse({ assignment_mode: "nonsense" }).success).toBe(true);
    expect(settings.safeParse({ audio_retention_days: 99999 }).success).toBe(true);
    expect(settings.safeParse({ workday_start: "not a time" }).success).toBe(true);

    // ...while a constraint declared directly on a required field does survive,
    // which is why the enforcement split is per-field and not per-schema.
    const program = schemas.ProgramRequest as AnySchema;
    expect(program.safeParse({ name: "x", code: "C".repeat(51) }).success).toBe(false);
    expect(program.safeParse({ name: "x", code: "DC" }).success).toBe(true);
  });

  it("keeps the default_quantity tri-state on the wire", () => {
    // 06_DESIGN.md §3.3: null means "this org did not say how many", which is
    // not the same as 1. If the generator ever emits a .default(1) here, the
    // console's checkbox-plus-number control becomes a lie.
    const item = schemas.PricingItem as AnySchema;
    expect(item.parse({ code: "A", label: "A", unit_price: 1 }).default_quantity)
      .toBeUndefined();
    expect(item.parse({ code: "A", label: "A", unit_price: 1, default_quantity: null })
      .default_quantity).toBeNull();
    expect(item.parse({ code: "A", label: "A", unit_price: 1, default_quantity: 1 })
      .default_quantity).toBe(1);
  });
});

describe("vocabularies", () => {
  it("carries the handler-enforced lists OpenAPI cannot express", () => {
    expect(VOCAB.department).toEqual(["sales", "operations", "accounts"]);
    expect(VOCAB.template_kind).toEqual(["intro", "follow_up"]);
    expect(VOCAB.message_channel).toEqual(["email", "whatsapp"]);
    expect(VOCAB.skill_level.length).toBeGreaterThan(0);
    expect(VOCAB.phase.length).toBeGreaterThan(0);
  });

  it("excludes super_admin from the roles the console can assign", () => {
    // D1 / Q14: get_org_context rejects super_admin permanently, and
    // register_staff refuses any role outside ORG_ROLES. A staff form offering
    // it would produce a 422 the operator cannot act on.
    expect(VOCAB.org_role).not.toContain("super_admin");
    expect(VOCAB.role).toContain("super_admin");
    expect(VOCAB.org_role.length).toBe(VOCAB.role.length - 1);
  });

  it("carries what an unmatched approval falls back to, per entity type", () => {
    // Task 23 check 4 states the COST of a missing catch-all rule, and the cost
    // differs per entity type: `proposals.py` passes default_approver_role=None
    // (the proposal is applied unreviewed) while every outbound_message path
    // passes sales_lead. None of that is in openapi.json — it is nine call
    // sites in the engines — so the dumper AST-walks app/ for it.
    const entries = Object.entries(APPROVAL_NO_RULE);
    expect(entries.length).toBeGreaterThan(0);
    for (const [, v] of entries) {
      // A type with call sites must say where they fall, and one with none
      // must say nothing — a stubbed table would break one of these.
      expect(v.fallsTo.length > 0).toBe(v.callSites > 0);
    }
  });

  it("keeps BOTH kinds of fallback, which is the only reason it is worth generating", () => {
    // If every entity type fell back the same way, check 4 could say one
    // sentence and this table would be dead weight. It does not: at least one
    // type is applied with nobody asked, and at least one still reaches a role.
    const falls = Object.values(APPROVAL_NO_RULE).flatMap((v) => [...v.fallsTo]);
    expect(falls).toContain(null);
    expect(falls.some((r) => typeof r === "string")).toBe(true);
  });

  it("names only roles the console knows", () => {
    for (const v of Object.values(APPROVAL_NO_RULE)) {
      for (const role of v.fallsTo) {
        if (role !== null) expect(VOCAB.role).toContain(role);
      }
    }
  });

  it("is not constrained by the spec, which is the whole reason it exists", () => {
    // If `role` ever gains an enum in openapi.json, the generated schema can
    // carry it and this file becomes redundant — that is worth noticing.
    expect(components.CreateUserRequest.properties.role.enum).toBeUndefined();
    expect(components.CreateUserRequest.properties.department.enum).toBeUndefined();
  });
});
