import { z } from "zod";

const LoginRequest = z
  .object({
    email: z.string().email(),
    password: z.string(),
    org_slug: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const LoginResponse = z
  .object({
    access_token: z.string(),
    token_type: z.string().optional().default("bearer"),
    user_id: z.string(),
    name: z.string(),
    role: z.string(),
    org_id: z.union([z.string(), z.null()]),
    org_name: z.union([z.string(), z.null()]),
    must_change_password: z.boolean(),
  })
  .passthrough();
const ValidationError = z
  .object({
    loc: z.array(z.union([z.string(), z.number()])),
    msg: z.string(),
    type: z.string(),
    input: z.unknown().optional(),
    ctx: z.object({}).partial().passthrough().optional(),
  })
  .passthrough();
const HTTPValidationError = z
  .object({ detail: z.array(ValidationError) })
  .partial()
  .passthrough();
const MeResponse = z
  .object({
    user_id: z.string(),
    email: z.string(),
    name: z.string(),
    role: z.string(),
    org_id: z.union([z.string(), z.null()]),
    org_name: z.union([z.string(), z.null()]),
    phone: z.union([z.string(), z.null()]),
    has_email_app_password: z.boolean(),
    org_slug: z.union([z.string(), z.null()]).optional(),
    org_logo_url: z.union([z.string(), z.null()]).optional(),
    org_brand_colors: z
      .union([z.object({}).partial().passthrough(), z.null()])
      .optional(),
    designation: z.union([z.string(), z.null()]).optional(),
    department: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const ChangePasswordRequest = z
  .object({ current_password: z.string(), new_password: z.string() })
  .passthrough();
const AppPasswordRequest = z.object({ app_password: z.string() }).passthrough();
const OrgResponse = z
  .object({
    id: z.string(),
    name: z.string(),
    slug: z.string(),
    email_domain: z.string(),
    is_active: z.boolean(),
  })
  .passthrough();
const CreateOrgRequest = z
  .object({
    name: z.string().min(2).max(200),
    slug: z
      .string()
      .min(2)
      .max(100)
      .regex(/^[a-z0-9-]+$/),
    email_domain: z.string().min(3).max(200),
    logo_url: z.union([z.string(), z.null()]).optional(),
    brand_colors: z
      .union([z.object({}).partial().passthrough(), z.null()])
      .optional(),
    admin_email: z.string().email(),
    admin_name: z.string(),
  })
  .passthrough();
const CreateOrgResponse = z
  .object({
    id: z.string(),
    name: z.string(),
    slug: z.string(),
    email_domain: z.string(),
    is_active: z.boolean(),
    admin_email: z.string(),
    admin_temp_password: z.string(),
    note: z
      .string()
      .optional()
      .default(
        "Share the temporary password with the Org Admin securely; they must change it at first login."
      ),
  })
  .passthrough();
const UserResponse = z
  .object({
    id: z.string(),
    email: z.string(),
    name: z.string(),
    role: z.string(),
    phone: z.union([z.string(), z.null()]),
    is_active: z.boolean(),
    department: z.union([z.string(), z.null()]).optional(),
    designation: z.union([z.string(), z.null()]).optional(),
    whatsapp_number: z.union([z.string(), z.null()]).optional(),
    max_open_tasks: z.union([z.number(), z.null()]).optional(),
    working_days: z.union([z.array(z.string()), z.null()]).optional(),
    require_action_item_review: z.union([z.boolean(), z.null()]).optional(),
  })
  .passthrough();
const CreateUserRequest = z
  .object({
    email: z.string().email(),
    name: z.string().min(2),
    role: z.string(),
    phone: z.union([z.string(), z.null()]).optional(),
    department: z.union([z.string(), z.null()]).optional(),
    designation: z.union([z.string(), z.null()]).optional(),
    whatsapp_number: z.union([z.string(), z.null()]).optional(),
    max_open_tasks: z.union([z.number(), z.null()]).optional(),
    working_days: z.union([z.array(z.string()), z.null()]).optional(),
  })
  .passthrough();
const UpdateUserRequest = z
  .object({
    name: z.union([z.string(), z.null()]),
    role: z.union([z.string(), z.null()]),
    phone: z.union([z.string(), z.null()]),
    is_active: z.union([z.boolean(), z.null()]),
    require_action_item_review: z.union([z.boolean(), z.null()]),
    department: z.union([z.string(), z.null()]),
    designation: z.union([z.string(), z.null()]),
    whatsapp_number: z.union([z.string(), z.null()]),
    max_open_tasks: z.union([z.number(), z.null()]),
    working_days: z.union([z.array(z.string()), z.null()]),
  })
  .partial()
  .passthrough();
const ProgramRequest = z
  .object({
    name: z.string(),
    code: z.string().min(1).max(50),
    description: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const PricingItem = z
  .object({
    code: z.string(),
    label: z.string(),
    unit: z.string().optional().default("-"),
    unit_price: z.number().gte(0),
    default_quantity: z.union([z.number(), z.null()]).optional(),
    notes: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const PricingRequest = z
  .object({
    currency: z.string().optional().default("INR"),
    items: z.array(PricingItem).min(1),
  })
  .passthrough();
const ProposalTemplateRequest = z
  .object({
    name: z.string(),
    body_md: z.string().min(20),
    make_current: z.boolean().optional().default(true),
  })
  .passthrough();
const Body_add_proposal_template_docx_api_v1_admin_programs__program_id__proposal_templates_docx_post =
  z
    .object({
      name: z.string(),
      make_current: z.boolean().optional().default(true),
      flow: z.string().optional().default("simple"),
      file: z.string(),
    })
    .passthrough();
const SavePlanRequest = z
  .object({ plan: z.object({}).partial().passthrough() })
  .passthrough();
const MessageTemplateRequest = z
  .object({
    kind: z.string(),
    channel: z.string(),
    name: z.string(),
    subject: z.union([z.string(), z.null()]).optional(),
    body: z.string().min(10),
    make_current: z.boolean().optional().default(true),
  })
  .passthrough();
const DemoTeamRequest = z
  .object({
    name: z.string(),
    lead_user_id: z.union([z.string(), z.null()]).optional(),
    media_rep_id: z.union([z.string(), z.null()]).optional(),
    sales_rep_id: z.union([z.string(), z.null()]).optional(),
    member_ids: z.array(z.string()).optional().default([]),
  })
  .passthrough();
const SettingsRequest = z
  .object({
    require_action_item_review: z.union([z.boolean(), z.null()]),
    auto_suggest_lead_state: z.union([z.boolean(), z.null()]),
    audio_retention_days: z.union([z.number(), z.null()]),
    transcript_retention_days: z.union([z.number(), z.null()]),
    llm_monthly_budget_usd: z.union([z.number(), z.null()]),
    timezone: z.union([z.string(), z.null()]),
    currency: z.union([z.string(), z.null()]),
    followup_cadence_days: z.union([z.number(), z.null()]),
    assignment_mode: z.union([z.string(), z.null()]),
    working_days: z.union([z.array(z.string()), z.null()]),
    workday_start: z.union([z.string(), z.null()]),
    workday_end: z.union([z.string(), z.null()]),
    quiet_hours_override_priority: z.union([z.string(), z.null()]),
    nudge_gap_days: z.union([z.object({}).partial().passthrough(), z.null()]),
    max_unanswered_nudges: z.union([z.number(), z.null()]),
    max_client_messages_per_week: z.union([z.number(), z.null()]),
    lead_cold_after_days: z.union([z.number(), z.null()]),
    high_load_caution_pct: z.union([z.number(), z.null()]),
    delivery_requires_advance: z.union([z.boolean(), z.null()]),
    scope_change_requires_confirmation: z.union([z.boolean(), z.null()]),
    client_report_day: z.union([z.string(), z.null()]),
    client_report_time: z.union([z.string(), z.null()]),
    payment_reminder_schedule: z.union([
      z.array(z.object({}).partial().passthrough()),
      z.null(),
    ]),
    reply_nudge_after_days: z.union([
      z.object({}).partial().passthrough(),
      z.null(),
    ]),
    ai_confidence_threshold: z.union([z.number(), z.null()]),
  })
  .partial()
  .passthrough();
const EmailIntegrationRequest = z
  .object({ smtp_username: z.string(), smtp_app_password: z.string() })
  .passthrough();
const WhatsAppIntegrationRequest = z
  .object({ access_token: z.string(), phone_number_id: z.string() })
  .passthrough();
const CalendarIntegrationRequest = z
  .object({
    calendar_id: z.string(),
    credentials_file: z.string(),
    meet_link: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const ResetRequest = z
  .object({
    dry_run: z.boolean().default(true),
    wipe_transactional: z.boolean().default(true),
    wipe_catalogue: z.boolean().default(false),
    wipe_org_config: z.boolean().default(false),
    confirm_org_name: z.union([z.string(), z.null()]),
  })
  .partial()
  .passthrough();
const LeadRequest = z
  .object({
    name: z.string().min(2).max(300),
    address: z.union([z.string(), z.null()]).optional(),
    city: z.union([z.string(), z.null()]).optional(),
    region: z.union([z.string(), z.null()]).optional(),
    website: z.union([z.string(), z.null()]).optional(),
    source: z.union([z.string(), z.null()]).optional(),
    notes: z.union([z.string(), z.null()]).optional(),
    owner_id: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const state = z.union([z.string(), z.null()]).optional();
const LeadUpdateRequest = z
  .object({
    name: z.union([z.string(), z.null()]),
    address: z.union([z.string(), z.null()]),
    city: z.union([z.string(), z.null()]),
    region: z.union([z.string(), z.null()]),
    website: z.union([z.string(), z.null()]),
    notes: z.union([z.string(), z.null()]),
    owner_id: z.union([z.string(), z.null()]),
    is_important: z.union([z.boolean(), z.null()]),
  })
  .partial()
  .passthrough();
const StateChangeRequest = z
  .object({
    state: z.string(),
    reason: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const ContactRequest = z
  .object({
    name: z.string(),
    title: z.union([z.string(), z.null()]).optional(),
    email: z.union([z.string(), z.null()]).optional(),
    phone: z.union([z.string(), z.null()]).optional(),
    is_primary: z.boolean().optional().default(false),
    draft_intro: z.boolean().optional().default(true),
  })
  .passthrough();
const Body_add_contact_from_card_api_v1_leads__lead_id__contacts_from_card_post =
  z
    .object({
      file: z.string(),
      draft_intro: z.boolean().optional().default(true),
      intro_channel: z.string().optional().default("email"),
    })
    .passthrough();
const IntelligenceRequest = z
  .object({
    note: z.string().min(2),
    category: z.union([z.string(), z.null()]).optional(),
    source: z.string().optional().default("typed"),
  })
  .passthrough();
const ConsentRequest = z
  .object({
    method: z.string().default("verbal"),
    note: z.union([z.string(), z.null()]),
    meeting_id: z.union([z.string(), z.null()]),
  })
  .partial()
  .passthrough();
const Body_upload_meeting_api_v1_meetings_upload_post = z
  .object({
    lead_id: z.string(),
    consent_confirmed: z.boolean(),
    duration_seconds: z.union([z.number(), z.null()]).optional(),
    title: z.union([z.string(), z.null()]).optional(),
    project_id: z.union([z.string(), z.null()]).optional(),
    file: z.string(),
  })
  .passthrough();
const ReviewItem = z
  .object({
    id: z.union([z.string(), z.null()]).optional(),
    title: z.string(),
    description: z.union([z.string(), z.null()]).optional(),
    keep: z.boolean().optional().default(true),
  })
  .passthrough();
const ReviewConfirmRequest = z
  .object({ items: z.array(ReviewItem) })
  .passthrough();
const ScheduleMeetingRequest = z
  .object({
    lead_id: z.string(),
    title: z.union([z.string(), z.null()]).optional(),
    started_at: z.string().datetime({ offset: true }),
    meeting_type: z.string().optional().default("first_visit"),
    project_id: z.union([z.string(), z.null()]).optional(),
    agent_id: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const MeetingNotesRequest = z
  .object({
    lead_id: z.string(),
    text: z.string(),
    title: z.union([z.string(), z.null()]).optional(),
    meeting_type: z.string().optional().default("first_visit"),
    project_id: z.union([z.string(), z.null()]).optional(),
    meeting_id: z.union([z.string(), z.null()]).optional(),
    consent_confirmed: z.boolean().optional().default(false),
    attendee_user_ids: z.array(z.string()).optional().default([]),
    attendee_stakeholder_ids: z.array(z.string()).optional().default([]),
  })
  .passthrough();
const CreateItemRequest = z
  .object({
    title: z.string().min(2).max(490),
    description: z.union([z.string(), z.null()]).optional(),
    lead_id: z.union([z.string(), z.null()]).optional(),
    owner_id: z.union([z.string(), z.null()]).optional(),
    due_date: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const UpdateItemRequest = z
  .object({
    title: z.union([z.string(), z.null()]),
    description: z.union([z.string(), z.null()]),
    status: z.union([z.string(), z.null()]),
    owner_id: z.union([z.string(), z.null()]),
    due_date: z.union([z.string(), z.null()]),
    result_note: z.union([z.string(), z.null()]),
  })
  .partial()
  .passthrough();
const BuildProposalRequest = z
  .object({
    lead_id: z.string(),
    program_id: z.string(),
    template_id: z.union([z.string(), z.null()]).optional(),
    context_summary: z.union([z.string(), z.null()]).optional(),
    quantities: z.union([z.record(z.number()), z.null()]).optional(),
    project_id: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const EditProposalRequest = z
  .object({ instruction: z.string().min(3) })
  .passthrough();
const Body_upload_manual_revision_api_v1_proposals__proposal_id__upload_revision_post =
  z.object({ file: z.string() }).passthrough();
const ApproveSendRequest = z
  .object({
    to_address: z.string(),
    cc: z.array(z.string()).optional().default([]),
    extra_note: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const RejectRequest = z
  .object({ reason: z.union([z.string(), z.null()]) })
  .partial()
  .passthrough();
const CreateFollowUpRequest = z
  .object({
    lead_id: z.string(),
    due_date: z.string(),
    channel: z.string().optional().default("email"),
    note: z.union([z.string(), z.null()]).optional(),
    owner_id: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const app__api__followups__CompleteRequest = z
  .object({
    sent_message_id: z.union([z.string(), z.null()]),
    note: z.union([z.string(), z.null()]),
    schedule_next: z.boolean().default(true),
  })
  .partial()
  .passthrough();
const CreateDemoRequest = z
  .object({
    lead_id: z.string(),
    scheduled_date: z.string(),
    scheduled_time: z.union([z.string(), z.null()]).optional(),
    team_id: z.union([z.string(), z.null()]).optional(),
    notes: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const UpdateDemoRequest = z
  .object({
    scheduled_date: z.union([z.string(), z.null()]),
    scheduled_time: z.union([z.string(), z.null()]),
    team_id: z.union([z.string(), z.null()]),
    status: z.union([z.string(), z.null()]),
    notes: z.union([z.string(), z.null()]),
  })
  .partial()
  .passthrough();
const CommandRequest = z
  .object({
    text: z.string().min(1).max(4000),
    session_id: z.union([z.string(), z.null()]).optional(),
    lead_id: z.union([z.string(), z.null()]).optional(),
    proposal_id: z.union([z.string(), z.null()]).optional(),
    meeting_id: z.union([z.string(), z.null()]).optional(),
    agent: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const CommandResponse = z
  .object({
    agent: z.string(),
    reply: z.string(),
    actions: z.array(z.object({}).partial().passthrough()),
    pending_approvals: z.array(z.object({}).partial().passthrough()),
    session_id: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const TurnOut = z
  .object({
    role: z.string(),
    content: z.string(),
    agent: z.union([z.string(), z.null()]).optional(),
    at: z.string().datetime({ offset: true }),
  })
  .passthrough();
const DeviceRegisterRequest = z
  .object({
    fcm_token: z.string(),
    platform: z.string().optional().default("android"),
    app_version: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const Body_dictate_api_v1_dictate_post = z
  .object({ file: z.string() })
  .passthrough();
const EraseContactRequest = z.object({ contact_id: z.string() }).passthrough();
const MemberRequest = z
  .object({
    user_id: z.string(),
    role_in_project: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const StatusRequest = z
  .object({
    status: z.string(),
    reason: z.union([z.string(), z.null()]).optional(),
    revival_date: z.union([z.string(), z.null()]).optional(),
    revival_context: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const PhaseShiftRequest = z
  .object({
    phase: z.string(),
    anchor_date: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const FeasibilityRequest = z
  .object({
    date_from: z.string().datetime({ offset: true }),
    date_to: z.string().datetime({ offset: true }),
  })
  .passthrough();
const StakeholderRequest = z
  .object({
    contact_id: z.string(),
    role_at_client: z.union([z.string(), z.null()]).optional(),
    influence: z.union([z.string(), z.null()]).optional(),
    preferred_channel: z.string().optional().default("email"),
    preferred_language: z.string().optional().default("english"),
    receives_progress_updates: z.boolean().optional().default(false),
    do_not_contact: z.boolean().optional().default(false),
  })
  .passthrough();
const ResolveConflictRequest = z
  .object({ resolution_note: z.string().min(2) })
  .passthrough();
const ChildProjectsRequest = z
  .object({
    branch_names: z.array(z.string()),
    invoicing_mode: z.string().optional().default("group"),
  })
  .passthrough();
const app__api__workflow__CompleteRequest = z
  .object({
    result_note: z.union([z.string(), z.null()]),
    completion_method: z.string().default("in_app"),
    deliverable_type: z.union([z.string(), z.null()]),
    deliverable_title: z.union([z.string(), z.null()]),
    deliverable_content_md: z.union([z.string(), z.null()]),
    deliverable_file_path: z.union([z.string(), z.null()]),
  })
  .partial()
  .passthrough();
const DeclineRequest = z
  .object({
    reason: z.string().default("other"),
    note: z.union([z.string(), z.null()]),
  })
  .partial()
  .passthrough();
const BlockRequest = z.object({ reason: z.string().min(2) }).passthrough();
const ProgressRequest = z
  .object({
    percent: z.number().int().gte(0).lte(100),
    note: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const NewDateRequest = z
  .object({
    new_due: z.string().datetime({ offset: true }),
    reason: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const SplitRequest = z
  .object({ parts: z.array(z.object({}).partial().passthrough()).min(2) })
  .passthrough();
const VendorPromiseRequest = z
  .object({
    vendor_name: z.string(),
    promised_date: z.string().datetime({ offset: true }),
    chase_contact_user_id: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const VendorSlipRequest = z
  .object({
    new_promised_date: z.string().datetime({ offset: true }),
    note: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const DecideRequest = z
  .object({
    approve: z.boolean(),
    note: z.union([z.string(), z.null()]).optional(),
    allow_blanks: z.boolean().optional().default(false),
  })
  .passthrough();
const ConfirmBatchRequest = z
  .object({
    assignment_ids: z.array(z.string()),
    overrides: z.record(z.string()).optional(),
  })
  .passthrough();
const InboundRequest = z
  .object({
    channel: z.string().optional().default("email"),
    from_address: z.string(),
    to_address: z.union([z.string(), z.null()]).optional(),
    subject: z.union([z.string(), z.null()]).optional(),
    body: z.string(),
  })
  .passthrough();
const TriageResolveRequest = z
  .object({
    contact_id: z.union([z.string(), z.null()]),
    mark_processed: z.boolean().default(true),
    note: z.union([z.string(), z.null()]),
    intent: z.union([z.string(), z.null()]),
    project_id: z.union([z.string(), z.null()]),
  })
  .partial()
  .passthrough();
const IncidentFixRequest = z
  .object({ fix_tasks: z.array(z.object({}).partial().passthrough()) })
  .partial()
  .passthrough();
const IncidentResolveRequest = z
  .object({ lesson: z.string().min(2) })
  .passthrough();
const DraftRequest = z
  .object({
    contact_id: z.string(),
    kind: z.string().optional().default("follow_up"),
    purpose: z.string().optional().default("manual message"),
    project_id: z.union([z.string(), z.null()]).optional(),
    channel: z.union([z.string(), z.null()]).optional(),
    subject: z.union([z.string(), z.null()]).optional(),
    instruction: z.union([z.string(), z.null()]).optional(),
    facts: z.object({}).partial().passthrough().optional(),
    urgent: z.boolean().optional().default(false),
  })
  .passthrough();
const InvoiceRequest = z
  .object({
    project_id: z.string(),
    kind: z.string().optional().default("full"),
    advance_pct: z.number().optional().default(50),
    due_in_days: z.number().int().optional().default(14),
    sent_to_stakeholder_id: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const PaymentRequest = z
  .object({
    amount: z.number().gt(0),
    method: z.union([z.string(), z.null()]).optional(),
    note: z.union([z.string(), z.null()]).optional(),
    received_on: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const VendorRequest = z
  .object({
    name: z.string(),
    contact_name: z.union([z.string(), z.null()]).optional(),
    phone: z.union([z.string(), z.null()]).optional(),
    email: z.union([z.string(), z.null()]).optional(),
    category: z.union([z.string(), z.null()]).optional(),
    notes: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const LeaveRequest = z
  .object({ user_id: z.string(), leave_from: z.string(), leave_to: z.string() })
  .passthrough();
const BookingRequest = z
  .object({
    user_id: z.string(),
    kind: z.string(),
    date_from: z.string(),
    date_to: z.string(),
    project_id: z.union([z.string(), z.null()]).optional(),
    note: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const DeliverableRequest = z
  .object({
    project_id: z.string(),
    type: z.string(),
    title: z.union([z.string(), z.null()]).optional(),
    content_md: z.union([z.string(), z.null()]).optional(),
    file_path: z.union([z.string(), z.null()]).optional(),
    source: z.string().optional().default("manual_upload"),
    linked_action_item_id: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const PlaybookRequest = z
  .object({
    program_id: z.string(),
    phase: z.string(),
    entries: z.array(z.object({}).partial().passthrough()),
  })
  .passthrough();
const SuggestionDecision = z.object({ accept: z.boolean() }).passthrough();
const ApprovalRuleRequest = z
  .object({
    entity_type: z.string(),
    condition: z.object({}).partial().passthrough().optional(),
    rank: z.number().int().optional().default(100),
    approver_role: z.string(),
    fallback_role: z.union([z.string(), z.null()]).optional(),
    recommender_role: z.union([z.string(), z.null()]).optional(),
    joint_with_role: z.union([z.string(), z.null()]).optional(),
    joint_condition: z
      .union([z.object({}).partial().passthrough(), z.null()])
      .optional(),
    auto_approve: z.boolean().optional().default(false),
    expires_hours: z.number().optional().default(48),
    description: z.union([z.string(), z.null()]).optional(),
  })
  .passthrough();
const SkillRequest = z
  .object({
    user_id: z.string(),
    skill: z.string(),
    level: z.string().optional().default("good"),
  })
  .passthrough();

export const schemas = {
  LoginRequest,
  LoginResponse,
  ValidationError,
  HTTPValidationError,
  MeResponse,
  ChangePasswordRequest,
  AppPasswordRequest,
  OrgResponse,
  CreateOrgRequest,
  CreateOrgResponse,
  UserResponse,
  CreateUserRequest,
  UpdateUserRequest,
  ProgramRequest,
  PricingItem,
  PricingRequest,
  ProposalTemplateRequest,
  Body_add_proposal_template_docx_api_v1_admin_programs__program_id__proposal_templates_docx_post,
  SavePlanRequest,
  MessageTemplateRequest,
  DemoTeamRequest,
  SettingsRequest,
  EmailIntegrationRequest,
  WhatsAppIntegrationRequest,
  CalendarIntegrationRequest,
  ResetRequest,
  LeadRequest,
  state,
  LeadUpdateRequest,
  StateChangeRequest,
  ContactRequest,
  Body_add_contact_from_card_api_v1_leads__lead_id__contacts_from_card_post,
  IntelligenceRequest,
  ConsentRequest,
  Body_upload_meeting_api_v1_meetings_upload_post,
  ReviewItem,
  ReviewConfirmRequest,
  ScheduleMeetingRequest,
  MeetingNotesRequest,
  CreateItemRequest,
  UpdateItemRequest,
  BuildProposalRequest,
  EditProposalRequest,
  Body_upload_manual_revision_api_v1_proposals__proposal_id__upload_revision_post,
  ApproveSendRequest,
  RejectRequest,
  CreateFollowUpRequest,
  app__api__followups__CompleteRequest,
  CreateDemoRequest,
  UpdateDemoRequest,
  CommandRequest,
  CommandResponse,
  TurnOut,
  DeviceRegisterRequest,
  Body_dictate_api_v1_dictate_post,
  EraseContactRequest,
  MemberRequest,
  StatusRequest,
  PhaseShiftRequest,
  FeasibilityRequest,
  StakeholderRequest,
  ResolveConflictRequest,
  ChildProjectsRequest,
  app__api__workflow__CompleteRequest,
  DeclineRequest,
  BlockRequest,
  ProgressRequest,
  NewDateRequest,
  SplitRequest,
  VendorPromiseRequest,
  VendorSlipRequest,
  DecideRequest,
  ConfirmBatchRequest,
  InboundRequest,
  TriageResolveRequest,
  IncidentFixRequest,
  IncidentResolveRequest,
  DraftRequest,
  InvoiceRequest,
  PaymentRequest,
  VendorRequest,
  LeaveRequest,
  BookingRequest,
  DeliverableRequest,
  PlaybookRequest,
  SuggestionDecision,
  ApprovalRuleRequest,
  SkillRequest,
};
