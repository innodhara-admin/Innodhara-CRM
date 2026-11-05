"""Domain enumerations shared by models, schemas, services and agents."""
from enum import Enum


class Role(str, Enum):
    SUPER_ADMIN = "super_admin"        # platform level — cannot read org sales data
    ORG_ADMIN = "org_admin"
    SALES_AGENT = "sales_agent"
    SALES_LEAD = "sales_lead"
    OPERATIONS_AGENT = "operations_agent"
    OPERATIONS_LEAD = "operations_lead"
    # Looks after a client after the selling and the delivery are done: keeps
    # in touch, and notices when they are ready to buy again. Deliberately not
    # a sales role -- an RM holds no `manage_leads` and cannot move a lead
    # through the sales states.
    RELATIONSHIP_MANAGER = "relationship_manager"
    # Runs the whole sales side and watches it (23 Oct 2026): reads the
    # /insights screens and nothing else. Holds no permission that changes a
    # record (docs/superpowers/specs/2026-10-23-sales-head-design.md §5).
    SALES_HEAD = "sales_head"


ORG_ROLES = {
    Role.ORG_ADMIN,
    Role.SALES_AGENT,
    Role.SALES_LEAD,
    Role.OPERATIONS_AGENT,
    Role.OPERATIONS_LEAD,
    Role.RELATIONSHIP_MANAGER,
    Role.SALES_HEAD,
}


class LeadState(str, Enum):
    """'Active and Important' is stored as ACTIVE + is_important flag (doc §4).

    COLD_CALLING is the pre-sales entry state: a lead has an owner but nobody
    has reached the school yet. It is NOT related to COLD, which sits at the
    other end of the lifecycle and means a lead we were working has gone
    quiet. Only the owner may move a lead out of COLD_CALLING.
    """
    COLD_CALLING = "cold_calling"
    OPEN = "open"
    ACTIVE = "active"
    COLD = "cold"
    EXECUTION_IN_PROGRESS = "execution_in_progress"
    CLIENT_EXECUTION_IN_PROGRESS = "client_execution_in_progress"
    CLOSED = "closed"
    LOST_FOR_NOW = "lost_for_now"


# Allowed lead state transitions (solid + dashed arrows in Figure 2).
LEAD_STATE_TRANSITIONS: dict[LeadState, set[LeadState]] = {
    # Pre-sales: the owner either got a response worth pursuing, or did not.
    # There is deliberately no COLD_CALLING -> ACTIVE shortcut; the usual flow
    # begins at OPEN and is unchanged from there on.
    LeadState.COLD_CALLING: {LeadState.OPEN, LeadState.LOST_FOR_NOW},
    LeadState.OPEN: {LeadState.ACTIVE, LeadState.COLD, LeadState.LOST_FOR_NOW},
    LeadState.ACTIVE: {
        LeadState.EXECUTION_IN_PROGRESS,
        LeadState.COLD,
        LeadState.LOST_FOR_NOW,
    },
    LeadState.COLD: {LeadState.ACTIVE, LeadState.OPEN, LeadState.LOST_FOR_NOW},
    LeadState.EXECUTION_IN_PROGRESS: {
        LeadState.CLIENT_EXECUTION_IN_PROGRESS,
        LeadState.LOST_FOR_NOW,
        LeadState.ACTIVE,
    },
    LeadState.CLIENT_EXECUTION_IN_PROGRESS: {
        LeadState.CLOSED,
        LeadState.EXECUTION_IN_PROGRESS,
        LeadState.LOST_FOR_NOW,
    },
    # A client who comes back. Deliberately to OPEN and never to
    # COLD_CALLING: cold calling exists to find out whether there is any
    # interest at all, and with a client we have already delivered for we
    # know there is. Reached either by a relationship manager accepting an
    # opportunity, or by a person who simply knows the client called back.
    LeadState.CLOSED: {LeadState.LOST_FOR_NOW, LeadState.OPEN},
    LeadState.LOST_FOR_NOW: {LeadState.OPEN, LeadState.ACTIVE},  # retry later
}


class MeetingStatus(str, Enum):
    SCHEDULED = "scheduled"             # booked in advance, not yet held
    UPLOADED = "uploaded"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    EXTRACTING = "extracting"
    REVIEW_PENDING = "review_pending"   # action items waiting for human review
    COMPLETED = "completed"
    FAILED = "failed"


