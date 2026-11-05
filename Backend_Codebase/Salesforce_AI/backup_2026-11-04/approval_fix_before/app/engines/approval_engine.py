"""Approval Engine — finds the right approver from approval_rules, supports
joint and chained approvals, reminds, escalates on expiry, and records every
decision (30-Workflows §4 engine 8).

Two boundaries (Data Model §8.5):
- Plan versions matching NO rule activate automatically as approved_by="system".
- Task-assignment confirmations never come here (assignments.status instead).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    AP_APPROVER_SENDER,
    APPROVER_THREAD_OWNER,
    ApprovalStage,
    ApprovalStatus,
    EventType,
    MessageStatus,
    Role,
)
from app.core.exceptions import ValidationFailedError
from app.engines import events
from app.engines.common import find_role_user, get_user, record_decision
from app.models.base import utcnow
from app.models.comms import Approval, ApprovalRule
from app.models.messaging import OutboundMessage
from app.services.notification_service import notify

logger = logging.getLogger(__name__)

ENGINE = "approval"


# ─────────────────────────────────────────────────────────────────────────────
# Rule evaluation — conditions are data, evaluated generically
# ─────────────────────────────────────────────────────────────────────────────


def _condition_matches(condition: dict[str, Any] | None, facts: dict[str, Any]) -> bool:
    """Generic test evaluator. Supported key forms:
    "field_gt": n  → facts[field] > n
    "field_gte"/"field_lt"/"field_lte" analogous
    "field": value → equality (also bare booleans)
    Missing facts fail the test (a rule never fires on unknown data)."""
    if not condition:
        return True
    for key, expected in condition.items():
        for suffix, op in (("_gte", ">="), ("_gt", ">"), ("_lte", "<="), ("_lt", "<")):
            if key.endswith(suffix):
                field = key[: -len(suffix)]
                actual = facts.get(field)
                if actual is None:
                    return False
                if op == ">" and not actual > expected:
                    return False
                if op == ">=" and not actual >= expected:
                    return False
                if op == "<" and not actual < expected:
                    return False
                if op == "<=" and not actual <= expected:
                    return False
                break
        else:
            if facts.get(key) != expected:
                return False
    return True


async def find_rule(
    db: AsyncSession, *, org_id: str, entity_type: str, facts: dict[str, Any]
) -> ApprovalRule | None:
    """First matching rule wins (rank order, then creation order)."""
    rules = (
        await db.execute(
            select(ApprovalRule)
            .where(ApprovalRule.org_id == org_id, ApprovalRule.entity_type == entity_type)
            .order_by(ApprovalRule.rank, ApprovalRule.created_at)
        )
    ).scalars().all()
    for rule in rules:
        if _condition_matches(rule.condition, facts):
            return rule
    return None


async def _resolve_role_user(
    db: AsyncSession, org_id: str, role: str | None, facts: dict[str, Any]
):
    if not role:
        return None
    if role == APPROVER_THREAD_OWNER:
        return await get_user(db, org_id, facts.get("thread_owner_user_id"))
    if role == AP_APPROVER_SENDER:
        return await get_user(db, org_id, facts.get("sender_user_id"))
    return await find_role_user(db, org_id, role)


# ─────────────────────────────────────────────────────────────────────────────
# Requesting approvals
# ─────────────────────────────────────────────────────────────────────────────


async def request_approval(
    db: AsyncSession,
    *,
    org_id: str,
    entity_type: str,
    entity_id: str | None,
    facts: dict[str, Any],
    reason: str,
    project_id: str | None = None,
    bundled_entities: list[dict[str, str]] | None = None,
    default_approver_role: str | None = Role.SALES_LEAD.value,
) -> Approval | None:
    """Create the approval chain a matching rule demands.

    Returns the approval now waiting for a human (the recommend stage of a
    chain, or the decide stage otherwise). Returns None when no rule matches
    AND no default applies — the caller may then auto-apply as "system".
    """
    rule = await find_rule(db, org_id=org_id, entity_type=entity_type, facts=facts)

    if rule is None:
        if default_approver_role is None:
            return None  # below every threshold — caller activates as "system"
        approver = await _resolve_role_user(db, org_id, default_approver_role, facts)
        if approver is None:
            approver = await find_role_user(db, org_id, Role.ORG_ADMIN.value)
        approval = Approval(
            org_id=org_id, project_id=project_id,
            entity_type=entity_type, entity_id=entity_id,
            requested_from_user_id=approver.id if approver else None,
            requested_from_role=default_approver_role,
            stage=ApprovalStage.DECIDE.value,
            bundled_entities=bundled_entities or [],
            reason=reason, status=ApprovalStatus.PENDING.value,
            requested_at=utcnow(), expires_at=utcnow() + timedelta(hours=48),
        )
        db.add(approval)
        await db.flush()
        await _notify_approver(db, approval)
        return approval

    expires = utcnow() + timedelta(hours=rule.expires_hours or 48)

    if rule.auto_approve:
        # Two things this branch used to skip, both built for the path a human
        # taps and neither reaching this one.
        #
        # 1 · The F30/F47 fence. `_refuse_unfinished_drafts` lives in `decide()`,
        #     so a draft still reading "[Name]" was released to a client by a
        #     rule. `auto_approve` answers *who signs off*; it does not make an
        #     unfinished message finished. When the draft is not ready the rule
        #     simply does not apply and the approval becomes an ordinary pending
        #     one — refusing outright would strand the message with no approval
        #     at all, which is worse than asking a person.
        #
        # 2 · `requested_from_user_id`. It was never set, so `_release_message`
        #     copied None into `outbound_messages.approved_by` — the column
        #     Roles §2 calls "the proof". A rule delegating a decision still
        #     names somebody; resolve them exactly as the ordinary path does.
        approver = await _resolve_role_user(db, org_id, rule.approver_role, facts)
        if approver is None:
            approver = await _resolve_role_user(db, org_id, rule.fallback_role, facts)
        if approver is None:
            approver = await find_role_user(db, org_id, Role.ORG_ADMIN.value)

        blocked = await _unfinished_draft_reason(db, org_id, entity_type, entity_id,
                                                 bundled_entities)
        if blocked is None:
            approval = Approval(
                org_id=org_id, project_id=project_id,
                entity_type=entity_type, entity_id=entity_id,
                requested_from_user_id=approver.id if approver else None,
                requested_from_role=rule.approver_role,
                stage=ApprovalStage.DECIDE.value,
                bundled_entities=bundled_entities or [],
                reason=reason + " (auto-approved per rule)",
                status=ApprovalStatus.APPROVED.value,
                requested_at=utcnow(), decided_at=utcnow(),
            )
            db.add(approval)
            await db.flush()
            await _apply_approved(db, approval)
            return approval

        approval = Approval(
            org_id=org_id, project_id=project_id,
            entity_type=entity_type, entity_id=entity_id,
            requested_from_user_id=approver.id if approver else None,
            requested_from_role=rule.approver_role,
            stage=ApprovalStage.DECIDE.value,
            bundled_entities=bundled_entities or [],
            reason=f"{reason} — the auto-approval rule did not apply: {blocked}",
            status=ApprovalStatus.PENDING.value,
            requested_at=utcnow(), expires_at=expires,
        )
        db.add(approval)
        await db.flush()
        await _notify_approver(db, approval)
        return approval

    # Chained rule: the recommender reviews first.
    if rule.recommender_role:
        recommender = await _resolve_role_user(db, org_id, rule.recommender_role, facts)
        approval = Approval(
            org_id=org_id, project_id=project_id,
            entity_type=entity_type, entity_id=entity_id,
            requested_from_user_id=recommender.id if recommender else None,
            requested_from_role=rule.recommender_role,
            stage=ApprovalStage.RECOMMEND.value,
            bundled_entities=bundled_entities or [],
            reason=reason, status=ApprovalStatus.PENDING.value,
            requested_at=utcnow(), expires_at=expires,
        )
        # Remember who decides after the recommendation (rule data re-derives
        # it, but storing keeps the chain self-contained).
        approval.decision_note = None
        db.add(approval)
        await db.flush()
        await _notify_approver(db, approval)
        return approval

    approver = await _resolve_role_user(db, org_id, rule.approver_role, facts)
    if approver is None:
        approver = await _resolve_role_user(db, org_id, rule.fallback_role, facts)
    if approver is None:
        approver = await find_role_user(db, org_id, Role.ORG_ADMIN.value)

    joint_user = None
    if rule.joint_with_role and _condition_matches(rule.joint_condition, facts):
        joint_user = await _resolve_role_user(db, org_id, rule.joint_with_role, facts)

    approval = Approval(
        org_id=org_id, project_id=project_id,
        entity_type=entity_type, entity_id=entity_id,
        requested_from_user_id=approver.id if approver else None,
        requested_from_role=rule.approver_role,
        stage=ApprovalStage.DECIDE.value,
        joint_with_user_id=joint_user.id if joint_user else None,
        joint_status=ApprovalStatus.PENDING.value if joint_user else None,
        bundled_entities=bundled_entities or [],
        reason=reason, status=ApprovalStatus.PENDING.value,
        requested_at=utcnow(), expires_at=expires,
    )
    db.add(approval)
    await db.flush()
    await _notify_approver(db, approval)
    if joint_user is not None:
        await notify(
            db, org_id=org_id, user_id=joint_user.id,
            title="Joint approval waiting on you",
            body=reason, kind="approval_waiting",
            entity_type="approval", entity_id=approval.id,
        )
    await events.emit(
        db, org_id=org_id, event_type=EventType.APPROVAL_REQUESTED.value,
        project_id=project_id, entity_type="approval", entity_id=approval.id,
        details={"entity_type": entity_type, "reason": reason},
    )
    return approval


async def _notify_approver(db: AsyncSession, approval: Approval) -> None:
    if approval.requested_from_user_id:
        await notify(
            db, org_id=approval.org_id, user_id=approval.requested_from_user_id,
            title="Approval waiting on you"
            + (" (recommend stage)" if approval.stage == ApprovalStage.RECOMMEND.value else ""),
            body=approval.reason or "",
            kind="approval_waiting", entity_type="approval", entity_id=approval.id,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Deciding
# ─────────────────────────────────────────────────────────────────────────────


async def decide(
    db: AsyncSession,
    *,
    org_id: str,
    approval_id: str,
    user_id: str,
    approve: bool,
    note: str | None = None,
    allow_blanks: bool = False,
) -> Approval:
    """One human's yes/no on one approval card."""
    approval = (
        await db.execute(
            select(Approval).where(Approval.org_id == org_id, Approval.id == approval_id)
        )
    ).scalar_one()

    # F30 fence, before any state changes: a yes on a draft that still says
    # "[Name]" is refused here as well as on the direct message route, because
    # the inbox is the OTHER way into the same send. Checked up front so a
    # refusal leaves the approval exactly as it was — decided nothing, applied
    # nothing.
    if approve and not allow_blanks:
        await _refuse_unfinished_drafts(db, approval)

    # Joint second-approver path: record their own slot.
    if approval.joint_with_user_id and user_id == approval.joint_with_user_id:
        approval.joint_status = (
            ApprovalStatus.APPROVED.value if approve else ApprovalStatus.REJECTED.value
        )
        approval.joint_decision_note = note
        approval.joint_decided_at = utcnow()
        if not approve:
            approval.status = ApprovalStatus.REJECTED.value
            approval.decided_at = utcnow()
            await _finalise(db, approval, approved=False, note=note)
        elif approval.status == ApprovalStatus.APPROVED.value:
            # main approver already said yes → now complete
            await _finalise(db, approval, approved=True, note=note)
        return approval

    # Recommend stage: the yes attaches a recommendation and opens the decide row.
    if approval.stage == ApprovalStage.RECOMMEND.value:
        approval.status = (
            ApprovalStatus.APPROVED.value if approve else ApprovalStatus.REJECTED.value
        )
        approval.decision_note = note
        approval.decided_at = utcnow()
        if not approve:
            await _finalise(db, approval, approved=False, note=note)
            return approval
        # Chain to the decider named by the chained rule for this entity type.
        decider_role = Role.ORG_ADMIN.value
        rules = (
            await db.execute(
                select(ApprovalRule).where(
                    ApprovalRule.org_id == org_id,
                    ApprovalRule.entity_type == approval.entity_type,
                    ApprovalRule.recommender_role.is_not(None),
                )
            )
        ).scalars().all()
        if rules:
            decider_role = rules[0].approver_role
        decider = await find_role_user(db, org_id, decider_role)
        decide_row = Approval(
            org_id=org_id, project_id=approval.project_id,
            entity_type=approval.entity_type, entity_id=approval.entity_id,
            requested_from_user_id=decider.id if decider else None,
            requested_from_role=decider_role,
            stage=ApprovalStage.DECIDE.value,
            chain_parent_id=approval.id,
            recommendation=note,
            bundled_entities=approval.bundled_entities,
            reason=(approval.reason or "") + f" — recommendation attached: {note or '—'}",
            status=ApprovalStatus.PENDING.value,
            requested_at=utcnow(),
            expires_at=approval.expires_at,
        )
        db.add(decide_row)
        await db.flush()
        await _notify_approver(db, decide_row)
        return decide_row

    # Decide stage (single or the main slot of a joint approval).
    approval.decision_note = note
    approval.decided_at = utcnow()
    if not approve:
        approval.status = ApprovalStatus.REJECTED.value
        await _finalise(db, approval, approved=False, note=note)
        return approval

    approval.status = ApprovalStatus.APPROVED.value
    if approval.joint_with_user_id and approval.joint_status == ApprovalStatus.PENDING.value:
        # waiting for the second yes — nothing applies yet
        await notify(
            db, org_id=org_id, user_id=approval.joint_with_user_id,
            title="Your joint approval is now the last one pending",
            body=approval.reason or "", kind="approval_waiting",
            entity_type="approval", entity_id=approval.id,
        )
        return approval
    await _finalise(db, approval, approved=True, note=note)
    return approval


