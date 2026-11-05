/**
 * Status derivation — 07_BUILD_PLAN.md Task 16 Step 3.
 *
 * Table-driven, and the table's inputs are the **Task 15 fixtures**: payloads a
 * real backend produced, parsed through the read shapes that guard them. A
 * derivation tested against invented payloads proves that the function agrees
 * with the test author, which is not the claim being made.
 *
 * The fixture organisation happens to be a genuinely partial one — two active
 * accounts of which one has no department, and one of the two holding a skill —
 * so items 2 and 3 exercise `◐` against real data rather than a constructed
 * edge case.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { schemas } from "../api/generated";
import { EmailTemplatesRead, READS } from "../api/reads";
import { SETTINGS_DEFAULTS, VOCAB } from "../api/vocabularies.generated";
import { DESCRIPTORS } from "../descriptors";
import { ITEMS, ITEM_BY_NUMBER, TIER_ORDER } from "./items";
import {
  deriveStatus,
  PENDING_READS,
  type ChecklistReads,
  type Marker,
  type Read,
} from "./status";

const FIXTURES = join(dirname(dirname(fileURLToPath(import.meta.url))), "api", "__fixtures__");

const raw = (name: string): unknown =>
  JSON.parse(readFileSync(join(FIXTURES, `${name}.json`), "utf-8"));

/** Parse through the shape that guards it, so the test data cannot drift either. */
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

/** Everything readable and empty — a brand-new organisation. */
const EMPTY: ChecklistReads = {
  ...SEEDED,
  staff: ok(staff.filter((u) => u.id === me.user_id)),
  skills: ok([]),
  programs: ok([]),
  pricing: ok({}),
  proposalTemplates: ok({}),
  messageTemplates: ok([]),
  emailTemplates: ok([]),
  playbooks: ok([]),
  approvalRules: ok([]),
  demoTeams: ok([]),
  vendors: ok([]),
};

const with_ = (over: Partial<ChecklistReads>): ChecklistReads => ({ ...SEEDED, ...over });

const settingsWith = (over: Partial<typeof settings>) =>
  ok({ ...settings, ...over } as typeof settings);

/**
 * The generated defaults, as a mutable plain object. `SETTINGS_DEFAULTS` is
 * `as const`, so its arrays are readonly and cannot be spread into a settings
 * payload; a round trip through JSON also matches what the server actually
 * hands back for the three JSON columns.
 */
const DEFAULTS: Partial<typeof settings> = JSON.parse(JSON.stringify(SETTINGS_DEFAULTS));

/* ── The table ─────────────────────────────────────────────────────────────── */

type Case = {
  name: string;
  item: number;
  reads: ChecklistReads;
  marker: Marker;
  /** Substrings the caption must contain. Captions name values, so these are
   *  the values — not the phrasing, which is allowed to be improved. */
  caption?: string[];
  /** Substrings the caption must NOT contain. */
  notCaption?: string[];
};

