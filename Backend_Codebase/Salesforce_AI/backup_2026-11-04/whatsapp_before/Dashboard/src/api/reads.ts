/**
 * Read shapes for the eleven untyped responses — 07_BUILD_PLAN.md P1 / A1.
 *
 * **This is the only hand-written layer in the console's type stack, and it is
 * hand-written because there is nothing to generate from.** FastAPI emits a
 * response schema only where a route declares `response_model=`, and exactly
 * two routes this console reads do: `GET /admin/users` and
 * `GET /admin/users/{id}`. Every other read is `"schema": {}` in the spec —
 * OpenAPI for *anything* — while §5.2 derives every checklist status from them.
 *
 * Four things keep this file honest, because "we were careful" is not a
 * mechanism:
 *
 *  1. **Every shape cites the handler it was transcribed from**, so the next
 *     person re-derives it with one grep rather than by reading the whole API.
 *     Transcribe from the handler's literal `return`, not its docstring.
 *  2. **Committed fixtures**, captured from a live seeded backend by
 *     `tools/capture_fixtures.mjs`, are parsed by every shape in
 *     `reads.test.ts`. A rename fails a test on the next capture.
 *  3. **A round-trip test derived from `generated.ts`** asserts that every
 *     field a write schema accepts is readable back. That test would have
 *     caught P4 and P5 on its own — the two defects that reopened the backend
 *     change list — so the class of bug is now guarded rather than remembered.
 *  4. **`client.ts` parses every read** and turns a mismatch into a visible
 *     drift banner, with the affected statuses shown as `—` rather than `○`.
 *
 * ## Strictness, deliberately asymmetric
 *
 * Objects are **not** `.strict()`: a field the backend *adds* must not break a
 * running console. Fields the handler always returns are **required**, so a
 * field the backend *removes or renames* does break it — loudly, at the client
 * boundary. Removal is the drift that silently corrupts a status; addition is
 * not.
 */
import { z } from "zod";

/** JSON the API stores without a sub-model. Kept loose on purpose (§3.3). */
const jsonObject = z.record(z.unknown());

// ── ops.py · list_skills ────────────────────────────────────────────────────
// Returns no row id — which is why DELETE /skills takes the natural key.
export const SkillsRead = z.array(
  z.object({
    user_id: z.string(),
    skill: z.string(),
    level: z.string(),
  }),
);

// ── admin.py · list_programs ────────────────────────────────────────────────
export const ProgramsRead = z.array(
  z.object({
    id: z.string(),
    name: z.string(),
    code: z.string(),
    description: z.string().nullable(),
    is_active: z.boolean(),
  }),
);

// ── admin.py · get_pricing_history ──────────────────────────────────────────
// `items` is stored as `model_dump()` of PricingItem, so every key is present
// and `default_quantity` is null when the org did not state one — the tri-state
// §3.3 exists to protect. Verified in the fixture: one line has 4, one has null.
export const PricingItemRead = z.object({
  code: z.string(),
  label: z.string(),
  unit: z.string(),
  unit_price: z.number(),
  default_quantity: z.number().nullable(),
  notes: z.string().nullable(),
});

export const PricingRead = z.array(
  z.object({
    id: z.string(),
    version: z.number(),
    currency: z.string(),
    items: z.array(PricingItemRead),
    is_current: z.boolean(),
    effective_from: z.string(),
  }),
);

// ── admin.py · list_proposal_templates ──────────────────────────────────────
export const ProposalTemplatesRead = z.array(
  z.object({
    id: z.string(),
    name: z.string(),
    version: z.number(),
    // "markdown" or "docx". The screen shows which, and the bundle refuses to
    // carry a docx one, because the document itself is not in the bundle.
    kind: z.string(),
    is_current: z.boolean(),
    body_md: z.string(),
  }),
);