async def _finalise(
    db: AsyncSession, approval: Approval, *, approved: bool, note: str | None
) -> None:
    await events.emit(
        db, org_id=approval.org_id, event_type=EventType.APPROVAL_DECIDED.value,
        project_id=approval.project_id, entity_type="approval", entity_id=approval.id,
        details={
            "entity_type": approval.entity_type,
            "approved": approved,
            "note": note or "",
        },
    )
    if approved:
        await _apply_approved(db, approval)
    else:
        await _apply_rejected(db, approval, note)


async def _apply_approved(db: AsyncSession, approval: Approval) -> None:
    """Release the approved entity and everything bundled with it —
    they succeed or fail together (Workflow 18)."""
    targets = [{"entity_type": approval.entity_type, "entity_id": approval.entity_id}]
    targets += list(approval.bundled_entities or [])
    for t in targets:
        etype, eid = t.get("entity_type"), t.get("entity_id")
        if not eid:
            continue
        if etype == "outbound_message":
            await _release_message(db, approval, eid)
        elif etype == "plan_change":
            from app.engines import planner_engine

            await planner_engine.activate_plan(
                db, org_id=approval.org_id, plan_id=eid,
                approved_by=approval.requested_from_user_id or "system",
            )
        elif etype == "meeting_plan":
            # Approved from the inbox (or by an app without the plan sheet):
            # every task stays on, then the plan_change rules apply as usual.
            from app.engines import planner_engine

            await planner_engine.approve_meeting_plan(
                db, org_id=approval.org_id, meeting_id=eid, skip_ids=[],
                by_user_id=approval.requested_from_user_id or "system",
            )
        elif etype == "proposal":
            from app.core.constants import ProposalStatus
            from app.models.proposal import Proposal

            proposal = (
                await db.execute(
                    select(Proposal).where(
                        Proposal.org_id == approval.org_id, Proposal.id == eid
                    )
                )
            ).scalar_one_or_none()
            if proposal is not None and proposal.status in (
                ProposalStatus.DRAFT.value, ProposalStatus.INTERNAL_REVIEW.value,
            ):
                proposal.status = ProposalStatus.APPROVED_INTERNALLY.value
        elif etype == "invoice":
            from app.core.constants import InvoiceStatus
            from app.models.finance import Invoice

            invoice = (
                await db.execute(
                    select(Invoice).where(
                        Invoice.org_id == approval.org_id, Invoice.id == eid
                    )
                )
            ).scalar_one_or_none()
            if invoice is not None and invoice.status == InvoiceStatus.DRAFT.value:
                # cleared to send — the Communication Engine's send task follows
                pass
        # price_change approvals carry no automatic effect: the recorded yes
        # itself is the artifact (proposal amendments reference it).