const CASES: Case[] = [
  // ── 1 · the organisation, from GET /auth/me alone (P6/A5) ────────────────
  {
    name: "1 · an org_admin session names its organisation",
    item: 1,
    reads: SEEDED,
    marker: "done",
    caption: [me.org_name!, me.name, me.role],
  },
  {
    name: "1 · a session with no org_id is not started, not done",
    item: 1,
    reads: with_({ me: ok({ ...me, org_id: null, org_name: null }) }),
    marker: "none",
  },

  // ── 2 · staff · the fixture org is genuinely partial ─────────────────────
  {
    name: "2 · one of two active accounts has no department",
    item: 2,
    reads: SEEDED,
    marker: "partial",
    caption: ["2 active accounts", "1 with no department", "Fixture Admin"],
  },
  {
    name: "2 · nobody but the administrator",
    item: 2,
    reads: EMPTY,
    marker: "none",
  },
  {
    name: "2 · every active account has a department",
    item: 2,
    reads: with_({ staff: ok(staff.map((u) => ({ ...u, department: "operations" }))) }),
    marker: "done",
    caption: ["2 active accounts"],
  },

  // ── 3 · skills · partial vs full coverage ────────────────────────────────
  {
    name: "3 · one of two people holds a skill",
    item: 3,
    reads: SEEDED,
    marker: "partial",
    caption: ["1 of 2 people", "phase lead"],
  },
  {
    name: "3 · everybody holds a skill",
    item: 3,
    reads: with_({
      skills: ok(staff.map((u) => ({ user_id: u.id, skill: "general", level: "basic" }))),
    }),
    marker: "done",
    caption: ["all 2 people"],
  },
  {
    name: "3 · nobody holds a skill",
    item: 3,
    reads: EMPTY,
    marker: "none",
  },

  // ── 4 · offerings ────────────────────────────────────────────────────────
  { name: "4 · one described offering", item: 4, reads: SEEDED, marker: "done" },
  { name: "4 · nothing to sell", item: 4, reads: EMPTY, marker: "none" },
  {
    name: "4 · an offering with no description cannot be matched",
    item: 4,
    reads: with_({ programs: ok(programs.map((p) => ({ ...p, description: null }))) }),
    marker: "partial",
    caption: ["no description"],
  },

  // ── 5 / 6 / 8 · per-offering coverage, and the vacuous case ──────────────
  { name: "5 · every offering has a current rate card", item: 5, reads: SEEDED, marker: "done" },
  {
    name: "5 · no offering yet is NOT satisfied",
    item: 5,
    reads: EMPTY,
    marker: "none",
    caption: ["item 4 comes first"],
  },
  {
    name: "5 · a second offering with no rate card",
    item: 5,
    reads: with_({
      programs: ok([...programs, { ...programs[0], id: "p2", code: "DC-AUDIT" }]),
    }),
    marker: "partial",
    caption: ["1 of 2 offerings", "DC-AUDIT"],
  },
  {
    name: "5 · a rate card exists but no version is current",
    item: 5,
    reads: with_({
      pricing: ok({ [PROGRAM_ID]: pricing.map((t) => ({ ...t, is_current: false })) }),
    }),
    marker: "none",
  },
  { name: "6 · every offering has a current template", item: 6, reads: SEEDED, marker: "done" },
  { name: "8 · every offering has a current playbook", item: 8, reads: SEEDED, marker: "done" },
  {
    name: "8 · a second offering with no playbook",
    item: 8,
    reads: with_({
      programs: ok([...programs, { ...programs[0], id: "p2", code: "DC-AUDIT" }]),
    }),
    marker: "partial",
    caption: ["DC-AUDIT"],
  },

  // ── 7 · message templates at 4, 3, 1 and 0 of the four combinations ──────
  {
    name: "7 · all four kind × channel combinations",
    item: 7,
    reads: SEEDED,
    marker: "done",
    caption: ["all 4"],
  },
  {
    name: "7 · three of four",
    item: 7,
    reads: with_({ messageTemplates: ok(messageTemplates.slice(0, 3)) }),
    marker: "partial",
    caption: ["3 of 4", "intro/whatsapp"],
  },
  {
    name: "7 · one of four",
    item: 7,
    reads: with_({ messageTemplates: ok(messageTemplates.slice(0, 1)) }),
    marker: "partial",
    caption: ["1 of 4"],
  },
  {
    name: "7 · a row that is not current does not count",
    item: 7,
    reads: with_({
      messageTemplates: ok(messageTemplates.map((t) => ({ ...t, is_current: false }))),
      emailTemplates: ok(emailTemplates.map((t) => ({ ...t, is_current: false }))),
    }),
    marker: "none",
  },
  {
    // 28 Oct 2026: Jarvis's email follow-ups use the Word templates now, so
    // the old follow_up/email row is no longer one of the four.
    name: "7 · the three old ones and one Word email template is done",
    item: 7,
    reads: with_({
      messageTemplates: ok(
        messageTemplates.filter((t) => !(t.kind === "follow_up" && t.channel === "email")),
      ),
    }),
    marker: "done",
    caption: ["all 4"],
  },
  {
    name: "7 · no Word email template is partial",
    item: 7,
    reads: with_({ emailTemplates: ok([]) }),
    marker: "partial",
    caption: ["3 of 4", "a Word email template"],
  },

  // ── 9 · approval rules and the catch-all ─────────────────────────────────
  {
    name: "9 · every entity type in use has a catch-all",
    item: 9,
    reads: SEEDED,
    marker: "done",
    caption: ["2 rules"],
  },
  {
    name: "9 · rules exist but nothing catches the rest",
    item: 9,
    reads: with_({ approvalRules: ok(approvalRules.filter((r) => r.rank !== 100)) }),
    marker: "partial",
    caption: ["no catch-all", "proposal"],
  },
  {
    // P15: this caption used to end "has no approver", which is false for
    // seven of the nine `request_approval` call sites (they name a default) and
    // an understatement for the other two (they apply it unreviewed). The row
    // must not claim an outcome it cannot know from the rules alone.
    name: "9 · does not claim what a missing catch-all costs — that is check 4's job",
    item: 9,
    reads: with_({ approvalRules: ok(approvalRules.filter((r) => r.rank !== 100)) }),
    marker: "partial",
    notCaption: ["has no approver"],
  },
  { name: "9 · no rules at all", item: 9, reads: EMPTY, marker: "none" },

  // ── 10 · the dials, and the limit the API imposes ────────────────────────
  {
    name: "10 · untouched defaults are ◐, never a green tick",
    item: 10,
    reads: with_({ settings: settingsWith(DEFAULTS) }),
    marker: "partial",
    caption: ["defaults apply", "cannot tell whether you chose them"],
  },
  {
    name: "10 · the fixture org changed three dials the operator could choose",
    item: 10,
    reads: SEEDED,
    // The fixture also carries a non-default llm_monthly_budget_usd, which
    // org creation wrote from the server's env — it does not count.
    marker: "done",
    caption: ["3 of 25"],
  },
  {
    name: "10 · a dial only the server's environment set is still ◐",
    item: 10,
    reads: with_({
      settings: settingsWith({ ...DEFAULTS, llm_monthly_budget_usd: 3 }),
    }),
    marker: "partial",
    caption: ["llm_monthly_budget_usd", "cannot tell whether you chose them"],
    notCaption: ["of 25"],
  },
  {
    name: "10 · one changed dial is enough",
    item: 10,
    reads: with_({
      settings: settingsWith({ ...DEFAULTS, timezone: "Europe/London" }),
    }),
    marker: "done",
    caption: ["1 of 25"],
  },

  // ── 11 · the compound one. This is what change #2 exists for ─────────────
  {
    name: "11 · credentials stored, sending OFF — ◐ and never ●",
    item: 11,
    reads: with_({
      settings: settingsWith({ email_credentials_stored: true, email_mode: "dry_run" }),
    }),
    marker: "partial",
    caption: [
      "credentials stored",
      "sending is OFF on this server",
      "EMAIL_MODE=dry_run",
      "written to a file",
    ],
  },
  {
    name: "11 · credentials stored and sending ON",
    item: 11,
    reads: with_({
      settings: settingsWith({ email_credentials_stored: true, email_mode: "smtp" }),
    }),
    marker: "done",
    caption: ["EMAIL_MODE=smtp"],
  },
  {
    name: "11 · sending ON with no credentials still goes to a file",
    item: 11,
    reads: with_({
      settings: settingsWith({ email_credentials_stored: false, email_mode: "smtp" }),
    }),
    marker: "partial",
    caption: ["no credentials stored"],
  },
  {
    name: "11 · neither half",
    item: 11,
    reads: with_({
      settings: settingsWith({ email_credentials_stored: false, email_mode: "dry_run" }),
    }),
    marker: "none",
  },

  // ── 12 · in force, but unverifiable — P12 ────────────────────────────────
  {
    name: "12 · the current windows are named",
    item: 12,
    reads: SEEDED,
    marker: "partial",
    caption: ["recordings 90 days", "transcripts 365 days", "seeded from the server's environment"],
  },
  {
    name: "12 · still ◐ even when the windows are plainly not the model defaults",
    item: 12,
    // A deliberately chosen pair. It is STILL ◐: the env var could have seeded
    // exactly these, and no route returns the env var to rule that out (P12).
    reads: with_({
      settings: settingsWith({ audio_retention_days: 45, transcript_retention_days: 700 }),
    }),
    marker: "partial",
    caption: ["recordings 45 days", "transcripts 700 days"],
  },

  // ── 13 / 14 / 15 · the optional tier ─────────────────────────────────────
  { name: "13 · one team", item: 13, reads: SEEDED, marker: "done" },
  { name: "13 · no teams is fine, and is still ○", item: 13, reads: EMPTY, marker: "none" },
  {
    name: "14 · calendar credentials stored, mirroring OFF",
    item: 14,
    reads: with_({
      settings: settingsWith({ calendar_credentials_stored: true, calendar_mode: "off" }),
    }),
    marker: "partial",
    caption: ["CALENDAR_MODE=off", "credentials stored"],
  },
  {
    name: "14 · both halves",
    item: 14,
    reads: with_({
      settings: settingsWith({ calendar_credentials_stored: true, calendar_mode: "google" }),
    }),
    marker: "done",
  },
  { name: "15 · one vendor", item: 15, reads: SEEDED, marker: "done" },
  { name: "15 · no vendors", item: 15, reads: EMPTY, marker: "none" },

  // ── 16 · permanent, and it says why ──────────────────────────────────────
  {
    name: "16 · permanently — even with every read healthy",
    item: 16,
    reads: SEEDED,
    marker: "blocked",
    caption: ["no endpoint", "no per-org storage", "INBOUND_EMAIL_MODE", "F35"],
  },

  // ── A drifted read is —, never ○ (A1) ────────────────────────────────────
  {
    name: "a drifted read makes its item — with the reason, never ○",
    item: 9,
    reads: with_({
      approvalRules: {
        state: "unreadable",
        why: "GET /api/v1/approval-rules → 0.fallback_role: Required",
      },
    }),
    marker: "blocked",
    caption: ["fallback_role"],
    notCaption: ["no rules"],
  },
  {
    name: "a drifted staff read blocks item 3 too, not only item 2",
    item: 3,
    reads: with_({ staff: { state: "unreadable", why: "GET /admin/users failed: 403" } }),
    marker: "blocked",
    caption: ["403"],
  },
];

