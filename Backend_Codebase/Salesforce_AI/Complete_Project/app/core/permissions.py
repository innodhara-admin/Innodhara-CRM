"""Role-based access control — the access matrix from doc §13.

Checks are centralised here so finer-grained roles can be added later (§13.1)
without touching endpoints.
"""
from __future__ import annotations

from app.core.constants import Role

# Permission -> roles allowed. Super Admin is intentionally absent from all
# org-data permissions: the platform operator cannot read private sales data.
_MATRIX: dict[str, set[Role]] = {
    # Meetings & sales work
    # The relationship manager records meetings and writes to clients, because
    # keeping in touch is the whole job. They are deliberately absent from
    # `manage_leads` and `send_proposal`: an RM must not move a lead through
    # the sales states or price anything.
    "record_meeting": {
        Role.SALES_AGENT, Role.SALES_LEAD, Role.ORG_ADMIN,
        Role.RELATIONSHIP_MANAGER,
    },
    "send_proposal": {Role.SALES_AGENT, Role.SALES_LEAD, Role.ORG_ADMIN},
    "manage_leads": {Role.SALES_AGENT, Role.SALES_LEAD, Role.ORG_ADMIN},
    "view_leads": {
        Role.SALES_AGENT, Role.SALES_LEAD, Role.ORG_ADMIN,
        Role.OPERATIONS_AGENT, Role.OPERATIONS_LEAD,
        Role.RELATIONSHIP_MANAGER,
    },
    "send_messages": {
        Role.SALES_AGENT, Role.SALES_LEAD, Role.ORG_ADMIN,
        Role.RELATIONSHIP_MANAGER,
    },
    # Tasks — reassignment scope is refined in can_reassign_task()
    "manage_tasks": {
        Role.SALES_AGENT, Role.SALES_LEAD, Role.ORG_ADMIN,
        Role.OPERATIONS_AGENT, Role.OPERATIONS_LEAD,
        Role.RELATIONSHIP_MANAGER,
    },
    # F51 — confirming the org's AI assignment batch is a LEAD's job, and the
    # spec says so four times over: org_settings.assignment_mode ("lead_confirm
    # = the phase lead confirms each batch before anyone is notified"), the
    # `assignments` table ("the lead's batch screen flips these rows"),
    # Workflow 9 step 5 ("the phase lead ... gets a batch confirmation") and
    # Roles §5.4 ("Confirming assignment batches — the phase lead").
    # `/assignments/confirm-batch` was open to any org member, and this org runs
    # in lead_confirm mode with the card offered on an agent's own Home screen.
    # Note this is a genuinely role-shaped control, unlike the task-lifecycle
    # half of F51, where the missing control was ownership.
    "confirm_assignments": {Role.SALES_LEAD, Role.OPERATIONS_LEAD, Role.ORG_ADMIN},
    # Demos
    "view_demos": {
        Role.SALES_AGENT, Role.SALES_LEAD, Role.ORG_ADMIN,
        Role.OPERATIONS_AGENT, Role.OPERATIONS_LEAD,
        Role.RELATIONSHIP_MANAGER,
    },
    "schedule_demos": {Role.OPERATIONS_LEAD, Role.ORG_ADMIN, Role.SALES_LEAD},
    "update_demo_status": {Role.OPERATIONS_AGENT, Role.OPERATIONS_LEAD, Role.ORG_ADMIN},
    # Relationship management
    # Handing a finished client to a relationship manager is a sales-side
    # decision, so the roles here are the sales ones; WHICH lead a given
    # person may hand over is an ownership question, answered on the endpoint
    # by `can_change_lead_state` rather than by this matrix.
    "assign_relationship_manager": {
        Role.SALES_AGENT, Role.SALES_LEAD, Role.ORG_ADMIN,
    },
    # The RM's own screens, and accepting the "this looks like a new
    # opportunity" card. Not held by sales: a sales agent who wants a client
    # back asks the RM, or the org admin steps in.
    "manage_relationships": {Role.RELATIONSHIP_MANAGER, Role.ORG_ADMIN},
    # Org administration
    "edit_pricing": {Role.ORG_ADMIN},
    "manage_programs": {Role.ORG_ADMIN},
    "manage_templates": {Role.ORG_ADMIN},
    "manage_staff": {Role.ORG_ADMIN},
    "manage_teams": {Role.ORG_ADMIN, Role.OPERATIONS_LEAD},
    "manage_settings": {Role.ORG_ADMIN},
    "view_audit": {Role.ORG_ADMIN},
    "erase_personal_data": {Role.ORG_ADMIN},
    # Field location (2 Oct 2026): where the sales team was when they opened
    # the app. The org admin only -- the developer's decision; a sales lead
    # sees no map.
    "track_locations": {Role.ORG_ADMIN},
    # Sales head (23 Oct 2026): the read-only /insights screens -- pipeline,
    # outlook, the team's report cards, field readings, AI spend. The sales
    # head alone; the org admin's app is unchanged
    # (docs/superpowers/specs/2026-10-23-sales-head-design.md §5).
    "view_sales_insights": {Role.SALES_HEAD},
    # Platform level
    "create_organisation": {Role.SUPER_ADMIN},
    "platform_stats": {Role.SUPER_ADMIN},
}


