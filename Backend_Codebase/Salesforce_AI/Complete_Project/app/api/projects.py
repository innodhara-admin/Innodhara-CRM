"""Project layer API: projects, members, stakeholders, plans, conflicts,
commitments, feasibility, timeline, briefs and chain deals."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_org_context, require_permission
from app.core.constants import (
    ActionItemStatus,
    EventType,
    Phase,
    ProjectStatus,
    Role,
)
from app.core.context import OrgContext
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.database import get_db
from app.engines import assistant_engine, events, planner_engine
from app.models.action_item import ActionItem
from app.models.base import utcnow
from app.models.lead import Contact, Lead
from app.models.project import (
    ActionPlan,
    ClientCommitment,
    Conflict,
    Project,
    ProjectMember,
    Stakeholder,
)
from app.models.user import User
from app.models.work import ProgressEvent

router = APIRouter(prefix="/projects", tags=["projects"])


async def _get_project(db: AsyncSession, ctx: OrgContext, project_id: str) -> Project:
    project = (
        await db.execute(
            select(Project).where(Project.org_id == ctx.org_id, Project.id == project_id)
        )
    ).scalar_one_or_none()
    if project is None:
        raise NotFoundError("Project not found")
    return project


def _project_dict(p: Project) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "lead_id": p.lead_id,
        "program_id": p.program_id,
        "objective": p.objective,
        "status": p.status,
        "status_reason": p.status_reason,
        "health": p.health,
        "health_reason": p.health_reason,
        "sales_owner_id": p.sales_owner_id,
        "ops_owner_id": p.ops_owner_id,
        "current_plan_version": p.current_plan_version,
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "target_end_date": p.target_end_date.isoformat() if p.target_end_date else None,
        "value_estimate": p.value_estimate,
        # F31: value_estimate travelled without the currency it is denominated
        # in, so the app had nothing to render but a hardcoded ₹. Additive key —
        # an older APK ignores it and behaves exactly as before.
        "currency": p.currency or "INR",
        "parent_project_id": p.parent_project_id,
        "invoicing_mode": p.invoicing_mode,
    }


@router.get("")
async def list_projects(
    status: str | None = None,
    lead_id: str | None = None,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Project).where(Project.org_id == ctx.org_id)
    if status:
        stmt = stmt.where(Project.status == status)
    if lead_id:
        stmt = stmt.where(Project.lead_id == lead_id)
    rows = (await db.execute(stmt.order_by(Project.created_at.desc()))).scalars().all()
    return [_project_dict(p) for p in rows]


@router.get("/resolve/{entity_type}/{entity_id}")
async def resolve_project_for_entity(
    entity_type: str,
    entity_id: str,
    ctx: OrgContext = Depends(require_permission("view_leads")),
    db: AsyncSession = Depends(get_db),
):
    """Which project does this conflict / plan belong to? (F58)

    Notifications carry only `entity_type` + `entity_id` (Data Model §2.5), and
    a conflict's screen is the project's Conflicts tab — so tapping one had
    nothing to navigate with and fell through to "this opens fully in a later
    phase", for a screen that has existed and worked since Act 11.

    A lookup rather than a new `notifications.project_id` column: additive, no
    migration, and it cannot make the 16 existing notify() call sites wrong.
    """
    from app.models.project import ActionPlan, Conflict

    model = {"conflict": Conflict, "action_plan": ActionPlan}.get(entity_type)
    if model is None:
        raise ValidationFailedError(
            f"'{entity_type}' does not belong to a project"
        )
    row = (
        await db.execute(
            select(model).where(model.org_id == ctx.org_id, model.id == entity_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError(f"No {entity_type} with that id")
    return {"project_id": row.project_id}


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    p = await _get_project(db, ctx, project_id)
    tasks = (
        await db.execute(
            select(ActionItem).where(ActionItem.project_id == p.id)
        )
    ).scalars().all()
    members = (
        await db.execute(
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == p.id, ProjectMember.left_at.is_(None))
        )
    ).all()
    stakeholders = (
        await db.execute(
            select(Stakeholder, Contact)
            .join(Contact, Contact.id == Stakeholder.contact_id)
            .where(Stakeholder.project_id == p.id)
        )
    ).all()
    commitments = (
        await db.execute(
            select(ClientCommitment).where(ClientCommitment.project_id == p.id)
        )
    ).scalars().all()
    out = _project_dict(p)
    out["tasks"] = [
        {
            "id": t.id, "title": t.title, "status": t.status,
            "assignee_id": t.assignee_id, "phase": t.phase, "priority": t.priority,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "blocked": t.blocked, "blocked_reason": t.blocked_reason,
            "visible_to_client": t.visible_to_client,
            "progress_percent": t.progress_percent,
            "assignment_reason": t.assignment_reason,
            "depends_on_ids": t.depends_on_ids,
        }
        for t in tasks
    ]
    out["members"] = [
        {"user_id": u.id, "name": u.name, "role_in_project": m.role_in_project}
        for m, u in members
    ]
    out["stakeholders"] = [
        {
            "id": s.id, "contact_id": c.id, "name": c.name,
            "role_at_client": s.role_at_client, "influence": s.influence,
            "preferred_channel": s.preferred_channel,
            "receives_progress_updates": s.receives_progress_updates,
        }
        for s, c in stakeholders
    ]
    out["commitments"] = [
        {
            "id": c.id, "text": c.text, "direction": c.direction,
            "status": c.status,
            "due_date": c.due_date.isoformat() if c.due_date else None,
        }
        for c in commitments
    ]
    return out


@router.get("/{project_id}/timeline")
async def project_timeline(
    project_id: str,
    limit: int = 100,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """The live timeline — the event stream, humanised (Workflow 17.6)."""
    await _get_project(db, ctx, project_id)
    rows = (
        await db.execute(
            select(ProgressEvent)
            .where(
                ProgressEvent.org_id == ctx.org_id,
                ProgressEvent.project_id == project_id,
            )
            .order_by(ProgressEvent.at.desc())
            .limit(min(limit, 500))
        )
    ).scalars().all()
    return [
        {
            "at": e.at.isoformat(),
            "event": e.event_type,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "actor": e.actor,
            "details": e.details,
        }
        for e in rows
    ]


@router.get("/{project_id}/plans")
async def list_plans(
    project_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _get_project(db, ctx, project_id)
    plans = (
        await db.execute(
            select(ActionPlan)
            .where(ActionPlan.project_id == project_id)
            .order_by(ActionPlan.version)
        )
    ).scalars().all()
    return [
        {
            "id": p.id, "version": p.version, "status": p.status,
            "summary": p.summary, "trigger": p.trigger,
            "changes_from_previous": p.changes_from_previous,
            "approved_by": p.approved_by,
            "approved_at": p.approved_at.isoformat() if p.approved_at else None,
        }
        for p in plans
    ]


class MemberRequest(BaseModel):
    user_id: str
    role_in_project: str | None = None


@router.post("/{project_id}/members")
async def add_member(
    project_id: str,
    body: MemberRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project(db, ctx, project_id)
    user = (
        await db.execute(
            select(User).where(User.org_id == ctx.org_id, User.id == body.user_id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found in your organisation")
    member = ProjectMember(
        org_id=ctx.org_id, project_id=project.id, user_id=user.id,
        role_in_project=body.role_in_project, added_by=ctx.user_id,
        joined_at=utcnow(),
    )
    db.add(member)
    await events.emit(
        db, org_id=ctx.org_id, event_type=EventType.MEMBER_JOINED.value,
        project_id=project.id, entity_type="user", entity_id=user.id,
        actor=ctx.user_id,
    )
    # The onboarding brief writes itself (Workflow 15.3).
    brief = await assistant_engine.onboarding_brief(
        db, org_id=ctx.org_id, project=project, user=user
    )
    from app.services.notification_service import notify

    await notify(
        db, org_id=ctx.org_id, user_id=user.id,
        title=f"Welcome to {project.name}",
        body=brief, kind="general", entity_type="project", entity_id=project.id,
    )
    await db.commit()
    return {"ok": True, "onboarding_brief": brief}


@router.delete("/{project_id}/members/{user_id}")
async def remove_member(
    project_id: str,
    user_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project(db, ctx, project_id)
    member = (
        await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == user_id,
                ProjectMember.left_at.is_(None),
            )
        )
    ).scalars().first()
    if member is None:
        raise NotFoundError("Member not found")
    member.left_at = utcnow()
    await events.emit(
        db, org_id=ctx.org_id, event_type=EventType.MEMBER_LEFT.value,
        project_id=project.id, entity_type="user", entity_id=user_id,
        actor=ctx.user_id,
    )
    await db.commit()
    return {"ok": True, "note": "open tasks are being redistributed"}


class StatusRequest(BaseModel):
    status: str
    reason: str | None = None
    revival_date: datetime | None = None
    revival_context: str | None = None


@router.post("/{project_id}/status")
async def set_status(
    project_id: str,
    body: StatusRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project(db, ctx, project_id)
    try:
        new_status = ProjectStatus(body.status)
    except ValueError:
        raise ValidationFailedError(f"Unknown status '{body.status}'")
    old = project.status
    project.status = new_status.value
    project.status_reason = body.reason
    await events.emit(
        db, org_id=ctx.org_id, event_type=EventType.PROJECT_STATUS_CHANGED.value,
        project_id=project.id, entity_type="project", entity_id=project.id,
        actor=ctx.user_id, details={"from": old, "to": new_status.value,
                                    "reason": body.reason or ""},
    )
    if new_status == ProjectStatus.AGREED and old != ProjectStatus.AGREED.value:
        await events.emit(
            db, org_id=ctx.org_id, event_type=EventType.DEAL_AGREED.value,
            project_id=project.id, entity_type="project", entity_id=project.id,
            actor=ctx.user_id,
        )
    if new_status == ProjectStatus.LOST:
        # Workflow 28: a no that is really a "later".
        lead = (
            await db.execute(select(Lead).where(Lead.id == project.lead_id))
        ).scalar_one_or_none()
        open_tasks = (
            await db.execute(
                select(ActionItem).where(
                    ActionItem.project_id == project.id,
                    ActionItem.status.in_(
                        [ActionItemStatus.OPEN.value, ActionItemStatus.IN_PROGRESS.value]
                    ),
                )
            )
        ).scalars().all()
        for t in open_tasks:
            t.status = ActionItemStatus.CANCELLED.value
            t.result_note = f"project lost: {body.reason or ''}"
        if lead is not None:
            from app.services import lead_service

            await lead_service.apply_suggestion(
                db, org_id=ctx.org_id, lead=lead, to_state="lost_for_now",
                reason=body.reason or "Project marked lost",
                engine="projects_api", confidence=1.0,
                input_summary=f"Project '{project.name}' set to lost by {ctx.email}",
            )
            if body.revival_date:
                lead.revival_date = body.revival_date
                lead.revival_context = body.revival_context
                lead.lost_reason = body.reason
    if new_status == ProjectStatus.ON_HOLD and project.parent_project_id is None:
        # Chain parents: pause cascades to unstarted children only (Workflow 27).
        children = (
            await db.execute(
                select(Project).where(Project.parent_project_id == project.id)
            )
        ).scalars().all()
        for child in children:
            if child.status in (
                ProjectStatus.PLANNING.value, ProjectStatus.PROPOSAL_STAGE.value,
                ProjectStatus.NEGOTIATION.value, ProjectStatus.AGREED.value,
            ):
                child.status = ProjectStatus.ON_HOLD.value
                child.status_reason = f"parent on hold: {body.reason or ''}"
    await db.commit()
    return _project_dict(project)


class PhaseShiftRequest(BaseModel):
    phase: str
    anchor_date: datetime | None = None


@router.post("/{project_id}/phase-shift")
async def trigger_phase_shift(
    project_id: str,
    body: PhaseShiftRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project(db, ctx, project_id)
    try:
        phase = Phase(body.phase)
    except ValueError:
        raise ValidationFailedError(f"Unknown phase '{body.phase}'")
    result = await planner_engine.phase_shift(
        db, org_id=ctx.org_id, project=project, phase=phase.value,
        anchor_date=body.anchor_date,
    )
    await db.commit()
    return result


class FeasibilityRequest(BaseModel):
    date_from: datetime
    date_to: datetime


@router.post("/{project_id}/feasibility")
async def check_feasibility(
    project_id: str,
    body: FeasibilityRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project(db, ctx, project_id)
    result = await planner_engine.feasibility_pass(
        db, org_id=ctx.org_id, project=project,
        date_from=body.date_from, date_to=body.date_to,
    )
    await db.commit()
    return result


@router.get("/{project_id}/whats-blocking")
async def whats_blocking(
    project_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project(db, ctx, project_id)
    return {"answer": await assistant_engine.whats_blocking(db, org_id=ctx.org_id, project=project)}


@router.get("/{project_id}/brief")
async def onboarding_brief(
    project_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project(db, ctx, project_id)
    user = (
        await db.execute(select(User).where(User.id == ctx.user_id))
    ).scalar_one()
    return {"brief": await assistant_engine.onboarding_brief(db, org_id=ctx.org_id, project=project, user=user)}


class StakeholderRequest(BaseModel):
    contact_id: str
    role_at_client: str | None = None
    influence: str | None = None
    preferred_channel: str = "email"
    preferred_language: str = "english"
    receives_progress_updates: bool = False
    do_not_contact: bool = False


@router.post("/{project_id}/stakeholders")
async def add_stakeholder(
    project_id: str,
    body: StakeholderRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project(db, ctx, project_id)
    contact = (
        await db.execute(
            select(Contact).where(Contact.org_id == ctx.org_id, Contact.id == body.contact_id)
        )
    ).scalar_one_or_none()
    if contact is None:
        raise NotFoundError("Contact not found")
    existing = (
        await db.execute(
            select(Stakeholder).where(
                Stakeholder.project_id == project.id,
                Stakeholder.contact_id == contact.id,
            )
        )
    ).scalars().first()
    if existing is not None:
        for field in ("role_at_client", "influence", "preferred_channel",
                      "preferred_language", "receives_progress_updates", "do_not_contact"):
            value = getattr(body, field)
            if value is not None:
                setattr(existing, field, value)
        await db.commit()
        return {"id": existing.id, "updated": True}
    stakeholder = Stakeholder(
        org_id=ctx.org_id, project_id=project.id, contact_id=contact.id,
        role_at_client=body.role_at_client, influence=body.influence,
        preferred_channel=body.preferred_channel,
        preferred_language=body.preferred_language,
        receives_progress_updates=body.receives_progress_updates,
        do_not_contact=body.do_not_contact,
    )
    db.add(stakeholder)
    await db.commit()
    return {"id": stakeholder.id, "updated": False}


@router.get("/{project_id}/conflicts")
async def list_conflicts(
    project_id: str,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _get_project(db, ctx, project_id)
    rows = (
        await db.execute(
            select(Conflict).where(Conflict.project_id == project_id)
        )
    ).scalars().all()
    return [
        {
            "id": c.id, "description": c.description, "status": c.status,
            "raised_to_user_id": c.raised_to_user_id,
            "resolution_note": c.resolution_note,
        }
        for c in rows
    ]


class ResolveConflictRequest(BaseModel):
    resolution_note: str = Field(min_length=2)


@router.post("/{project_id}/conflicts/{conflict_id}/resolve")
async def resolve_conflict(
    project_id: str,
    conflict_id: str,
    body: ResolveConflictRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    await _get_project(db, ctx, project_id)
    conflict = (
        await db.execute(
            select(Conflict).where(
                Conflict.org_id == ctx.org_id, Conflict.id == conflict_id
            )
        )
    ).scalar_one_or_none()
    if conflict is None:
        raise NotFoundError("Conflict not found")
    await planner_engine.resolve_conflict(
        db, org_id=ctx.org_id, conflict=conflict,
        resolution_note=body.resolution_note, resolved_by=ctx.user_id,
    )
    await db.commit()
    return {"ok": True}


class ChildProjectsRequest(BaseModel):
    branch_names: list[str]
    invoicing_mode: str = "group"


@router.post("/{project_id}/children")
async def create_children(
    project_id: str,
    body: ChildProjectsRequest,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    """Chain deals (Workflow 27): commercials on the parent, delivery on the
    children — each child with its own lead record and plan."""
    parent = await _get_project(db, ctx, project_id)
    parent.invoicing_mode = body.invoicing_mode
    created = []
    for name in body.branch_names:
        # Same rule as every other way a client is created (26 Sep 2026).
        from app.services.lead_service import refuse_duplicate_name

        await refuse_duplicate_name(db, ctx.org_id, name)
        lead = Lead(
            org_id=ctx.org_id, name=name, state="active",
            owner_id=parent.sales_owner_id, source="chain_deal",
        )
        db.add(lead)
        await db.flush()
        child = Project(
            org_id=ctx.org_id, lead_id=lead.id, program_id=parent.program_id,
            name=f"{name} — {parent.name}",
            objective=parent.objective,
            status=ProjectStatus.PLANNING.value,
            sales_owner_id=parent.sales_owner_id,
            ops_owner_id=parent.ops_owner_id,
            parent_project_id=parent.id,
        )
        db.add(child)
        await db.flush()
        await events.emit(
            db, org_id=ctx.org_id, event_type=EventType.PROJECT_CREATED.value,
            project_id=child.id, entity_type="project", entity_id=child.id,
            actor=ctx.user_id, details={"parent": parent.id},
        )
        created.append({"project_id": child.id, "lead_id": lead.id, "name": child.name})
    await db.commit()
    return {"children": created}


@router.get("/{project_id}/weekly-report")
async def weekly_report(
    project_id: str,
    kind: str = "client",
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project(db, ctx, project_id)
    if kind == "client":
        digest = await assistant_engine.build_weekly_client_report(
            db, org_id=ctx.org_id, project=project
        )
    else:
        digest = await assistant_engine.build_weekly_internal(
            db, org_id=ctx.org_id, project=project
        )
    await db.commit()
    if digest is None:
        return {"skipped": True, "reason": "nothing happened this week / on hold"}
    return {"digest_id": digest.id, "content_md": digest.content_md,
            "sent_message_id": digest.sent_message_id}
