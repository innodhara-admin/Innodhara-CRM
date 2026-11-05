/**
 * Playbooks, approval rules, settings, demo teams and vendors.
 *
 * These are the entities whose write bodies carry free `dict` / `list[dict]`
 * fields, so they are where `ui-only` clusters — every one of those rules is a
 * place the server will accept whatever it is sent.
 */
import { CONSTRAINTS } from "../api/constraints.generated";
import { VOCAB } from "../api/vocabularies.generated";
import type { Descriptor } from "./types";

const S = CONSTRAINTS.SettingsRequest;

export const playbooks: Descriptor = {
  key: "playbooks",
  item: 8,
  title: "Standard task waves for each offering and phase",
  writeSchema: "PlaybookRequest",
  read: "playbooks",
  quote:
    "Your repeatable checklist — what always happens in preparation, in " +
    "delivery, at payment, at closure — with day offsets from the start date.",
  ifSkipped:
    "Each phase is derived from scratch by the AI instead of following your " +
    "known-good routine.",
  manualRef: "Product manual, p. 7 · item 8",
  dependsOn: ["programs"],
  inBundle: true,
  reimport: "creates a NEW version and supersedes the current one for that program and phase",
  fields: [
    {
      field: "program_id",
      label: "Offering",
      control: "select",
      enforcement: {
        kind: "ui-only",
        why: "ops.py · upsert_playbook does not check that the program exists — a wrong id stores a playbook nothing will ever load",
      },
      caption: "the offering this wave belongs to",
    },
    {
      field: "phase",
      label: "Phase",
      control: "select",
      options: VOCAB.phase,
      // The server takes any string here, so refusing one would be this
      // console inventing a rule the backend does not have. It is allowed
      // through and warned about instead — see `optionsAreSuggestions`.
      optionsAreSuggestions: true,
      enforcement: {
        kind: "ui-only",
        why: "ops.py · upsert_playbook accepts any string; a phase outside this list produces a playbook no plan will ever fire",
      },
      caption: "one of the six the engine plans against",
    },
    {
      field: "entries",
      label: "Entries",
      control: "json",
      enforcement: {
        kind: "ui-only",
        why: "list[dict] with no sub-model — the server stores the blob unread, and the planner ignores keys it does not recognise",
      },
      caption:
        "each entry: title, required_skill, offset_days, priority, visible_to_client",
    },
  ],
  csv: null, // list[dict] per row; JSON only, and the format panel says so.
  // The entry keys are `project.py`'s model comment, confirmed against the 15
  // working entries in `seed_workflows.py`. Nothing validates any of them.
  jsonExample: {
    program_id: "<a programme id from What you sell>",
    phase: "preparation",
    entries: [
      {
        title: "Confirm site access",
        required_skill: "rack-and-stack",
        offset_days: -7,
        priority: "P1",
        visible_to_client: false,
      },
    ],
  },
};

