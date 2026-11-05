/**
 * What the form will and will not send — 07_BUILD_PLAN.md Task 17 Step 1.
 *
 * The cases below are chosen for one property: **each is a value the server
 * would reject, that layer 1 alone lets through.** A suite that only checked
 * required-ness would pass against a form with no layers 2 or 3 at all, which
 * is exactly the form P2 warns about — one that silently permits values the
 * backend refuses and turns every mistake into a round trip.
 */
import { describe, expect, it } from "vitest";

import { CONSTRAINTS } from "../api/constraints.generated";
import { VOCAB } from "../api/vocabularies.generated";
import { DESCRIPTORS, ALL_DESCRIPTORS } from "../descriptors";
import { bodyFor, boundsFor, emptyRow, isBlank, validate } from "./entityValidation";

describe("layer 1 — the generated schema", () => {
  it("requires what the backend requires", () => {
    const errors = validate(DESCRIPTORS.staff, {});
    expect(Object.keys(errors).sort()).toEqual(["email", "name", "role"]);
  });

  it("accepts a complete row", () => {
    expect(
      validate(DESCRIPTORS.staff, {
        email: "ravi@example.com",
        name: "Ravi Menon",
        role: "operations_lead",
        department: "operations",
        max_open_tasks: 12,
      }),
    ).toEqual({});
  });
});

describe("layer 2 — the bounds the generator drops (P2)", () => {
  it("catches max_open_tasks out of range, which generated.ts does not carry", () => {
    // The proof this layer is doing work: the same row through the generated
    // schema alone is clean, because FastAPI renders the optional field as an
    // anyOf and openapi-zod-client discards the bounds inside it.
    const row = { email: "a@b.com", name: "Ravi", role: "sales_agent", max_open_tasks: 500 };
    expect(validate(DESCRIPTORS.staff, row).max_open_tasks).toBe(
      "At most 100 (admin.py · CreateUserRequest)",
    );
  });

  it("names the handler in the message, not just the number", () => {
    // The operator needs to know whose rule this is: a ui-only message they can
    // reasonably override, a backend one they cannot.
    const message = validate(DESCRIPTORS.staff, {
      email: "a@b.com",
      name: "Ravi",
      role: "sales_agent",
      max_open_tasks: 0,
    }).max_open_tasks;
    expect(message).toContain("At least 1");
    expect(message).toContain("admin.py");
  });

  it("reads every bound from the lift rather than from a literal", () => {
    // If the backend widens the range, this test moves with it and the
    // assertion above is the one that would need editing — which is the point.
    expect(boundsFor(DESCRIPTORS.staff, "max_open_tasks")).toEqual(
      CONSTRAINTS.CreateUserRequest.max_open_tasks,
    );
  });

  it("enforces the programme code length, which generated.ts DOES carry", () => {
    const errors = validate(DESCRIPTORS.programs, { name: "X", code: "C".repeat(51) });
    expect(errors.code).toBeDefined();
  });
});

describe("layer 3 — option lists and cross-field rules", () => {
  it("rejects a role outside VOCAB.org_role", () => {
    const errors = validate(DESCRIPTORS.staff, {
      email: "a@b.com",
      name: "Ravi",
      role: "super_admin",
    });
    expect(errors.role).toContain("Must be one of");
    // A4: the list in the message is the generated one, never typed here.
    expect(errors.role).toContain(VOCAB.org_role.join(", "));
  });

  it("refuses an email message template with no subject", () => {
    const row = { kind: "intro", channel: "email", name: "Intro", body: "Hello there!" };
    expect(validate(DESCRIPTORS.messageTemplates, row).subject).toBe(
      "Email templates need a subject (admin.py · add_message_template)",
    );
  });

  it("does not demand a subject for WhatsApp", () => {
    const row = { kind: "intro", channel: "whatsapp", name: "Intro", body: "Hello there!" };
    expect(validate(DESCRIPTORS.messageTemplates, row)).toEqual({});
  });

  it("lets a suggestion list through, and still refuses a closed one", () => {
    // playbooks.phase is the one field whose options are suggestions: the
    // server takes any string, so refusing one here would be a rule this
    // console invented. The screen warns instead. skills.level looks identical
    // and is NOT a suggestion list, which is the contrast worth pinning.
    const suggestion = DESCRIPTORS.playbooks.fields.find((f) => f.field === "phase");
    expect(suggestion?.optionsAreSuggestions).toBe(true);
    expect(
      validate(DESCRIPTORS.playbooks, {
        program_id: "p1",
        phase: "handover",
        entries: [],
      }).phase,
    ).toBeUndefined();

    expect(DESCRIPTORS.skills.fields.find((f) => f.field === "level")?.optionsAreSuggestions)
      .toBeUndefined();
  });

  it("has exactly one suggestion list, so the exception stays an exception", () => {
    const suggestions = ALL_DESCRIPTORS.flatMap((d) =>
      d.fields.filter((f) => f.optionsAreSuggestions).map((f) => `${d.key}.${f.field}`),
    );
    expect(suggestions).toEqual(["playbooks.phase"]);
  });

  it("marks a ui-only rule as checked here only", () => {
    // skills.level is ui-only: ops.py stores whatever string it is sent. The
    // message must not imply the server would refuse it.
    const errors = validate(DESCRIPTORS.skills, {
      user_id: "u1",
      skill: "rack-and-stack",
      level: "wizard",
    });
    expect(errors.level).toContain("checked here only");
  });
});