def has_permission(role: str, permission: str) -> bool:
    allowed = _MATRIX.get(permission, set())
    try:
        return Role(role) in allowed
    except ValueError:
        return False


def can_leave_cold_calling(
    role: str, actor_id: str, owner_id: str | None
) -> bool:
    """Who may move a lead out of COLD_CALLING (to OPEN or LOST_FOR_NOW).

    Pre-sales is the one place where ownership, not role, decides. The owner
    made the calls; only they know whether the response was worth pursuing,
    so only they may answer that question — a sales lead cannot overrule it.

    This is deliberately narrow. Every transition from OPEN onward keeps the
    plain `manage_leads` check it has always had, so the established flow is
    untouched.

    The org admin retains a break-glass path for the case nobody plans for.
    An owner who has left is not a reason to widen this: `PATCH /leads/{id}`
    already lets anyone with `manage_leads` reassign `owner_id`, and the new
    owner can then open the lead.
    """
    if role == Role.ORG_ADMIN.value:
        return True
    return owner_id is not None and owner_id == actor_id


def can_change_lead_state(
    role: str, actor_id: str, owner_id: str | None
) -> bool:
    """Who may move a lead through the states from OPEN onward.

    `manage_leads` alone used to be the whole check, and every sales agent
    holds `manage_leads` -- so any agent could drive any colleague's lead all
    the way to closed. The permission says "this person works leads". It never
    said "this person works *this* lead".

    A sales lead may move any lead: they run the team and cover absences. An
    agent may move the leads they own. The org admin keeps the same
    break-glass path they hold everywhere else.

    A lead with no owner is not an open invitation -- an agent who wants it
    takes ownership first through `PATCH /leads/{id}`, which `manage_leads`
    already guards. That keeps "who may move this" answerable from one field.

    The pre-sales boundary is stricter still and sits on top of this:
    `can_leave_cold_calling` excludes even the sales lead, because only the
    person who made the calls knows what was said.
    """
    if role in (Role.ORG_ADMIN.value, Role.SALES_LEAD.value):
        return True
    return owner_id is not None and owner_id == actor_id


def can_reassign_task(
    role: str, actor_id: str, task_owner_id: str | None, same_team: bool
) -> bool:
    """Doc §13 matrix: Sales Agent — own only; Sales Lead — whole team; Admin — yes."""
    if role == Role.ORG_ADMIN.value:
        return True
    if role in (Role.SALES_LEAD.value, Role.OPERATIONS_LEAD.value):
        return same_team or task_owner_id == actor_id or task_owner_id is None
    return task_owner_id == actor_id or task_owner_id is None