export const approvalRules: Descriptor = {
  key: "approvalRules",
  item: 9,
  title: "Approval rules",
  writeSchema: "ApprovalRuleRequest",
  read: "approvalRules",
  quote:
    "Who signs off what, as data: a condition (for example a discount above " +
    "10%, or an amount above a threshold), a rank, an approver role, an " +
    "optional second approver and an optional recommender. Changing who " +
    "approves what is a settings edit, never a software change.",
  ifSkipped:
    "Everything falls to one default approver, and nothing is escalated by " +
    "value or risk.",
  manualRef: "Product manual, p. 6 · item 9",
  dependsOn: [],
  inBundle: true, // cleared by wipe_org_config
  reimport: "creates duplicate rows — nothing dedupes approval rules",
  fields: [
    {
      field: "entity_type",
      label: "Applies to",
      control: "text",
      enforcement: {
        kind: "ui-only",
        why: "an unconstrained string; a value no engine emits produces a rule that never fires",
      },
      caption: "e.g. proposal, outbound_message",
    },
    {
      field: "condition",
      label: "Condition",
      control: "json",
      enforcement: {
        kind: "ui-only",
        why: "a free dict — the 13 observed keys are a suggestion list, not a schema",
      },
      caption: "an empty object {} is the catch-all, and every entity type in use needs one",
    },
    {
      field: "rank",
      label: "Rank",
      control: "number",
      enforcement: { kind: "ui-only", why: "any integer is accepted, including one that duplicates another rule's rank — the tie is resolved by insertion order, which nothing displays" },
      caption: "lowest rank wins · a never-matching low rank quietly hands approval to the catch-all",
    },
    {
      field: "approver_role",
      label: "Approver",
      control: "select",
      options: VOCAB.org_role,
      enforcement: {
        kind: "ui-only",
        why: "stored unvalidated — a role name that does not exist leaves nobody able to approve",
      },
      caption: "who signs this off",
    },
    {
      field: "fallback_role",
      label: "Fallback approver",
      control: "select",
      options: VOCAB.org_role,
      enforcement: { kind: "ui-only", why: "stored unvalidated — a role name that does not exist leaves nobody able to approve" },
      caption: "used when the approver is unavailable · readable since change #9",
    },
    {
      field: "recommender_role",
      label: "Recommender",
      control: "select",
      options: VOCAB.org_role,
      enforcement: { kind: "ui-only", why: "stored unvalidated — an unknown role name simply never matches anyone" },
      caption: "optional · recommends but does not approve",
    },
    {
      field: "joint_with_role",
      label: "Joint approver",
      control: "select",
      options: VOCAB.org_role,
      enforcement: { kind: "ui-only", why: "stored unvalidated — an unknown role name means the joint approval can never be given" },
      caption: "optional · both must approve",
    },
    {
      field: "joint_condition",
      label: "Joint condition",
      control: "json",
      enforcement: { kind: "ui-only", why: "a free dict with no sub-model — unrecognised keys are stored and never read" },
      caption: "when the joint approver is required",
    },
    {
      field: "auto_approve",
      label: "Approve automatically",
      control: "checkbox",
      enforcement: { kind: "ui-only", why: "a plain boolean — nothing warns you that a rule approves itself, which is why the go-live check lists them" },
      caption: "no human is asked · readable since change #9, and the go-live check lists every rule with this set",
    },
    {
      field: "expires_hours",
      label: "Expires after",
      control: "number",
      enforcement: { kind: "ui-only", why: "any number is accepted, including zero, which expires the request immediately" },
      caption: "hours before the request escalates",
    },
    {
      field: "description",
      label: "Description",
      control: "text",
      enforcement: { kind: "ui-only", why: "free text — the server never reads it, so it is a note to your future self and nothing more" },
      caption: "why this rule exists — the only record of intent",
    },
  ],
  csv: null, // two free dicts per row; JSON only.
  jsonExample: {
    entity_type: "proposal",
    condition: { discount_pct_gt: 10 },
    rank: 10,
    approver_role: "sales_lead",
    fallback_role: "org_admin",
    auto_approve: false,
    expires_hours: 48,
    description: "Discounts above 10% go to the sales lead.",
  },
};