describe("the body that actually goes on the wire", () => {
  it("drops blanks rather than sending empty strings", () => {
    // Empty string is not null anywhere in this API, and an optional field sent
    // as "" is a written value, not an absent one.
    const body = bodyFor(DESCRIPTORS.staff, {
      email: "a@b.com",
      name: "Ravi",
      role: "sales_agent",
      department: "",
      phone: "",
      max_open_tasks: "",
    });
    expect(body).toEqual({ email: "a@b.com", name: "Ravi", role: "sales_agent" });
  });

  it("carries writeOnly directives, which are not descriptor fields", () => {
    const body = bodyFor(DESCRIPTORS.proposalTemplates, {
      name: "Standard",
      body_md: "#".repeat(30),
      make_current: true,
    });
    expect(body.make_current).toBe(true);
  });

  it("never invents a key the descriptor does not declare (P9)", () => {
    // Everything the generator emits is .passthrough(), so an unknown key
    // validates clean and is then silently ignored by the server. The form must
    // not be the thing that introduces one.
    const body = bodyFor(DESCRIPTORS.programs, {
      name: "X",
      code: "X",
      description: "d",
      unit_pirce: 10,
    });
    expect(Object.keys(body).sort()).toEqual(["code", "description", "name"]);
  });

  it("sends nothing at all for an untouched form", () => {
    // The regression this pins, found in a browser: `EntityForm` validated
    // `bodyFor(values)` and then posted `values`. An untouched `working_days`
    // box is `""` in the form state, and the server answered
    //   working_days: Input should be a valid list
    // for a field the operator had never seen. What is checked and what is sent
    // have to be the same object.
    for (const d of ALL_DESCRIPTORS) {
      // Checkboxes are the one exception, and they are not an oversight: an
      // unchecked box is a real `false`, not an absent value, and dropping it
      // would make "the operator said no" indistinguishable from "the operator
      // did not reach this field". `approvalRules.auto_approve` is the only
      // one today. Everything else must be absent.
      const checkboxes = d.fields.filter((f) => f.control === "checkbox").map((f) => f.field);
      expect(Object.keys(bodyFor(d, emptyRow(d))).sort(), d.key).toEqual(checkboxes.sort());
    }
  });

  it("drops a blank list field rather than sending an empty string", () => {
    const body = bodyFor(DESCRIPTORS.staff, {
      ...emptyRow(DESCRIPTORS.staff),
      email: "a@b.com",
      name: "Asha Rao",
      role: "sales_agent",
    });
    expect("working_days" in body).toBe(false);
    expect("phone" in body).toBe(false);
  });

  it("treats null, undefined and empty string as blank — and 0 and false as values", () => {
    expect([null, undefined, ""].every(isBlank)).toBe(true);
    expect([0, false, "0"].some(isBlank)).toBe(false);
  });
});

describe("every descriptor can drive a form", () => {
  it("produces a starting row whose keys are exactly its fields", () => {
    for (const d of ALL_DESCRIPTORS) {
      expect(Object.keys(emptyRow(d)).sort(), d.key).toEqual(
        d.fields.map((f) => f.field).sort(),
      );
    }
  });

  it("has no descriptor whose empty row already validates clean", () => {
    // A descriptor with nothing required would give a form that posts an empty
    // body on first click. `settings` is the one legitimate case: every dial is
    // optional because PATCH applies exclude_none.
    const permissive = ALL_DESCRIPTORS.filter(
      (d) => Object.keys(validate(d, emptyRow(d))).length === 0,
    ).map((d) => d.key);
    expect(permissive).toEqual(["settings"]);
  });

  it("attributes every cross-field rule to somebody", () => {
    for (const d of ALL_DESCRIPTORS) {
      for (const rule of d.crossFieldRules ?? []) {
        expect(rule.says.length, `${d.key}.${rule.field}`).toBeGreaterThan(10);
        expect(d.fields.some((f) => f.field === rule.field), rule.field).toBe(true);
      }
    }
  });
});