// ── admin.py · list_message_templates ───────────────────────────────────────
export const MessageTemplatesRead = z.array(
  z.object({
    id: z.string(),
    kind: z.string(),
    channel: z.string(),
    name: z.string(),
    version: z.number(),
    subject: z.string().nullable(),
    body: z.string(),
    is_current: z.boolean(),
  }),
);

// ── email_templates.py · list_email_templates (28 Oct 2026) ────────────────
// Word email templates: common ones by category, product ones by product.
// Read by item 7 and its checklist rule. Not in READS: it has no catalogue
// descriptor and no bundle entry (spec 2, non-goals).
export const EmailTemplatesRead = z.array(
  z.object({
    id: z.string(),
    template_type: z.string(),
    category: z.string().nullable(),
    category_label: z.string().nullable(),
    program_id: z.string().nullable(),
    program_name: z.string().nullable(),
    name: z.string(),
    when_to_use: z.string().nullable(),
    version: z.number(),
    is_current: z.boolean(),
    built_document: z.string(),
    subject: z.string(),
    filename: z.string(),
    tags: z.number(),
    always_asked: z.number(),
    distinct: z.array(z.string()),
    leftover_blanks: z.array(z.string()),
    attachments: z.array(
      z.object({ id: z.string(), filename: z.string(), size_bytes: z.number() }),
    ),
  }),
);

// ── email_templates.py · list_email_categories ─────────────────────────────
export const EmailCategoriesRead = z.array(
  z.object({ key: z.string(), label: z.string() }),
);

// ── ops.py · list_playbooks (change #3) ─────────────────────────────────────
export const PlaybooksRead = z.array(
  z.object({
    id: z.string(),
    program_id: z.string(),
    phase: z.string(),
    entries: z.array(jsonObject),
    version: z.number(),
    is_current: z.boolean(),
    updated_by: z.string().nullable(),
  }),
);

// ── ops.py · list_approval_rules (change #9 added the last two) ─────────────
// Before change #9 this read omitted `fallback_role` and `auto_approve` while
// the write accepted both, so the reseed bundle silently dropped them. They are
// required here now: if they ever vanish again, the drift banner says so on the
// first read rather than at someone's reseed.
export const ApprovalRulesRead = z.array(
  z.object({
    id: z.string(),
    entity_type: z.string(),
    condition: jsonObject,
    rank: z.number(),
    approver_role: z.string(),
    fallback_role: z.string().nullable(),
    recommender_role: z.string().nullable(),
    joint_with_role: z.string().nullable(),
    joint_condition: jsonObject.nullable(),
    auto_approve: z.boolean(),
    expires_hours: z.number(),
    description: z.string().nullable(),
  }),
);

// ── admin.py · list_demo_teams (change #10 added the three ids) ─────────────
// The names stay because the Android app renders them; the ids are what the
// recreate path and the bundle need. Both halves are modelled.
export const DemoTeamsRead = z.array(
  z.object({
    id: z.string(),
    name: z.string(),
    lead: z.string().nullable(),
    lead_user_id: z.string().nullable(),
    media_rep: z.string().nullable(),
    media_rep_id: z.string().nullable(),
    sales_rep: z.string().nullable(),
    sales_rep_id: z.string().nullable(),
    members: z.array(z.object({ id: z.string(), name: z.string() })),
  }),
);

// ── ops.py · list_vendors (change #7 added the contact fields) ──────────────
export const VendorsRead = z.array(
  z.object({
    id: z.string(),
    name: z.string(),
    contact_name: z.string().nullable(),
    phone: z.string().nullable(),
    email: z.string().nullable(),
    category: z.string().nullable(),
    notes: z.string().nullable(),
  }),
);