async def _unfinished_draft_reason(
    db: AsyncSession,
    org_id: str,
    entity_type: str | None,
    entity_id: str | None,
    bundled_entities: list[dict[str, str]] | None = None,
) -> str | None:
    """The refusal text for a release that would send an unfinished draft, or
    None when everything is ready.

    Split out of `_refuse_unfinished_drafts` so the auto-approve branch can ask
    the same question without raising. Two copies of "what counts as
    unfinished" is how F30's fence came to guard one route and not the other,
    and F47 is the same lesson a second time — so there is exactly one.
    """
    from app.services import draft_check
    from app.services.message_service import find_message_blanks

    targets = [{"entity_type": entity_type, "entity_id": entity_id}]
    targets += list(bundled_entities or [])
    for target in targets:
        if target.get("entity_type") != "outbound_message" or not target.get("entity_id"):
            continue
        message = (
            await db.execute(
                select(OutboundMessage).where(
                    OutboundMessage.org_id == org_id,
                    OutboundMessage.id == target["entity_id"],
                )
            )
        ).scalar_one_or_none()
        if message is None or message.status not in (
            MessageStatus.PENDING_APPROVAL.value, MessageStatus.DRAFT.value,
        ):
            continue
        blanks, lines = await find_message_blanks(db, message)
        if blanks:
            return draft_check.refusal_message(blanks, lines)
    return None