class MeetingType(str, Enum):
    FIRST_VISIT = "first_visit"
    NEGOTIATION = "negotiation"
    KICKOFF = "kickoff"
    REVIEW = "review"
    CLOSURE = "closure"
    # A catch-up with a client we have already delivered for. Nobody is
    # selling. The pipeline treats it completely differently: a summary and a
    # suggested next touch, and none of the sales machinery.
    RELATIONSHIP = "relationship"


class ActionItemStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"      # no longer needed — kept, with reason
    DECLINED = "declined"        # assignee said no; being reassigned
    SUPERSEDED = "superseded"    # a re-plan replaced it (superseded_by points on)


class ProposalStatus(str, Enum):
    DRAFT = "draft"
    INTERNAL_REVIEW = "internal_review"          # waiting for internal approver
    APPROVED_INTERNALLY = "approved_internally"  # cleared to send
    PENDING_APPROVAL = "pending_approval"        # legacy alias of internal_review
    SENT = "sent"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class MessageChannel(str, Enum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"


class MessageKind(str, Enum):
    INTRO = "intro"
    PROPOSAL = "proposal"
    FOLLOW_UP = "follow_up"
    PROGRESS_UPDATE = "progress_update"
    REPLY = "reply"
    REPORT = "report"
    INVOICE = "invoice"
    NOTIFICATION = "notification"
    # An email drafted from an uploaded Word email template (28 Oct 2026)
    # whose category names no older kind.
    TEMPLATE_EMAIL = "template_email"


class MessageStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"   # human one-tap approval gate
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    REJECTED = "rejected"                   # human declined the draft


class TemplateKind(str, Enum):
    INTRO = "intro"
    FOLLOW_UP = "follow_up"


# Word email templates (28 Oct 2026). Separate from TemplateKind on purpose:
# the card scan and the go-live checklist are built on TemplateKind, and the
# developer asked for both to stay exactly as they are.
class EmailTemplateType(str, Enum):
    COMMON = "common"      # grouped by category
    PRODUCT = "product"    # grouped by product (programme)


class BuiltDocument(str, Enum):
    """What a product email carries from the client's own records."""

    NONE = "none"
    PROPOSAL = "proposal"
    MOU = "mou"


#: The common-email categories offered first, taken from the developer's own
#: document. Admins may add more; these are suggestions, not a closed list.
EMAIL_CATEGORY_PRESETS: dict[str, str] = {
    "intro": "Intro",
    "meeting_confirmation": "Meeting confirmation",
    "after_meeting": "After meeting",
    "follow_up": "Follow-up",
    "final_follow_up": "Final follow-up",
    "onboarding": "Onboarding",
}


class FollowUpStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    SKIPPED = "skipped"


class DemoStatus(str, Enum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"        # will retry
    DEAD_LETTER = "dead_letter"


class ContactSource(str, Enum):
    CARD = "card"
    MANUAL = "manual"
    MEETING = "meeting"


# ═════════════════════════════════════════════════════════════════════════════
# Workflow-design vocabulary (30-Workflows + Data-Model docs)
# ═════════════════════════════════════════════════════════════════════════════


class Department(str, Enum):
    SALES = "sales"
    OPERATIONS = "operations"
    ACCOUNTS = "accounts"
    # `find_department_lead` routes anything that is not operations or
    # accounts to the sales lead, so a relationship manager's overload and
    # escalation notices reach the sales lead without a branch of their own.
    # That is the intended reporting line, not an accident of the fallback.
    RELATIONSHIP = "relationship"


class EngagementStatus(str, Enum):
    """The life of one relationship engagement.

    ENDED and RETURNED_TO_SALES are both endings, kept apart because they mean
    different things to whoever reads the client's history later: one is a
    relationship that stopped, the other is a client who started buying again.
    """

    ACTIVE = "active"
    ENDED = "ended"
    RETURNED_TO_SALES = "returned_to_sales"


class CycleSource(str, Enum):
    """How a round of business started.

    COLD_CALL is the first round: nobody had spoken to this client before.
    RELATIONSHIP is every later one, where a relationship manager noticed they
    were ready to buy again — which is why those rounds skip cold calling
    entirely. We already know them.
    """

    COLD_CALL = "cold_call"
    RELATIONSHIP = "relationship"


class CycleOutcome(str, Enum):
    """How a round ended. RUNNING is the one that has not."""

    RUNNING = "running"
    CLOSED = "closed"
    LOST_FOR_NOW = "lost_for_now"


class OpportunityStatus(str, Enum):
    """Whether a client has hinted they want to buy again, and what a person
    decided about it. NONE is the ordinary state for most engagements."""

    NONE = "none"
    OPEN = "open"            # flagged by the AI, waiting for a person
    ACCEPTED = "accepted"    # a person agreed; sales have been told
    DISMISSED = "dismissed"  # a person looked and said no


class SkillLevel(str, Enum):
    BASIC = "basic"
    GOOD = "good"
    EXPERT = "expert"


SKILL_LEVEL_SCORE = {SkillLevel.EXPERT.value: 3, SkillLevel.GOOD.value: 2, SkillLevel.BASIC.value: 1}


class LostReason(str, Enum):
    BUDGET_TIMING = "budget_timing"
    CHOSE_COMPETITOR = "chose_competitor"
    NO_NEED = "no_need"
    OTHER = "other"


class ProjectStatus(str, Enum):
    PLANNING = "planning"
    PROPOSAL_STAGE = "proposal_stage"
    NEGOTIATION = "negotiation"
    AGREED = "agreed"
    PREPARATION = "preparation"
    DELIVERY = "delivery"
    PAYMENT_PENDING = "payment_pending"
    CLOSED = "closed"
    ON_HOLD = "on_hold"
    LOST = "lost"


class ProjectHealth(str, Enum):
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    DELAYED = "delayed"


class InvoicingMode(str, Enum):
    GROUP = "group"
    PER_BRANCH = "per_branch"


class Phase(str, Enum):
    SALES = "sales"
    PROPOSAL = "proposal"
    PREPARATION = "preparation"
    DELIVERY = "delivery"
    PAYMENT = "payment"
    CLOSURE = "closure"


# Which lead role confirms assignments / receives escalations for each phase.
PHASE_LEAD_ROLE: dict[str, str] = {
    Phase.SALES.value: Role.SALES_LEAD.value,
    Phase.PROPOSAL.value: Role.SALES_LEAD.value,
    Phase.PREPARATION.value: Role.OPERATIONS_LEAD.value,
    Phase.DELIVERY.value: Role.OPERATIONS_LEAD.value,
    Phase.PAYMENT.value: Role.OPERATIONS_LEAD.value,
    Phase.CLOSURE.value: Role.OPERATIONS_LEAD.value,
}


class TaskPriority(str, Enum):
    P1 = "P1"  # urgent — may break quiet hours and capacity caps
    P2 = "P2"  # normal
    P3 = "P3"  # low


PRIORITY_ORDER = {TaskPriority.P1.value: 1, TaskPriority.P2.value: 2, TaskPriority.P3.value: 3}


class AssignOn(str, Enum):
    PLAN_ACTIVATION = "plan_activation"
    WHEN_READY = "when_ready"


class TaskSource(str, Enum):
    MEETING = "meeting"
    CLIENT_REPLY = "client_reply"
    AI_REFINEMENT = "ai_refinement"
    PLAYBOOK = "playbook"
    MANUAL = "manual"


class CompletionMethod(str, Enum):
    IN_APP = "in_app"
    MANUAL_UPLOAD = "manual_upload"
    VOICE = "voice"
    EXTERNAL = "external"
    SYSTEM = "system"


class PlanStatus(str, Enum):
    DRAFT = "draft"                  # being built, or held by an open conflict
    PENDING_REVIEW = "pending_review"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class PlanTrigger(str, Enum):
    FIRST_MEETING = "first_meeting"
    NEW_MEETING = "new_meeting"
    CLIENT_REPLY = "client_reply"
    PROGRESS_REVIEW = "progress_review"
    PHASE_SHIFT = "phase_shift"
    MANUAL = "manual"


class CommitmentDirection(str, Enum):
    OURS = "ours"      # we promised the school
    THEIRS = "theirs"  # the school promised us


class CommitmentStatus(str, Enum):
    OPEN = "open"
    KEPT = "kept"
    BROKEN = "broken"
    RENEGOTIATED = "renegotiated"


class ConflictStatus(str, Enum):
    OPEN = "open"          # blocks the related re-plan
    RESOLVED = "resolved"


# Stakeholder roles are deliberately NOT an enum: the role is free-form text
# in the client's own vocabulary (principal, cto, procurement_head, store
# manager...), authored by the model's read of the discussion or by a human.
# Only `influence` below is a fixed vocabulary — it is what the engines act on.


class Influence(str, Enum):
    DECISION_MAKER = "decision_maker"
    INFLUENCER = "influencer"
    GATEKEEPER = "gatekeeper"


INFLUENCE_WEIGHT = {
    Influence.DECISION_MAKER.value: 3,
    Influence.GATEKEEPER.value: 2,
    Influence.INFLUENCER.value: 1,
}


class AssignmentStatus(str, Enum):
    PROPOSED = "proposed"            # waiting for lead confirmation
    ACCEPTED = "accepted"
    AUTO_ACCEPTED = "auto_accepted"  # org assignment_mode = auto
    DECLINED = "declined"
    OVERRIDDEN = "overridden"        # a human changed the AI's pick


class DeclineReason(str, Enum):
    BUSY = "busy"
    WRONG_SKILL = "wrong_skill"
    ON_SITE_ELSEWHERE = "on_site_elsewhere"
    OTHER = "other"


class ReminderTargetType(str, Enum):
    ACTION_ITEM = "action_item"
    FOLLOWUP = "followup"
    APPROVAL = "approval"
    CLIENT_COMMITMENT = "client_commitment"
    INVOICE = "invoice"


class EventType(str, Enum):
    """Core progress_events vocabulary — extendable; keep values stable."""

    TASK_DONE = "task_done"
    TASK_BLOCKED = "task_blocked"
    TASK_UNBLOCKED = "task_unblocked"
    TASK_OVERDUE = "task_overdue"
    TASK_ESCALATED = "task_escalated"
    TASK_DECLINED = "task_declined"
    TASK_CREATED = "task_created"
    TASK_REASSIGNED = "task_reassigned"
    TASK_CANCELLED = "task_cancelled"
    PLAN_ACTIVATED = "plan_activated"
    PLAN_HELD = "plan_held"
    MEETING_PROCESSED = "meeting_processed"
    REPLY_RECEIVED = "reply_received"
    MESSAGE_SENT = "message_sent"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_DECIDED = "approval_decided"
    DEAL_AGREED = "deal_agreed"
    PROPOSAL_SENT = "proposal_sent"
    PAYMENT_RECEIVED = "payment_received"
    INVOICE_SENT = "invoice_sent"
    INVOICE_OVERDUE = "invoice_overdue"
    DEMO_COMPLETED = "demo_completed"
    COMPLAINT_RECEIVED = "complaint_received"
    INCIDENT_RESOLVED = "incident_resolved"
    MEMBER_JOINED = "member_joined"
    MEMBER_LEFT = "member_left"
    LEAVE_RECORDED = "leave_recorded"
    USER_OVERLOADED = "user_overloaded"
    COMMITMENT_KEPT = "commitment_kept"
    COMMITMENT_BROKEN = "commitment_broken"
    COMMITMENT_RENEGOTIATED = "commitment_renegotiated"
    VENDOR_SLIP = "vendor_slip"
    PROJECT_HEALTH_CHANGED = "project_health_changed"
    PROJECT_STATUS_CHANGED = "project_status_changed"
    PROJECT_CREATED = "project_created"
    PROJECT_CLOSED = "project_closed"
    LEAD_REVIVED = "lead_revived"
    CONFLICT_RAISED = "conflict_raised"
    CONFLICT_RESOLVED = "conflict_resolved"
    DELIVERABLE_ADDED = "deliverable_added"
    ON_SITE_UPDATE = "on_site_update"


class IncidentSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IncidentStatus(str, Enum):
    OPEN = "open"
    FIXING = "fixing"
    RESOLVED = "resolved"


class DecisionType(str, Enum):
    ASSIGNMENT = "assignment"
    PLAN_UPDATE = "plan_update"
    DRAFT_MESSAGE = "draft_message"
    STATE_CHANGE = "state_change"
    CONFLICT_RAISED = "conflict_raised"
    ESCALATION = "escalation"
    FEASIBILITY = "feasibility"


class DigestKind(str, Enum):
    DAILY_USER = "daily_user"
    WEEKLY_PROJECT_INTERNAL = "weekly_project_internal"
    WEEKLY_PROJECT_CLIENT = "weekly_project_client"


class DeliverableType(str, Enum):
    PROPOSAL = "proposal"
    SYLLABUS = "syllabus"
    SCHEDULE = "schedule"
    INVOICE = "invoice"
    DAILY_REPORT = "daily_report"
    CLOSURE_REPORT = "closure_report"
    CERTIFICATES = "certificates"
    FEEDBACK_SUMMARY = "feedback_summary"
    PHOTO_SET = "photo_set"
    OTHER = "other"


class DeliverableSource(str, Enum):
    AI_GENERATED = "ai_generated"
    MANUAL_UPLOAD = "manual_upload"


class DeliverableStatus(str, Enum):
    DRAFT = "draft"
    INTERNAL_REVIEW = "internal_review"
    APPROVED = "approved"
    SENT = "sent"
    ACCEPTED = "accepted"


class InvoiceKind(str, Enum):
    ADVANCE = "advance"
    BALANCE = "balance"
    FULL = "full"


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    PART_PAID = "part_paid"
    PAID = "paid"
    OVERDUE = "overdue"
    DISPUTED = "disputed"


class PaymentMethod(str, Enum):
    CHEQUE = "cheque"
    TRANSFER = "transfer"
    UPI = "upi"
    CASH = "cash"


class BookingKind(str, Enum):
    DELIVERY = "delivery"
    DEMO = "demo"
    TRAVEL = "travel"
    LEAVE = "leave"
    HOLD = "hold"


class ThreadStatus(str, Enum):
    OPEN = "open"
    SETTLED = "settled"
    DORMANT = "dormant"


class InboundIntent(str, Enum):
    QUESTION = "question"
    CHANGE_REQUEST = "change_request"
    APPROVAL = "approval"          # yes to something we sent
    REJECTION = "rejection"
    COMPLAINT = "complaint"
    PAYMENT_INFO = "payment_info"
    SCHEDULING = "scheduling"
    ACKNOWLEDGEMENT = "acknowledgement"
    UNKNOWN = "unknown"


class ChangeType(str, Enum):
    PRICE = "price"
    CONTENT = "content"
    DATE = "date"
    SCOPE = "scope"
    OTHER = "other"


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class InboundStatus(str, Enum):
    NEW = "new"
    PROCESSED = "processed"
    NEEDS_HUMAN = "needs_human"  # AI understood too little to act
    TRIAGE = "triage"            # matched nothing — human sorts it


class ApprovalEntityType(str, Enum):
    OUTBOUND_MESSAGE = "outbound_message"
    PROPOSAL = "proposal"
    PRICE_CHANGE = "price_change"
    PLAN_CHANGE = "plan_change"
    INVOICE = "invoice"
    # A recorded meeting's plan, held for the person who recorded it to tap
    # "Approve plan" (entity_id = the meeting). Their yes then goes through
    # the plan_change rules like any other plan (1 Oct 2026).
    MEETING_PLAN = "meeting_plan"


class MeetingPlanState(str, Enum):
    """Where a recorded meeting's plan stands (`meetings.plan_state`)."""

    PLANNING = "planning"
    READY = "ready"                          # held, waiting for "Approve plan"
    APPROVED = "approved"                    # the plan is live
    SENT_FOR_APPROVAL = "sent_for_approval"  # a rule sent it to someone else
    NO_PLAN = "no_plan"                      # follow-ups only, or no change
    FAILED = "failed"
    DISCARDED = "discarded"                  # rejected from the Approvals inbox
    SUPERSEDED = "superseded"                # a newer plan replaced it first


class ApprovalStage(str, Enum):
    RECOMMEND = "recommend"
    DECIDE = "decide"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"    # with a note → redo loop
    EXPIRED = "expired"
    ESCALATED = "escalated"


class AssignmentMode(str, Enum):
    AUTO = "auto"
    LEAD_CONFIRM = "lead_confirm"


class TriggeredBy(str, Enum):
    TASK_COMPLETED = "task_completed"
    PLAN_UPDATED = "plan_updated"
    WEEKLY_REPORT = "weekly_report"
    INBOUND_REPLY = "inbound_reply"
    REMINDER_LADDER = "reminder_ladder"
    MANUAL = "manual"


# Special approver_role values in approval_rules beyond org roles.
APPROVER_THREAD_OWNER = "thread_owner"
AP_APPROVER_SENDER = "sender"