export const demoTeams: Descriptor = {
  key: "demoTeams",
  item: 13,
  title: "Demo teams",
  writeSchema: "DemoTeamRequest",
  read: "demoTeams",
  quote:
    "Named squads with a team lead, a media representative and a sales " +
    "representative, so a booking can be made against a team and clashes detected.",
  ifSkipped: "Demos are still bookable; they simply carry no team.",
  manualRef: "Product manual, p. 7 · item 13",
  dependsOn: ["staff"],
  inBundle: true,
  // The write takes ids; the read returns them (change #10) AND the resolved
  // names. `member_ids` is the one genuine rename.
  aliases: { member_ids: "members" },
  reimport: "fails on a duplicate name — unique per organisation, compared case-insensitively",
  fields: [
    {
      field: "name",
      label: "Team name",
      control: "text",
      enforcement: { kind: "backend-undeclared", source: "admin.py · register_demo_team" },
      caption: "unique per organisation · the delete must succeed before a recreate can reuse it",
    },
    {
      field: "lead_user_id",
      label: "Team lead",
      control: "select",
      enforcement: { kind: "backend-undeclared", source: "admin.py · register_demo_team" },
      caption: "must be a user in this organisation",
    },
    {
      field: "media_rep_id",
      label: "Media representative",
      control: "select",
      enforcement: { kind: "backend-undeclared", source: "admin.py · register_demo_team" },
      caption: "must be a user in this organisation",
    },
    {
      field: "sales_rep_id",
      label: "Sales representative",
      control: "select",
      enforcement: { kind: "backend-undeclared", source: "admin.py · register_demo_team" },
      caption: "must be a user in this organisation",
    },
    {
      field: "member_ids",
      label: "Members",
      control: "json",
      enforcement: { kind: "backend-undeclared", source: "admin.py · register_demo_team" },
      caption: "every id is checked · read back as members, with names",
    },
  ],
  csv: {
    columns: ["name", "lead_user_id", "media_rep_id", "sales_rep_id", "member_ids"],
    example: {
      name: "Commissioning crew",
      lead_user_id: "<a user id from Staff>",
      media_rep_id: "",
      sales_rep_id: "",
      member_ids: "<user id>|<user id>",
    },
  },
};

export const vendors: Descriptor = {
  key: "vendors",
  item: 15,
  title: "Vendors",
  writeSchema: "VendorRequest",
  read: "vendors",
  quote:
    "Outside suppliers your plans depend on, so a vendor promise can be " +
    "recorded against a task and chased.",
  ifSkipped:
    "Vendor promises can still be typed as free text, but are not tracked as vendors.",
  manualRef: "Product manual, p. 7 · item 15",
  dependsOn: [],
  inBundle: true,
  reimport: "creates duplicates silently — vendors have no uniqueness of any kind",
  fields: [
    {
      field: "name",
      label: "Name",
      control: "text",
      enforcement: { kind: "ui-only", why: "unconstrained, and not unique — re-importing duplicates it" },
      caption: "the supplier's name",
    },
    {
      field: "contact_name",
      label: "Contact",
      control: "text",
      enforcement: { kind: "ui-only", why: "free text · readable since change #7" },
      caption: "who to chase",
    },
    {
      field: "phone",
      label: "Phone",
      control: "text",
      enforcement: { kind: "ui-only", why: "free text · readable since change #7" },
      caption: "optional",
    },
    {
      field: "email",
      label: "Email",
      control: "text",
      enforcement: {
        kind: "ui-only",
        why: "VendorRequest types this as a plain string, not EmailStr — the server accepts anything",
      },
      caption: "optional · not validated as an address",
    },
    {
      field: "category",
      label: "Category",
      control: "text",
      enforcement: { kind: "ui-only", why: "free text with no category list anywhere — two spellings make two categories" },
      caption: "e.g. transport, civil, power",
    },
    {
      field: "notes",
      label: "Notes",
      control: "textarea",
      enforcement: { kind: "ui-only", why: "free text — stored verbatim and never parsed" },
      caption: "lead times, terms, anything worth remembering",
    },
  ],
  csv: {
    columns: ["name", "contact_name", "phone", "email", "category", "notes"],
    example: {
      name: "Northgate Logistics",
      contact_name: "Asha Rao",
      phone: "+919000000010",
      email: "asha@northgate-example.com",
      category: "transport",
      notes: "Two-day lead time.",
    },
  },
};