describe("deriveStatus", () => {
  it.each(CASES)("$name", ({ item, reads, marker, caption, notCaption }) => {
    const result = deriveStatus(ITEM_BY_NUMBER.get(item)!, reads);
    expect(result.marker, `caption was: ${result.caption}`).toBe(marker);
    for (const fragment of caption ?? []) expect(result.caption).toContain(fragment);
    for (const fragment of notCaption ?? []) expect(result.caption).not.toContain(fragment);
  });

  it("covers all four markers plus pending", () => {
    // Guards the table against quietly losing a case: a suite that only ever
    // asserts ● and ○ would pass while the two markers §6 exists for rotted.
    const seen = new Set(CASES.map((c) => c.marker));
    expect([...seen].sort()).toEqual(["blocked", "done", "none", "partial"]);
  });
});

describe("never optimistic", () => {
  it("a read still in flight is `pending`, never `○`", () => {
    // Showing "not started" while a request is open is the exact false
    // reassurance §5.2's "no local I-did-that flags" rule is written against.
    for (const item of ITEMS) {
      const marker = deriveStatus(item, PENDING_READS).marker;
      if (item.n === 16) {
        expect(marker, "16 takes no read at all").toBe("blocked");
      } else {
        expect(marker, `item ${item.n}`).toBe("pending");
      }
    }
  });

  it("every item survives a completely unreadable API without claiming anything", () => {
    const unreadable = Object.fromEntries(
      Object.keys(PENDING_READS).map((k) => [
        k,
        { state: "unreadable", why: "the server is unreachable" },
      ]),
    ) as ChecklistReads;
    for (const item of ITEMS) {
      const { marker, caption } = deriveStatus(item, unreadable);
      expect(marker, `item ${item.n}`).toBe("blocked");
      expect(caption.length, `item ${item.n} says nothing`).toBeGreaterThan(0);
    }
  });

  it("item 11 is `done` only when both halves hold", () => {
    // Stated as an exhaustive truth table rather than as three examples,
    // because "never ● on dry_run" is the single claim this console exists to
    // keep. p.7: "otherwise approved messages are written to a file and
    // everyone believes they were sent".
    const item = ITEM_BY_NUMBER.get(11)!;
    for (const stored of [true, false]) {
      for (const mode of ["smtp", "dry_run", "", "SMTP"]) {
        const marker = deriveStatus(
          item,
          with_({
            settings: settingsWith({ email_credentials_stored: stored, email_mode: mode }),
          }),
        ).marker;
        expect(marker === "done", `stored=${stored} mode=${mode}`).toBe(
          stored && mode === "smtp",
        );
      }
    }
  });

  it("item 12 is never `done`, whatever the windows say (P12)", () => {
    // The two columns it reads are seeded by POST /orgs from env vars no route
    // returns, so no response can establish that a human chose them. Stated as
    // "never ● for any input" rather than as two examples, because the next
    // person's instinct on seeing ◐ on a satisfied-looking row will be to
    // "fix" it back to ●.
    const item = ITEM_BY_NUMBER.get(12)!;
    for (const audio of [1, 90, 365, 3650]) {
      for (const transcript of [1, 90, 365, 3650]) {
        const { marker, caption } = deriveStatus(
          item,
          with_({
            settings: settingsWith({
              audio_retention_days: audio,
              transcript_retention_days: transcript,
            }),
          }),
        );
        expect(marker, `audio=${audio} transcript=${transcript}`).toBe("partial");
        expect(caption).toContain(`recordings ${audio} day`);
      }
    }
  });

  it("no status claims a choice from a column POST /orgs seeds (P12)", () => {
    // The audit in status.ts's ENV_SEEDED comment, asserted rather than
    // trusted: a brand-new organisation — nothing created, every dial at its
    // model default, the three env-seeded columns at values that differ — has
    // no green row except item 1, which asserts only that it exists.
    const fresh: ChecklistReads = {
      ...EMPTY,
      settings: settingsWith({
        ...DEFAULTS,
        // What this repo's .env actually produces at org creation.
        llm_monthly_budget_usd: 3,
        audio_retention_days: 90,
        transcript_retention_days: 365,
        email_credentials_stored: false,
        email_mode: "dry_run",
        calendar_credentials_stored: false,
        calendar_mode: "dry_run",
      }),
    };
    const green = ITEMS.filter((i) => deriveStatus(i, fresh).marker === "done").map(
      (i) => i.n,
    );
    expect(green, "only item 1 may be green on an untouched organisation").toEqual([1]);
  });

  it("item 10 compares against the generated defaults, key order included", () => {
    // `nudge_gap_days` comes back from SQLite as JSON with no ordering
    // guarantee. A serialise-and-compare would call an untouched org "changed".
    const reordered: Partial<typeof settings> = {
      ...DEFAULTS,
      nudge_gap_days: { level3: 5, level1: 1, level2: 3 },
    };
    expect(
      deriveStatus(ITEM_BY_NUMBER.get(10)!, with_({ settings: settingsWith(reordered) }))
        .marker,
    ).toBe("partial");
  });
});