async def _refuse_unfinished_drafts(db: AsyncSession, approval: Approval) -> None:
    """Raise if this approval would release a message still full of blanks.

    Covers the bundled entities too (Workflow 18: a bundle succeeds or fails
    together), so a finished draft cannot smuggle an unfinished one out with it.
    """
    blocked = await _unfinished_draft_reason(
        db, approval.org_id, approval.entity_type, approval.entity_id,
        approval.bundled_entities,
    )
    if blocked:
        raise ValidationFailedError(blocked)


async def _release_message(db: AsyncSession, approval: Approval, message_id: str) -> None:
    message = (
        await db.execute(
            select(OutboundMessage).where(
                OutboundMessage.org_id == approval.org_id,
                OutboundMessage.id == message_id,
            )
        )
    ).scalar_one_or_none()
    if message is None:
        return
    if message.status in (
        MessageStatus.PENDING_APPROVAL.value, MessageStatus.DRAFT.value,
    ):
        message.status = MessageStatus.QUEUED.value
        message.approved_by = approval.requested_from_user_id
        message.approved_at = utcnow()
        message.queued_at = utcnow()
        message.approval_id = approval.id
        from app.services.message_service import log_event

        await log_event(db, message, "queued", "released by approval")
        # Hand to the send worker.
        try:
            from app.jobs.queue import job_queue

            await job_queue.enqueue(
                "send_message", {"message_id": message.id},
                org_id=approval.org_id, priority=50, db=db,
            )
        except Exception:  # noqa: BLE001 — queue may be absent in dry-run harness
            logger.debug("Send queue unavailable; message stays QUEUED for the worker")