export const settings: Descriptor = {
  key: "settings",
  item: 10,
  title: "The behaviour dials",
  writeSchema: "SettingsRequest",
  read: "settings",
  quote:
    "Working days and hours, quiet hours, the three nudge intervals, how many " +
    "messages one client contact may receive per week, the payment-reminder " +
    "schedule, when the weekly report goes out, and whether task assignments " +
    "apply automatically or wait for a lead.",
  ifSkipped:
    "Sensible defaults apply, but the system will chase on days you do not " +
    "work and at hours you do not keep.",
  manualRef: "Product manual, p. 7 · item 10",
  dependsOn: [],
  // One row, updated in place — the reset never clears it (org_settings is KEEP).
  inBundle: false,
  reimport: "overwrites the fields present in the file · omitted fields are left unchanged",
  fields: [
    {
      field: "timezone",
      label: "Timezone",
      control: "text",
      enforcement: { kind: "ui-only", why: "an unconstrained string; an unknown zone is stored as typed" },
      caption: "e.g. Asia/Kolkata",
    },
    {
      field: "currency",
      label: "Currency",
      control: "text",
      enforcement: { kind: "ui-only", why: "an unconstrained string — no currency list is checked anywhere" },
      caption: "the default for new rate cards",
    },
    {
      field: "assignment_mode",
      label: "Assignment mode",
      control: "text",
      enforcement: { kind: "backend-undeclared", source: "admin.py · SettingsRequest" },
      caption: `matches ${S.assignment_mode.pattern} · auto applies immediately, lead_confirm waits`,
    },
    {
      field: "working_days",
      label: "Working days",
      control: "json",
      enforcement: {
        kind: "ui-only",
        why: "Pydantic says list[str] — a day name the scheduler does not recognise silently never matches",
      },
      caption: "the organisation default, overridden per person",
    },
    {
      field: "workday_start",
      label: "Workday start",
      control: "text",
      enforcement: { kind: "backend-undeclared", source: "admin.py · SettingsRequest" },
      caption: `matches ${S.workday_start.pattern} · 24-hour`,
    },
    {
      field: "workday_end",
      label: "Workday end",
      control: "text",
      enforcement: { kind: "backend-undeclared", source: "admin.py · SettingsRequest" },
      caption: `matches ${S.workday_end.pattern} · 24-hour`,
    },
    {
      field: "quiet_hours_override_priority",
      label: "Quiet-hours override",
      control: "text",
      enforcement: { kind: "backend-undeclared", source: "admin.py · SettingsRequest" },
      caption: `matches ${S.quiet_hours_override_priority.pattern} · only this priority breaks quiet hours`,
    },
    {
      field: "followup_cadence_days",
      label: "Follow-up cadence",
      control: "number",
      enforcement: { kind: "backend-undeclared", source: "admin.py · SettingsRequest" },
      caption: `${S.followup_cadence_days.minimum}–${S.followup_cadence_days.maximum} days`,
    },
    {
      field: "nudge_gap_days",
      label: "Nudge gaps",
      control: "json",
      enforcement: {
        kind: "ui-only",
        why: "a free dict — the key names are not validated, and an unrecognised key is simply never read",
      },
      caption: "the three nudge intervals, by key",
    },
    {
      field: "reply_nudge_after_days",
      label: "Reply nudges",
      control: "json",
      enforcement: { kind: "ui-only", why: "a free dict — an unrecognised key name is stored and silently never read" },
      caption: "when to chase an unanswered reply",
    },
    {
      field: "max_unanswered_nudges",
      label: "Max unanswered nudges",
      control: "number",
      enforcement: { kind: "backend-undeclared", source: "admin.py · SettingsRequest" },
      caption: `${S.max_unanswered_nudges.minimum}–${S.max_unanswered_nudges.maximum}`,
    },
    {
      field: "max_client_messages_per_week",
      label: "Max messages per week",
      control: "number",
      enforcement: { kind: "backend-undeclared", source: "admin.py · SettingsRequest" },
      caption: `${S.max_client_messages_per_week.minimum}–${S.max_client_messages_per_week.maximum} · per client contact`,
    },
    {
      field: "lead_cold_after_days",
      label: "Lead goes cold after",
      control: "number",
      enforcement: { kind: "backend-undeclared", source: "admin.py · SettingsRequest" },
      caption: `${S.lead_cold_after_days.minimum}–${S.lead_cold_after_days.maximum} days`,
    },
    {
      field: "high_load_caution_pct",
      label: "High-load caution",
      control: "number",
      enforcement: { kind: "backend-undeclared", source: "admin.py · SettingsRequest" },
      caption: `${S.high_load_caution_pct.minimum}–${S.high_load_caution_pct.maximum}% of a person's task ceiling`,
    },
    {
      field: "client_report_day",
      label: "Weekly report day",
      control: "text",
      enforcement: {
        kind: "ui-only",
        why: "Pydantic says str — a day name the scheduler does not recognise means the report never goes out",
      },
      caption: "e.g. Friday",
    },
    {
      field: "client_report_time",
      label: "Weekly report time",
      control: "text",
      enforcement: { kind: "backend-undeclared", source: "admin.py · SettingsRequest" },
      caption: `matches ${S.client_report_time.pattern}`,
    },
    {
      field: "payment_reminder_schedule",
      label: "Payment reminders",
      control: "json",
      enforcement: { kind: "ui-only", why: "list[dict] with no sub-model — an entry the scheduler cannot parse is skipped without a warning" },
      caption: "each entry: offset_days and channel",
    },
    {
      field: "ai_confidence_threshold",
      label: "AI confidence threshold",
      control: "number",
      enforcement: { kind: "backend-undeclared", source: "admin.py · SettingsRequest" },
      caption: `${S.ai_confidence_threshold.minimum}–${S.ai_confidence_threshold.maximum} · below this, a human is asked`,
    },
    {
      field: "audio_retention_days",
      label: "Audio retention",
      control: "number",
      enforcement: { kind: "backend-undeclared", source: "admin.py · SettingsRequest" },
      caption: `${S.audio_retention_days.minimum}–${S.audio_retention_days.maximum} days (item 12)`,
    },
    {
      field: "transcript_retention_days",
      label: "Transcript retention",
      control: "number",
      enforcement: { kind: "backend-undeclared", source: "admin.py · SettingsRequest" },
      caption: `${S.transcript_retention_days.minimum}–${S.transcript_retention_days.maximum} days (item 12)`,
    },
    {
      field: "llm_monthly_budget_usd",
      label: "Monthly AI budget",
      control: "number",
      enforcement: { kind: "backend-undeclared", source: "admin.py · SettingsRequest" },
      caption: `at least ${S.llm_monthly_budget_usd.minimum} · work stops when it is spent`,
    },
    {
      field: "require_action_item_review",
      label: "Review action items",
      control: "checkbox",
      enforcement: { kind: "ui-only", why: "a plain boolean, accepted as sent — there is no per-person override on this one" },
      caption: "a human confirms extracted tasks before they are assigned",
    },
    {
      field: "auto_suggest_lead_state",
      label: "Suggest lead state",
      control: "checkbox",
      enforcement: { kind: "ui-only", why: "a plain boolean, accepted as sent" },
      caption: "the AI proposes state changes rather than making them",
    },
    {
      field: "delivery_requires_advance",
      label: "Delivery needs an advance",
      control: "checkbox",
      enforcement: { kind: "ui-only", why: "a plain boolean, accepted as sent — the rule it switches on lives in the engine, not here" },
      caption: "delivery cannot start before an advance is recorded",
    },
    {
      field: "scope_change_requires_confirmation",
      label: "Scope changes need confirming",
      control: "checkbox",
      enforcement: { kind: "ui-only", why: "a plain boolean, accepted as sent — the rule it switches on lives in the engine, not here" },
      caption: "a scope change waits for a human",
    },
  ],
  csv: null, // one row, not a list — JSON only (§5.5).
  // Deliberately a handful of dials rather than all 25: PATCH applies with
  // exclude_none, so a settings file is "the ones you are changing", and a
  // template listing every field invites an operator to send values they never
  // chose. The three env-seeded dials (P11) are absent for the same reason.
  jsonExample: {
    timezone: "Asia/Kolkata",
    assignment_mode: "lead_confirm",
    working_days: ["Mon", "Tue", "Wed", "Thu", "Fri"],
    workday_start: "09:00",
    workday_end: "18:30",
  },
};
