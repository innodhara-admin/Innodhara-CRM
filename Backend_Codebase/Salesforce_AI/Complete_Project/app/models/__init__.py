"""Model registry — importing this module registers all tables on Base."""
from app.models.action_item import ActionItem
from app.models.assistant import AssistantPendingAction, AssistantTurn
from app.models.audit import AuditLog, IdempotencyRecord, LlmUsage
from app.models.comms import Approval, ApprovalRule, InboundMessage, Thread
from app.models.demo import Demo, DemoTeam, DemoTeamMember
from app.models.email_template import (
    EmailFillSession,
    EmailTemplate,
    EmailTemplateAttachment,
)
from app.models.finance import Deliverable, Invoice, Payment, Vendor
from app.models.followup import FollowUp
from app.models.insight import InsightSnapshot
from app.models.job import JobRecord
from app.models.lead import (
    ConsentRecord,
    Contact,
    Lead,
    LeadStateHistory,
    ClientIntelligence,
)
from app.models.location import LocationPing
from app.models.meeting import Meeting, Transcript
from app.models.memory import MemoryChunk
from app.models.messaging import MessageDeliveryLog, OutboundMessage
from app.models.mou import MouDocument
from app.models.organisation import Organisation, OrgSettings
from app.models.program import (
    MessageTemplate,
    PricingTable,
    Program,
    ProposalTemplate,
    ProposalTemplateDoc,
)
from app.models.project import (
    ActionPlan,
    ClientCommitment,
    Conflict,
    Playbook,
    PlaybookSuggestion,
    Project,
    ProjectMember,
    Stakeholder,
)
from app.models.proposal import Proposal, ProposalRevision
from app.models.proposal_fill import ProposalFillSession
from app.models.relationship import LeadCycle, RelationshipEngagement
from app.models.resource import ResourceBooking
from app.models.scheduled_meeting import ScheduledMeeting
from app.models.user import DeviceToken, Notification, User, UserSkill
from app.models.work import (
    AIDecision,
    Assignment,
    Digest,
    Incident,
    ProgressEvent,
    Reminder,
)

__all__ = [
    "ActionItem",
    "ActionPlan",
    "AIDecision",
    "Approval",
    "ApprovalRule",
    "Assignment",
    "AssistantPendingAction",
    "AssistantTurn",
    "AuditLog",
    "ClientCommitment",
    "Conflict",
    "ConsentRecord",
    "Contact",
    "Deliverable",
    "Demo",
    "EmailFillSession",
    "EmailTemplate",
    "EmailTemplateAttachment",
    "DemoTeam",
    "DemoTeamMember",
    "Digest",
    "FollowUp",
    "IdempotencyRecord",
    "InboundMessage",
    "Incident",
    "InsightSnapshot",
    "Invoice",
    "JobRecord",
    "Lead",
    "LeadCycle",
    "LeadStateHistory",
    "LocationPing",
    "LlmUsage",
    "MemoryChunk",
    "MessageDeliveryLog",
    "MessageTemplate",
    "Meeting",
    "MouDocument",
    "DeviceToken",
    "Notification",
    "Organisation",
    "OrgSettings",
    "OutboundMessage",
    "Payment",
    "Playbook",
    "PlaybookSuggestion",
    "PricingTable",
    "Program",
    "ProgressEvent",
    "Project",
    "ProjectMember",
    "Proposal",
    "ProposalFillSession",
    "ProposalRevision",
    "ProposalTemplate",
    "ProposalTemplateDoc",
    "RelationshipEngagement",
    "Reminder",
    "ResourceBooking",
    "ScheduledMeeting",
    "ClientIntelligence",
    "Stakeholder",
    "Thread",
    "Transcript",
    "User",
    "UserSkill",
    "Vendor",
]
