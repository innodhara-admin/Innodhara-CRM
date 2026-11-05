/**
 * The go-live check — 07_BUILD_PLAN.md Task 23 Step 7.
 *
 * Table-driven over the **Task 15 fixtures**, for the reason `status.test.ts`
 * gives: payloads a real backend produced, parsed through the read shapes that
 * guard them. A check tested against invented payloads proves that the function
 * agrees with its author.
 *
 * The four cases the plan names each have a test that was **watched failing**
 * against the derivation without the behaviour, and each says so where it is
 * not obvious.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { schemas } from "../api/generated";
import { EmailTemplatesRead, READS } from "../api/reads";
import { APPROVAL_NO_RULE, VOCAB } from "../api/vocabularies.generated";
import { runGoLive, type Check } from "./golive";
import { PENDING_READS, type ChecklistReads, type Read } from "./status";

const FIXTURES = join(dirname(dirname(fileURLToPath(import.meta.url))), "api", "__fixtures__");
const raw = (name: string): unknown =>
  JSON.parse(readFileSync(join(FIXTURES, `${name}.json`), "utf-8"));

const ok = <T>(value: T): Read<T> => ({ state: "ok", value });

const me = schemas.MeResponse.parse(raw("me"));
const staff = schemas.UserResponse.array().parse(raw("staff"));
const skills = READS.skills.parse(raw("skills"));
const programs = READS.programs.parse(raw("programs"));
const pricing = READS.pricing.parse(raw("pricing"));
const proposalTemplates = READS.proposalTemplates.parse(raw("proposalTemplates"));
const messageTemplates = READS.messageTemplates.parse(raw("messageTemplates"));

/** One current Word email template, through the shape that guards the read. */
const emailTemplates = EmailTemplatesRead.parse([
  {
    id: "e1", template_type: "common", category: "follow_up",
    category_label: "Follow-up", program_id: null, program_name: null,
    name: "No reply follow-up", when_to_use: null, version: 1, is_current: true,
    built_document: "none", subject: "Innovation learning for <School Name>",
    filename: "No reply follow-up.docx", tags: 10, always_asked: 3,
    distinct: [], leftover_blanks: [], attachments: [],
  },
]);
const playbooks = READS.playbooks.parse(raw("playbooks"));
const approvalRules = READS.approvalRules.parse(raw("approvalRules"));
const settings = READS.settings.parse(raw("settings"));
const demoTeams = READS.demoTeams.parse(raw("demoTeams"));
const vendors = READS.vendors.parse(raw("vendors"));

const PROGRAM_ID = programs[0].id;
/** Ravi Menon, the fixture's operations lead — the only skill holder. */
const HOLDER = skills[0].user_id;
/** The skill the fixture playbook's one entry asks for. */
const SKILL = skills[0].skill;

const SEEDED: ChecklistReads = {
  me: ok(me),
  staff: ok(staff),
  skills: ok(skills),
  programs: ok(programs),
  pricing: ok({ [PROGRAM_ID]: pricing }),
  proposalTemplates: ok({ [PROGRAM_ID]: proposalTemplates }),
  messageTemplates: ok(messageTemplates),
  emailTemplates: ok(emailTemplates),
  playbooks: ok(playbooks),
  approvalRules: ok(approvalRules),
  settings: ok(settings),
  demoTeams: ok(demoTeams),
  vendors: ok(vendors),
};

const with_ = (over: Partial<ChecklistReads>): ChecklistReads => ({ ...SEEDED, ...over });

const check = (n: number, reads = SEEDED, session = {}): Check =>
  runGoLive(reads, session).find((c) => c.n === n)!;