// ── admin.py · _settings_response ───────────────────────────────────────────
// 25 dials plus the 10 delivery-honesty fields change #2 added. Every dial
// column is NOT NULL with a model default — checked against
// `Base.metadata.tables["org_settings"]`, not inferred from one payload — so
// none of them is nullable here.
export const SettingsRead = z
  .object({
    require_action_item_review: z.boolean(),
    auto_suggest_lead_state: z.boolean(),
    audio_retention_days: z.number(),
    transcript_retention_days: z.number(),
    llm_monthly_budget_usd: z.number(),
    timezone: z.string(),
    currency: z.string(),
    followup_cadence_days: z.number(),
    assignment_mode: z.string(),
    working_days: z.array(z.string()),
    workday_start: z.string(),
    workday_end: z.string(),
    quiet_hours_override_priority: z.string(),
    nudge_gap_days: jsonObject,
    max_unanswered_nudges: z.number(),
    max_client_messages_per_week: z.number(),
    lead_cold_after_days: z.number(),
    high_load_caution_pct: z.number(),
    delivery_requires_advance: z.boolean(),
    scope_change_requires_confirmation: z.boolean(),
    client_report_day: z.string(),
    client_report_time: z.string(),
    payment_reminder_schedule: z.array(jsonObject),
    reply_nudge_after_days: jsonObject,
    ai_confidence_threshold: z.number(),

    // Change #2. Both halves of every channel, because "configured" needs two
    // facts and a single boolean cannot say which one is missing (§5.2 item 11).
    email_mode: z.string(),
    whatsapp_mode: z.string(),
    calendar_mode: z.string(),
    inbound_email_mode: z.string(),
    email_credentials_stored: z.boolean(),
    whatsapp_credentials_stored: z.boolean(),
    calendar_credentials_stored: z.boolean(),
    email_integration_configured: z.boolean(),
    whatsapp_integration_configured: z.boolean(),
    calendar_integration_configured: z.boolean(),
  });

// ── admin.py · reset_organisation (dry run) ─────────────────────────────────
// `blocking_edges` is populated only for a catalogue-only reset that would
// orphan surviving rows (D22/D23). A dry run never 422s, so the preview must
// render them — see Task 24.
export const ResetRead = z.object({
  org: z.object({ id: z.string(), name: z.string() }),
  counts: z.record(z.number()),
  total: z.number(),
  applied: z.boolean(),
  blocking_edges: z.array(
    z.object({
      table: z.string(),
      column: z.string(),
      references: z.string(),
      count: z.number(),
    }),
  ),
});

// ── admin.py · delete_organisation (28 Oct 2026) ────────────────────────────
// Hand-written, not in READS (no descriptor, no fixture), like
// EmailTemplatesRead: the generated files were already stale before this
// route existed. Spec: docs/superpowers/specs/2026-10-28-org-delete-design.md.
export const OrgDeletePreviewRead = z.object({
  applied: z.literal(false),
  org: z.object({ id: z.string(), name: z.string() }),
  rows: z.record(z.number()),
  total: z.number(),
  platform_rows: z.number(),
  other_org_mentions: z.record(z.number()),
  files: z.number(),
  bytes: z.number(),
  outside_files: z.array(z.string()),
  users: z.array(z.object({ email: z.string(), role: z.string() })),
  expected_confirmation: z.string(),
});

export const OrgDeleteResultRead = z.object({
  applied: z.literal(true),
  org: z.object({ id: z.string(), name: z.string() }),
  deleted: z.record(z.number()),
  total: z.number(),
  platform_rows_removed: z.number(),
  files_removed: z.number(),
  bytes_removed: z.number(),
  remaining: z.record(z.number()),
  compacted: z.boolean(),
  backup_folder: z.string().nullable(),
  backup_expires_at: z.string().nullable(),
});

/**
 * Every untyped read, keyed by its fixture name. The keys are the contract the
 * coverage test checks: a shape with no fixture, or a fixture with no shape, is
 * a failure.
 */
export const READS = {
  skills: SkillsRead,
  programs: ProgramsRead,
  pricing: PricingRead,
  proposalTemplates: ProposalTemplatesRead,
  messageTemplates: MessageTemplatesRead,
  playbooks: PlaybooksRead,
  approvalRules: ApprovalRulesRead,
  demoTeams: DemoTeamsRead,
  vendors: VendorsRead,
  settings: SettingsRead,
  resetDryRun: ResetRead,
} as const;