async def _apply_rejected(db: AsyncSession, approval: Approval, note: str | None) -> None:
    """A rejection with a note loops the draft back to be redone —
    the note becomes the instruction."""
    if approval.entity_type == "outbound_message" and approval.entity_id:
        message = (
            await db.execute(
                select(OutboundMessage).where(
                    OutboundMessage.org_id == approval.org_id,
                    OutboundMessage.id == approval.entity_id,
                )
            )
        ).scalar_one_or_none()
        if message is not None and message.status in (
            MessageStatus.PENDING_APPROVAL.value, MessageStatus.DRAFT.value,
        ):
            message.status = MessageStatus.REJECTED.value
            from app.services.message_service import log_event

            await log_event(db, message, "rejected", note)
            # The Communication Engine redrafts with the note as instruction.
            from app.engines import communication_engine

            await communication_engine.redraft_rejected(
                db, org_id=approval.org_id, message=message, instruction=note or "",
            )
    elif approval.entity_type == "plan_change" and approval.entity_id:
        from app.engines import planner_engine

        await planner_engine.plan_rejected(
            db, org_id=approval.org_id, plan_id=approval.entity_id, note=note or "",
        )
    elif approval.entity_type == "meeting_plan" and approval.entity_id:
        # Turned down by the person who recorded the meeting: the Planner's
        # extras are dropped, the confirmed to-dos stay, nobody else is asked.
        from app.engines import planner_engine

        await planner_engine.discard_meeting_plan(
            db, org_id=approval.org_id, meeting_id=approval.entity_id, note=note,
        )
    elif approval.entity_type == "proposal" and approval.entity_id:
        # The note becomes the instruction: proposal back to draft for redo.
        from app.core.constants import ProposalStatus
        from app.models.proposal import Proposal, ProposalRevision

        proposal = (
            await db.execute(
                select(Proposal).where(
                    Proposal.org_id == approval.org_id,
                    Proposal.id == approval.entity_id,
                )
            )
        ).scalar_one_or_none()
        if proposal is not None and proposal.status == ProposalStatus.INTERNAL_REVIEW.value:
            proposal.status = ProposalStatus.DRAFT.value
            from sqlalchemy import func as sa_func

            last_no = (
                await db.execute(
                    select(sa_func.max(ProposalRevision.revision_no)).where(
                        ProposalRevision.proposal_id == proposal.id
                    )
                )
            ).scalar_one()
            db.add(
                ProposalRevision(
                    org_id=approval.org_id, proposal_id=proposal.id,
                    revision_no=(last_no or 0) + 1,
                    instruction=f"Rejected in review: {note or 'redo'}",
                    content_md=proposal.content_md,
                    line_items=proposal.line_items,
                    total_amount=proposal.total_amount,
                    edited_by=approval.requested_from_user_id,
                )
            )
    # Notify whoever the approval concerned (project owner) — done via event.