// The fixtures were captured from an organisation seeded one row deep, so it is
// genuinely incomplete: one programme, one playbook covering one of six phases.
describe("the fixture organisation, as captured", () => {
  it("runs all six checks in §5.6's order", () => {
    const checks = runGoLive(SEEDED);
    expect(checks.map((c) => c.n)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(checks.map((c) => c.id)).toEqual([
      "skill-coverage",
      "program-completeness",
      "message-templates",
      "approval-ordering",
      "delivery-honesty",
      "domain",
    ]);
  });

  it("covers the one skill its playbook asks for", () => {
    const c = check(1);
    expect(c.marker).toBe("done");
    expect(c.rows).toHaveLength(1);
    expect(c.rows[0].subject).toBe(SKILL);
    expect(c.rows[0].detail).toContain("Ravi Menon");
  });

  it("has all four message templates", () => {
    expect(check(3).marker).toBe("done");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 1 · Skill coverage — the check that justifies the console
// ─────────────────────────────────────────────────────────────────────────────

describe("check 1 · skill coverage", () => {
  /**
   * **The case the plan names, and the reason this is a join rather than a set
   * difference.** `GET /skills` still returns the row — the skill *looks* held —
   * and only `GET /admin/users` says the holder has gone. Watched failing
   * against a version that diffed the two lists directly: it reported `done`.
   */
  it("a skill only a deactivated user holds is UNCOVERED", () => {
    const c = check(
      1,
      with_({ staff: ok(staff.map((u) => (u.id === HOLDER ? { ...u, is_active: false } : u))) }),
    );
    expect(c.marker).toBe("none");
    expect(c.rows[0].subject).toBe(SKILL);
    expect(c.rows[0].detail).toContain("deactivated");
    expect(c.rows[0].detail).toContain("Ravi Menon");
    // The whole point of the row: it says which definition of "covered" it used.
    expect(c.rows[0].detail).toContain("delete_skill");
  });

  it("matches ops.py · delete_skill: one active holder is enough, level ignored", () => {
    // delete_skill counts `UserSkill` rows joined to an ACTIVE user and looks at
    // no other column — not `level`, not role. A `basic` holder is coverage.
    const c = check(
      1,
      with_({ skills: ok(skills.map((s) => ({ ...s, level: "basic" }))) }),
    );
    expect(c.marker).toBe("done");
  });

  it("a skill nobody holds at all is uncovered, and says so differently", () => {
    const c = check(1, with_({ skills: ok([]) }));
    expect(c.marker).toBe("none");
    expect(c.rows[0].detail).toContain("nobody holds it");
    expect(c.rows[0].detail).not.toContain("deactivated");
  });

  it("names the phases that ask for the skill, not just that it is asked for", () => {
    expect(check(1).rows[0].detail).toContain(playbooks[0].phase);
  });

  it("ignores superseded playbook versions", () => {
    // `is_current` is what `phase_shift` loads. A retired v1 asking for a skill
    // nobody holds is not a live gap.
    const stale = playbooks.map((p) => ({
      ...p,
      is_current: false,
      entries: [{ ...p.entries[0], required_skill: "nobody-has-this" }],
    }));
    const c = check(1, with_({ playbooks: ok(stale) }));
    expect(c.marker).toBe("none");
    expect(c.summary).toContain("no current playbook");
    expect(c.rows).toHaveLength(0);
  });

  it("counts an entry with no required_skill, which routes the same way", () => {
    const noSkill = playbooks.map((p) => ({
      ...p,
      entries: [...p.entries, { title: "Send the kickoff note", offset_days: 0 }],
    }));
    const c = check(1, with_({ playbooks: ok(noSkill) }));
    expect(c.marker).toBe("none");
    const row = c.rows.find((r) => r.subject === "(no skill named)")!;
    expect(row.detail).toContain("1 playbook entry of 2");
    expect(row.detail).toContain("phase lead");
  });

  it("a playbook whose entries name no skill at all is not vacuously satisfied", () => {
    const blank = playbooks.map((p) => ({ ...p, entries: [] }));
    const c = check(1, with_({ playbooks: ok(blank) }));
    expect(c.marker).toBe("none");
    expect(c.summary).toContain("not one entry names a skill");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 2 · Programme completeness
// ─────────────────────────────────────────────────────────────────────────────

describe("check 2 · programme completeness", () => {
  it("a programme missing its pricing is ○, and the row says which is missing", () => {
    const c = check(2, with_({ pricing: ok({ [PROGRAM_ID]: [] }) }));
    expect(c.marker).toBe("none");
    expect(c.rows[0].subject).toBe(programs[0].code);
    expect(c.rows[0].detail).toContain("no current rate card");
    expect(c.rows[0].detail).not.toContain("proposal template");
  });

  it("a superseded rate card is not a current one", () => {
    const old = pricing.map((v) => ({ ...v, is_current: false }));
    expect(check(2, with_({ pricing: ok({ [PROGRAM_ID]: old }) })).marker).toBe("none");
  });

  it("missing playbook phases are ◐, not ○ — the AI derives the wave instead", () => {
    // The fixture has one playbook, for one of the six phases.
    const c = check(2);
    expect(c.marker).toBe("partial");
    expect(c.rows[0].detail).toContain("derived from scratch by the AI");
    for (const phase of VOCAB.phase.filter((p) => p !== playbooks[0].phase)) {
      expect(c.rows[0].detail).toContain(phase);
    }
  });

  it("is ● only when all six phases have a current playbook", () => {
    const all = VOCAB.phase.map((phase, i) => ({ ...playbooks[0], id: `pb${i}`, phase }));
    const c = check(2, with_({ playbooks: ok(all) }));
    expect(c.marker).toBe("done");
    expect(c.rows[0].detail).toContain(`all ${VOCAB.phase.length} phases`);
  });

  it("an inactive programme is not a gap", () => {
    const c = check(2, with_({ programs: ok(programs.map((p) => ({ ...p, is_active: false }))) }));
    expect(c.marker).toBe("none");
    expect(c.summary).toContain("item 4 comes first");
    expect(c.rows).toHaveLength(0);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 3 · Message templates
// ─────────────────────────────────────────────────────────────────────────────

describe("check 3 · message templates", () => {
  it("three of four is ◐ with the missing combination named", () => {
    const three = messageTemplates.filter(
      (t) => !(t.kind === "follow_up" && t.channel === "whatsapp"),
    );
    const c = check(3, with_({ messageTemplates: ok(three) }));
    expect(c.marker).toBe("none"); // the missing ROW is ○; see below
    expect(c.summary).toBe("3 of 4 needed templates are in place");
    const missing = c.rows.find((r) => r.subject === "follow_up/whatsapp")!;
    expect(missing.marker).toBe("none");
    expect(missing.detail).toBe("no current template");
    expect(c.rows.filter((r) => r.marker === "done")).toHaveLength(3);
  });

  it("names the three old templates still in use, then the Word email templates", () => {
    // 28 Oct 2026: the card scan uses intro/email and intro/whatsapp, WhatsApp
    // follow-ups use follow_up/whatsapp; email follow-ups use Word templates.
    expect(check(3).rows.map((r) => r.subject)).toEqual([
      "intro/email",
      "intro/whatsapp",
      "follow_up/whatsapp",
      "Word email templates",
    ]);
  });

  it("no Word email template leaves that row open", () => {
    const c = check(3, with_({ emailTemplates: ok([]) }));
    const row = c.rows.find((r) => r.subject === "Word email templates")!;
    expect(row.marker).toBe("none");
    expect(row.detail).toBe("none published");
  });

  it("the old follow_up/email template is no longer needed", () => {
    const c = check(3, with_({
      messageTemplates: ok(
        messageTemplates.filter((t) => !(t.kind === "follow_up" && t.channel === "email")),
      ),
    }));
    expect(c.marker).toBe("done");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 4 · Approval rule ordering
// ─────────────────────────────────────────────────────────────────────────────

describe("check 4 · approval rule ordering", () => {
  it("an entity type with rules but no catch-all is flagged", () => {
    const noCatchAll = approvalRules.filter((r) => Object.keys(r.condition).length > 0);
    const c = check(4, with_({ approvalRules: ok(noCatchAll) }));
    const row = c.rows.find((r) => r.subject === "proposal")!;
    expect(row.detail).toContain("no catch-all {} rule");
    expect(row.marker).toBe("none");
  });

  it("says what a missing catch-all COSTS, per entity type, from the generated table", () => {
    // The whole reason APPROVAL_NO_RULE is generated: the cost is not the same
    // for every type. `proposals.py` passes default_approver_role=None, so a
    // proposal matching no rule is applied with nobody looking; an
    // outbound_message falls to the sales lead.
    expect(APPROVAL_NO_RULE.proposal.fallsTo).toContain(null);
    expect(APPROVAL_NO_RULE.outbound_message.fallsTo).toEqual(["sales_lead"]);

    const c = check(4, with_({ approvalRules: ok([]) }));
    const proposal = c.rows.find((r) => r.subject === "proposal")!;
    const message = c.rows.find((r) => r.subject === "outbound_message")!;
    expect(proposal.detail).toContain("applied unreviewed");
    expect(proposal.marker).toBe("none");
    expect(message.detail).toContain("falls to sales_lead");
    expect(message.marker).toBe("partial");
  });

  it("reports an entity type the backend never requests an approval for", () => {
    // `invoice` is in ApprovalEntityType and has zero call sites — rules for it
    // are dead configuration. This was watched failing: a well-ranked invoice
    // rule *with* a catch-all reported ● and read as the healthiest row on the
    // sheet, which is how dead config survives a review.
    expect(APPROVAL_NO_RULE.invoice.callSites).toBe(0);
    const withInvoice = [...approvalRules, { ...approvalRules[1], id: "inv", entity_type: "invoice" }];
    const c = check(4, with_({ approvalRules: ok(withInvoice) }));
    const row = c.rows.find((r) => r.subject === "invoice")!;
    expect(row.marker).toBe("partial");
    expect(row.detail).toContain("never fire");
  });

  it("flags rules ranked after a catch-all, which can never fire", () => {
    // find_rule orders by rank and returns the FIRST match; an empty condition
    // matches everything. Watched failing against a version that only checked
    // for a catch-all's existence: it reported ●.
    const shadowed = [
      { ...approvalRules[1], rank: 1 },                        // catch-all first
      { ...approvalRules[0], rank: 50 },                       // unreachable
    ];
    const c = check(4, with_({ approvalRules: ok(shadowed) }));
    const row = c.rows.find((r) => r.subject === "proposal")!;
    expect(row.marker).toBe("partial");
    expect(row.detail).toContain("can never fire");
  });

  it("reports a rank tie rather than resolving it", () => {
    const tied = approvalRules.map((r) => ({ ...r, rank: 10 }));
    const c = check(4, with_({ approvalRules: ok(tied) }));
    const row = c.rows.find((r) => r.subject.endsWith("rank tie"))!;
    expect(row.detail).toContain("created_at");
    expect(row.detail).toContain("not");
  });

  it("lists every auto_approve rule explicitly", () => {
    const auto = approvalRules.map((r, i) => (i === 0 ? { ...r, auto_approve: true } : r));
    const c = check(4, with_({ approvalRules: ok(auto) }));
    const row = c.rows.find((r) => r.detail.includes("auto_approve"))!;
    expect(row.subject).toContain(`rank ${approvalRules[0].rank}`);
    expect(row.marker).toBe("partial");
    expect(c.summary).toContain("listed here for sign-off rather than as a fault");
  });

  it("names the fallback approver alongside the primary (change #9)", () => {
    const row = check(4).rows.find((r) => r.subject === "proposal")!;
    expect(row.detail).toContain(
      `${approvalRules[0].approver_role} (else ${approvalRules[0].fallback_role})`,
    );
    // The rank and the condition's threshold are both numbers and must be
    // separately labelled — "10 when discount_pct_gt" was two tens on one line.
    expect(row.detail).toContain("rank 10 · when discount_pct_gt=10 →");
    // The catch-all names no fallback and must not invent one.
    expect(row.detail).toContain(
      `{} (matches everything) → ${approvalRules[1].approver_role}`,
    );
    expect(row.detail).not.toContain(`${approvalRules[1].approver_role} (else`);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 5 · Delivery honesty
// ─────────────────────────────────────────────────────────────────────────────

describe("check 5 · delivery honesty", () => {
  const settingsWith = (over: Partial<typeof settings>) => ok({ ...settings, ...over });

  it("is never ● on dry_run, however the credentials look", () => {
    const c = check(
      5,
      with_({
        settings: settingsWith({
          email_mode: "dry_run",
          email_credentials_stored: true,
          calendar_mode: "google",
          calendar_credentials_stored: true,
        }),
      }),
    );
    const email = c.rows.find((r) => r.subject === "email")!;
    expect(email.marker).toBe("partial");
    expect(email.detail).toContain("EMAIL_MODE=dry_run");
    expect(c.marker).toBe("partial");
  });

  it("is ● only when both channels have credentials and a live mode", () => {
    const c = check(
      5,
      with_({
        settings: settingsWith({
          email_mode: "smtp",
          email_credentials_stored: true,
          calendar_mode: "google",
          calendar_credentials_stored: true,
        }),
      }),
    );
    expect(c.marker).toBe("done");
    expect(c.summary).toContain("both live");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 6 · Domain check (P7 / A6)
// ─────────────────────────────────────────────────────────────────────────────

describe("check 6 · the domain, and which source answered it", () => {
  const DOMAIN = staff[0].email.split("@")[1];

  it("uses the domain POST /orgs returned when this tab has it, and says so", () => {
    const c = check(6, SEEDED, { emailDomain: DOMAIN });
    expect(c.marker).toBe("done");
    expect(c.source).toContain("POST /orgs");
    expect(c.rows).toHaveLength(0);
  });

  it("strips a leading @ before comparing (F34)", () => {
    // The column is stored `lstrip("@").lower()`; a stored "@domain" once built
    // "@@domain" and made adding staff impossible.
    expect(check(6, SEEDED, { emailDomain: `@${DOMAIN}` }).marker).toBe("done");
  });

  it("flags an address outside the stated domain", () => {
    const outsider = { ...staff[0], id: "outsider", email: "ravi@elsewhere.example" };
    const c = check(6, with_({ staff: ok([...staff, outsider]) }), { emailDomain: DOMAIN });
    expect(c.marker).toBe("none");
    expect(c.rows).toHaveLength(1);
    expect(c.rows[0].subject).toBe("ravi@elsewhere.example");
  });

  it("says why the ADMINISTRATOR is the one account allowed to differ", () => {
    // POST /orgs writes the admin user with no domain test — only
    // register_staff applies one. Grepped, not assumed.
    const admin = staff.find((u) => u.role === "org_admin")!;
    const c = check(
      6,
      with_({ staff: ok(staff.map((u) => (u.id === admin.id ? { ...u, email: "boss@other.example" } : u))) }),
      { emailDomain: DOMAIN },
    );
    expect(c.rows[0].detail).toContain("POST /orgs");
    expect(c.rows[0].detail).toContain("register_staff");
  });

  it("falls back to the staff addresses, and can never be ● that way", () => {
    const c = check(6);
    expect(c.marker).toBe("partial");
    expect(c.source).toContain("the staff addresses themselves");
    expect(c.summary).toContain("not readable from this session");
  });

  it("more than one distinct domain is itself the finding", () => {
    const outsider = { ...staff[0], id: "outsider", email: "ravi@elsewhere.example" };
    const c = check(6, with_({ staff: ok([...staff, outsider]) }));
    expect(c.marker).toBe("none");
    expect(c.summary).toContain("2 distinct domains");
    expect(c.rows.map((r) => r.subject).sort()).toEqual([
      "@elsewhere.example",
      `@${DOMAIN}`,
    ].sort());
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// The two failure directions, kept apart (§6 / A1)
// ─────────────────────────────────────────────────────────────────────────────

describe("a read that has not arrived is never a verdict", () => {
  it("every check is `pending` while nothing has loaded", () => {
    const checks = runGoLive(PENDING_READS);
    expect(checks).toHaveLength(6);
    for (const c of checks) {
      expect(c.marker).toBe("pending");
      expect(c.rows).toHaveLength(0);
    }
  });

  it("a failed read is `—` with the server's own reason, never ○", () => {
    const why = "This endpoint is organisation-scoped";
    const c = check(1, with_({ skills: { state: "unreadable", why } }));
    expect(c.marker).toBe("blocked");
    expect(c.summary).toBe(why);
  });

  it("`unreadable` outranks `pending` — a failure is not 'still trying'", () => {
    const c = check(
      1,
      with_({ playbooks: { state: "pending" }, skills: { state: "unreadable", why: "boom" } }),
    );
    expect(c.marker).toBe("blocked");
    expect(c.summary).toBe("boom");
  });
});

describe("purity", () => {
  it("same reads in, same checks out", () => {
    expect(runGoLive(SEEDED, { emailDomain: "x.example" })).toEqual(
      runGoLive(SEEDED, { emailDomain: "x.example" }),
    );
  });

  it("does not mutate the reads it is given", () => {
    const before = JSON.stringify(SEEDED);
    runGoLive(SEEDED);
    expect(JSON.stringify(SEEDED)).toBe(before);
  });
});