export type ReadKey = keyof typeof READS;

/** Handler each shape was transcribed from — rendered by the drift banner. */
export const READ_SOURCE: Record<ReadKey, string> = {
  skills: "ops.py · list_skills",
  programs: "admin.py · list_programs",
  pricing: "admin.py · get_pricing_history",
  proposalTemplates: "admin.py · list_proposal_templates",
  messageTemplates: "admin.py · list_message_templates",
  playbooks: "ops.py · list_playbooks",
  approvalRules: "ops.py · list_approval_rules",
  demoTeams: "admin.py · list_demo_teams",
  vendors: "ops.py · list_vendors",
  settings: "admin.py · _settings_response",
  resetDryRun: "admin.py · reset_organisation",
};

// ── admin.py · get_proposal_template_doc ────────────────────────────────────
// The uploaded document, its parsed outline, and the fill plan the editor
// writes back. `outline` is a read-only view of an immutable file, which is
// what makes the positional `path` on each block safe to store in a plan.
export const BlockRead = z.object({
  id: z.string(),
  path: z.string(),
  kind: z.string(),
  style: z.string(),
  level: z.number().nullable(),
  text: z.string(),
  images: z.array(z.string()),
  table: z
    .object({
      rows: z.number(),
      cols: z.number(),
      header: z.array(z.string()),
      sample: z.array(z.array(z.string())),
    })
    .nullable(),
  fingerprint: z.string(),
});

export const TemplateDocRead = z.object({
  id: z.string(),
  template_id: z.string(),
  // The template's own name and version, which the editor's header states: an
  // administrator marking placeholders must know which version they are on,
  // because a new upload supersedes this one and takes its own outline with it.
  name: z.string(),
  version: z.number(),
  filename: z.string(),
  size_bytes: z.number(),
  index_kind: z.enum(["field", "static", "none"]),
  analysis_status: z.string(),
  analysis_error: z.string().nullable(),
  outline: z.object({
    blocks: z.array(BlockRead),
    headings: z.array(
      z.object({
        id: z.string(),
        path: z.string(),
        level: z.number().nullable(),
        text: z.string(),
      }),
    ),
    tokens: z.array(
      z.object({
        literal: z.string(),
        occurrences: z.number(),
        sample_block_ids: z.array(z.string()),
      }),
    ),
    media: z.array(z.string()),
  }),
  // Keyed by media file name, the same names `outline.media` carries. The
  // editor shows each image with the text tesseract read out of it, which is
  // often the only place a logo's wording exists as text at all.
  ocr: z.record(z.string()),
  plan: z.object({
    version: z.number(),
    entries: z.array(z.record(z.unknown())),
  }),
});

export type Block = z.infer<typeof BlockRead>;
export type TemplateDoc = z.infer<typeof TemplateDocRead>;

export type Skills = z.infer<typeof SkillsRead>;
export type Programs = z.infer<typeof ProgramsRead>;
export type Pricing = z.infer<typeof PricingRead>;
export type ProposalTemplates = z.infer<typeof ProposalTemplatesRead>;
export type MessageTemplates = z.infer<typeof MessageTemplatesRead>;
export type EmailTemplates = z.infer<typeof EmailTemplatesRead>;
export type EmailTemplate = EmailTemplates[number];
export type EmailCategories = z.infer<typeof EmailCategoriesRead>;
export type Playbooks = z.infer<typeof PlaybooksRead>;
export type ApprovalRules = z.infer<typeof ApprovalRulesRead>;
export type DemoTeams = z.infer<typeof DemoTeamsRead>;
export type Vendors = z.infer<typeof VendorsRead>;
export type Settings = z.infer<typeof SettingsRead>;
export type ResetPreview = z.infer<typeof ResetRead>;