describe("the sixteen items", () => {
  it("is sixteen rows, numbered 1–16, tiered as the manual tiers them", () => {
    expect(ITEMS.map((i) => i.n)).toEqual(Array.from({ length: 16 }, (_, i) => i + 1));
    const count = (tier: string) => ITEMS.filter((i) => i.tier === tier).length;
    // The manual's own counts: Essential 7, Strongly recommended 4, Optional 4,
    // with item 1 outside them at platform level.
    expect(count("platform")).toBe(1);
    expect(count("essential")).toBe(7);
    expect(count("recommended")).toBe(4);
    expect(count("optional")).toBe(4);
    // Tiers are contiguous blocks in item order — the rail renders them as
    // labelled groups separated by a rule, which a shuffled list cannot do.
    const order = ITEMS.map((i) => TIER_ORDER.indexOf(i.tier));
    expect(order).toEqual([...order].sort((a, b) => a - b));
  });

  it("quotes the manual once, and takes the eleven from their descriptors", () => {
    const byItem = new Map(Object.values(DESCRIPTORS).map((d) => [d.item, d]));
    for (const item of ITEMS) {
      expect(item.quote.length, `item ${item.n} has no quote`).toBeGreaterThan(20);
      expect(item.ifSkipped.length, `item ${item.n}`).toBeGreaterThan(10);
      expect(item.manualRef, `item ${item.n}`).toMatch(/^Product manual, p\. \d/);
      const d = byItem.get(item.n);
      if (d) {
        // Not a second copy: the row reads through to the descriptor, so there
        // is exactly one place to correct if a quote is ever mis-transcribed.
        expect(item.quote).toBe(d.quote);
        expect(item.ifSkipped).toBe(d.ifSkipped);
        expect(item.entity).toBe(d.key);
      } else {
        expect(item.entity).toBeNull();
      }
    }
  });

  it("every descriptor dependency appears as an item dependency", () => {
    // The two layers express the same foreign keys in different units —
    // entity keys and item numbers — and drift between them is silent.
    for (const item of ITEMS) {
      if (!item.entity) continue;
      for (const parent of DESCRIPTORS[item.entity].dependsOn) {
        expect(item.dependsOn, `item ${item.n} → ${parent}`).toContain(
          DESCRIPTORS[parent].item,
        );
      }
      for (const n of item.dependsOn) expect(ITEM_BY_NUMBER.has(n)).toBe(true);
    }
  });

  it("takes the four kind × channel combinations from the vocabularies", () => {
    // A4: no role, kind or channel list is ever typed by hand — `RoleGate.java`
    // is one permission behind because one was.
    expect(VOCAB.template_kind.length * VOCAB.message_channel.length).toBe(4);
  });
});
