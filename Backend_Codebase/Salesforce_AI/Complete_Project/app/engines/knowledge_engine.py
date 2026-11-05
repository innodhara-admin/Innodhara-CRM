"""Knowledge Engine — the organisation's memory (30-Workflows §4 engine 9).

Owns playbooks improvement, client_intelligence and the long-term memory
store. Distils every closed project and incident into lessons, and briefs
the Planner with rich priors so every new plan starts smarter than the last.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.memory import add_memory, search_memory
from app.core.constants import (
    ActionItemStatus,
    CommitmentStatus,
    EventType,
    IncidentStatus,
    Role,
)
from app.engines.common import find_role_user, get_user
from app.models.action_item import ActionItem
from app.models.base import utcnow
from app.models.finance import Deliverable
from app.models.lead import Lead, ClientIntelligence
from app.models.project import ClientCommitment, PlaybookSuggestion, Project
from app.models.proposal import Proposal
from app.models.work import Incident, ProgressEvent
from app.services.notification_service import notify

logger = logging.getLogger(__name__)

ENGINE = "knowledge"


async def distil_project(db: AsyncSession, *, org_id: str, project: Project) -> None:
    """The archival pass at closure (Workflow 26.5): the whole project boiled
    into memories, intelligence, and a cross-sell note."""
    commitments = (
        await db.execute(
            select(ClientCommitment).where(ClientCommitment.project_id == project.id)
        )
    ).scalars().all()
    kept = sum(1 for c in commitments if c.status == CommitmentStatus.KEPT.value)
    renegotiated = sum(1 for c in commitments if c.status == CommitmentStatus.RENEGOTIATED.value)
    broken = sum(1 for c in commitments if c.status == CommitmentStatus.BROKEN.value)
    incidents = (
        await db.execute(select(Incident).where(Incident.project_id == project.id))
    ).scalars().all()
    lessons = [i.lesson for i in incidents if i.lesson]
    feedback = (
        await db.execute(
            select(Deliverable)
            .where(
                Deliverable.project_id == project.id,
                Deliverable.type == "feedback_summary",
            )
            .order_by(Deliverable.version.desc())
        )
    ).scalars().first()

    summary_bits = [
        f"{project.name}: closed {utcnow():%b %Y}",
        f"value {project.value_estimate:,.0f}" if project.value_estimate else "",
        f"commitments {kept} kept / {renegotiated} renegotiated / {broken} broken",
    ]
    if feedback is not None and feedback.content_md:
        summary_bits.append(f"feedback: {feedback.content_md[:120]}")
    summary_bits += [f"lesson: {l}" for l in lessons]
    text = "; ".join(b for b in summary_bits if b)

    await add_memory(
        db, org_id=org_id, text=text, source_type="project_closure",
        source_id=project.id, lead_id=project.lead_id,
    )
    db.add(
        ClientIntelligence(
            org_id=org_id, lead_id=project.lead_id,
            note=f"{project.name} closed: {kept} promises kept"
            + (f"; feedback {feedback.content_md[:80]}" if feedback and feedback.content_md else ""),
            category="history", source="system", added_by="ai",
        )
    )

    # Cross-sell note — the opening scene of the next deal (Workflow 26.6 → 30).
    sales_owner = await get_user(db, org_id, project.sales_owner_id)
    if sales_owner is None:
        sales_owner = await find_role_user(db, org_id, Role.SALES_LEAD.value)
    if sales_owner is not None:
        went_well = broken == 0 and not any(
            i.severity == "high" and i.status != IncidentStatus.RESOLVED.value
            for i in incidents
        )
        if went_well:
            await notify(
                db, org_id=org_id, user_id=sales_owner.id,
                title=f"Cross-sell: {project.name} closed happy",
                body=(
                    "This client's profile fits a larger annual program; suggested "
                    "touch: before the next budget season. Full story in memory."
                ),
                kind="general", entity_type="project", entity_id=project.id,
            )
        else:
            await notify(
                db, org_id=org_id, user_id=sales_owner.id,
                title=f"Repair plan suggested for {project.name}",
                body="Closure had broken promises or open issues — a repair "
                "touch beats a sales touch here.",
                kind="general", entity_type="project", entity_id=project.id,
            )


async def distil_incident(db: AsyncSession, *, org_id: str, incident: Incident) -> None:
    """Incident resolved → memory + a playbook suggestion the admin can accept
    with one tap (Workflow 22.5)."""
    if incident.lesson:
        await add_memory(
            db, org_id=org_id,
            text=f"Incident lesson: {incident.lesson} (from: {incident.description[:120]})",
            source_type="incident", source_id=incident.id,
        )
        project = (
            await db.execute(select(Project).where(Project.id == incident.project_id))
        ).scalar_one_or_none()
        if project is not None and project.program_id:
            suggestion = PlaybookSuggestion(
                org_id=org_id,
                program_id=project.program_id,
                phase="preparation",
                entry={
                    "title": incident.lesson,
                    "required_skill": "logistics",
                    "offset_days": -1,
                    "priority": "P2",
                    "visible_to_client": False,
                },
                reason=f"From incident on {project.name}: {incident.description[:150]}",
                source_incident_id=incident.id,
            )
            db.add(suggestion)
            admin = await find_role_user(db, org_id, Role.ORG_ADMIN.value)
            if admin is not None:
                await notify(
                    db, org_id=org_id, user_id=admin.id,
                    title="Playbook improvement proposed",
                    body=f"'{incident.lesson}' — accept and every future project "
                    "at any client inherits the lesson.",
                    kind="general", entity_type="playbook_suggestion",
                    entity_id=suggestion.id,
                )


async def replay_story(db: AsyncSession, *, org_id: str, lead: Lead) -> str:
    """The whole story replayed for a revival card (Workflow 28.4):
    proposal, projects, champion, prices — ten seconds of reading."""
    lines: list[str] = []
    projects = (
        await db.execute(
            select(Project).where(Project.org_id == org_id, Project.lead_id == lead.id)
        )
    ).scalars().all()
    for p in projects:
        lines.append(
            f"Project: {p.name} — {p.status}"
            + (f", value {p.value_estimate:,.0f}" if p.value_estimate else "")
        )
    proposals = (
        await db.execute(
            select(Proposal).where(Proposal.org_id == org_id, Proposal.lead_id == lead.id)
        )
    ).scalars().all()
    for p in proposals:
        lines.append(f"Proposal: {p.title} — {p.status}, {p.total_amount:,.0f}")
    intel = (
        await db.execute(
            select(ClientIntelligence)
            .where(ClientIntelligence.lead_id == lead.id)
            .order_by(ClientIntelligence.created_at.desc())
        )
    ).scalars().all()
    for i in intel[:6]:
        lines.append(f"Known: {i.note}")
    memories = await search_memory(
        db, org_id=org_id, query=lead.name, lead_id=lead.id, top_k=3
    )
    for m in memories:
        lines.append(f"Memory: {m['text'][:200]}")
    return "\n".join(lines) if lines else "No prior history recorded."


async def planner_brief(db: AsyncSession, *, org_id: str, lead: Lead) -> dict:
    """Rich priors for a new plan (Workflow 30.3): known stakeholders,
    logistics, risks, and playbook lessons already absorbed."""
    intel = (
        await db.execute(
            select(ClientIntelligence).where(ClientIntelligence.lead_id == lead.id)
        )
    ).scalars().all()
    memories = await search_memory(
        db, org_id=org_id, query=f"{lead.name} lessons risks logistics",
        lead_id=lead.id, top_k=5,
    )
    return {
        "intelligence": [i.note for i in intel],
        "memories": [m["text"] for m in memories],
    }