# ─────────────────────────────────────────────────────────────────────────────
# Reminders and escalation (never dies silently in an inbox)
# ─────────────────────────────────────────────────────────────────────────────


async def sweep_pending(db: AsyncSession, *, org_id: str, now: datetime | None = None) -> None:
    now = now or utcnow()
    pending = (
        await db.execute(
            select(Approval).where(
                Approval.org_id == org_id,
                Approval.status == ApprovalStatus.PENDING.value,
            )
        )
    ).scalars().all()
    for a in pending:
        if a.expires_at is None:
            continue
        if now >= a.expires_at:
            a.status = ApprovalStatus.ESCALATED.value
            escalate_to = await find_role_user(db, org_id, Role.ORG_ADMIN.value)
            if escalate_to is not None and escalate_to.id != a.requested_from_user_id:
                a.escalated_to_user_id = escalate_to.id
                # Escalation re-opens the card for the new approver.
                a.requested_from_user_id = escalate_to.id
                a.status = ApprovalStatus.PENDING.value
                a.expires_at = now + timedelta(hours=24)
                await notify(
                    db, org_id=org_id, user_id=escalate_to.id,
                    title="Escalated approval needs you",
                    body=a.reason or "", kind="escalation",
                    entity_type="approval", entity_id=a.id,
                )
                await record_decision(
                    db, org_id=org_id, project_id=a.project_id,
                    decision_type="escalation", engine=ENGINE,
                    decision=f"Approval escalated to {escalate_to.name}",
                    reason="Approver did not act before expiry",
                    entity_type="approval", entity_id=a.id,
                )
        elif a.reminded_at is None and a.requested_from_user_id:
            half_life = a.requested_at + (a.expires_at - a.requested_at) / 2 if a.requested_at else None
            if half_life and now >= half_life:
                a.reminded_at = now
                await notify(
                    db, org_id=org_id, user_id=a.requested_from_user_id,
                    title="Reminder: approval still waiting",
                    body=a.reason or "", kind="reminder",
                    entity_type="approval", entity_id=a.id,
                )
