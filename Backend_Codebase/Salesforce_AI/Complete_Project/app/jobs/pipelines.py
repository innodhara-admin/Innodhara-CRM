"""The meeting-processing pipeline (Figure 7): transcribe -> extract action
items -> (review gate) -> save -> memory -> lead-state suggestion.

Runs as one background job so the user never stares at a frozen screen; the
app polls GET /meetings/{id} and sees status move through the stages.
Idempotent: a retry reuses the transcript instead of re-transcribing (§11.5).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.ai import extraction, memory as memory_ai, stt
from app.core import clock
from app.core.constants import (
    ActionItemStatus,
    EventType,
    FollowUpStatus,
    LeadState,
    MeetingPlanState,
    MeetingStatus,
    MeetingType,
)
from app.database import SessionLocal
from app.models.action_item import ActionItem
from app.models.base import utcnow
from app.models.followup import FollowUp
from app.models.lead import Lead, ClientIntelligence
from app.models.meeting import Meeting, Transcript
from app.models.organisation import Organisation, OrgSettings
from app.models.user import User
from app.services import lead_service, notification_service, storage

logger = logging.getLogger(__name__)


async def process_meeting(payload: dict[str, Any], job_id: str) -> dict[str, Any]:
    meeting_id = payload["meeting_id"]

    async with SessionLocal() as db:
        meeting = (
            await db.execute(select(Meeting).where(Meeting.id == meeting_id))
        ).scalar_one_or_none()
        if meeting is None:
            return {"skipped": "meeting deleted"}
        org_id = meeting.org_id
        lead = (
            await db.execute(select(Lead).where(Lead.id == meeting.lead_id))
        ).scalar_one_or_none()
        org = (
            await db.execute(select(Organisation).where(Organisation.id == org_id))
        ).scalar_one()
        org_settings = (
            await db.execute(select(OrgSettings).where(OrgSettings.org_id == org_id))
        ).scalar_one_or_none()
        agent = (
            await db.execute(select(User).where(User.id == meeting.agent_id))
        ).scalar_one_or_none()

        # ── Step 1: transcript (reused on retry — "do not re-transcribe") ────
        transcript = (
            await db.execute(select(Transcript).where(Transcript.meeting_id == meeting_id))
        ).scalar_one_or_none()
        if transcript is None:
            meeting.status = MeetingStatus.TRANSCRIBING.value
            await db.commit()
            if not meeting.audio_path:
                meeting.status = MeetingStatus.FAILED.value
                meeting.error = "No audio file attached"
                await db.commit()
                return {"error": "no audio"}
            audio = storage.read_bytes(org_id, meeting.audio_path)
            result = await stt.transcribe(
                audio, meeting.audio_mime or "audio/mpeg",
                org_id=org_id, user_id=meeting.agent_id,
            )
            transcript = Transcript(
                org_id=org_id,
                meeting_id=meeting_id,
                text=result.text,
                language=result.language,
                confidence=result.confidence,
                low_confidence=result.low_confidence,
                word_count=len(result.text.split()),
            )
            db.add(transcript)
            meeting.status = MeetingStatus.TRANSCRIBED.value
            await db.commit()

        # ── Step 2: understand the meeting ──────────────────────────────────
        meeting.status = MeetingStatus.EXTRACTING.value
        await db.commit()

        # A catch-up is not a sales meeting and must not be processed like
        # one. It branches here and returns: no action items, no review gate,
        # no lead-state suggestion and no Planner. Everything below this block
        # is the established sales path, unchanged.
        if meeting.meeting_type == MeetingType.RELATIONSHIP.value:
            return await process_relationship_meeting(
                db, meeting=meeting, transcript=transcript, lead=lead, org=org,
            )
        zone = await clock.org_zone(db, org_id)
        analysis = await extraction.analyse_meeting(
            transcript.text,
            org_name=org.name,
            client_name=lead.name if lead else "the client",
            org_id=org_id,
            user_id=meeting.agent_id,
            tz_name=str(zone),
            # "Thursday" is counted from the day it was said, not the day the
            # pipeline happens to run (BS Carmel School, 29 Sep 2026).
            today=clock.local_date(meeting.started_at or meeting.created_at, zone),
            # The moment itself, so the strong model reads "next Saturday at
            # 11" from when it was said (2 Oct 2026).
            now=clock.to_local(meeting.started_at or meeting.created_at, zone),
        )
        transcript.summary = analysis.summary

        # ── Step 3: review gate (per-user override, else org switch) ────────
        review_required = (
            agent.require_action_item_review
            if agent and agent.require_action_item_review is not None
            else (org_settings.require_action_item_review if org_settings else True)
        )
        item_status = (
            ActionItemStatus.PENDING_REVIEW.value
            if review_required
            else ActionItemStatus.OPEN.value
        )
        created = 0
        extracted: list[ActionItem] = []
        # The agreed meeting gets its own task below (Step 3b). A to-do that
        # is only the meeting itself or its invite, due that same day, would
        # list it twice — seen on the first real upload, 23 Sep 2026.
        meeting_day = (analysis.agreed_meeting or {}).get("date") if lead is not None else None
        for raw in analysis.action_items:
            due = raw.get("due_date")
            if meeting_day and due is not None and due.date().isoformat() == meeting_day \
                    and _only_the_meeting(raw.get("title") or ""):
                continue
            description = raw.get("description") or ""
            # The deadline belongs in the column the digest, My Tasks and the
            # nudge ladder all read (finding F8). Only a hint the model could
            # not resolve to a date stays as prose — losing it entirely would
            # be worse, and a guessed date would be worse still.
            if due is None and raw.get("due_hint"):
                description += f" (due: {raw['due_hint']})"
            item = ActionItem(
                org_id=org_id,
                lead_id=meeting.lead_id,
                meeting_id=meeting_id,
                title=raw.get("title", "")[:490],
                description=description,
                due_date=due,
                owner_id=meeting.agent_id,
                status=item_status,
                created_by="system",
            )
            db.add(item)
            extracted.append(item)
            created += 1

        # ── Step 3b: an agreed meeting (customer ask, 21 Sep 2026) ───────────
        # Scheduled on its own path, not as a demo: a task with the date and
        # time (reviewed like the rest when the gate is on) and an invite that
        # waits in Approvals. A failure here must not cost the meeting's other
        # results, so it is contained and logged.
        if analysis.agreed_meeting and lead is not None:
            from app.services import meeting_invite_service

            try:
                async with db.begin_nested():
                    scheduled = await meeting_invite_service.schedule_from_recording(
                        db, recording=meeting, lead=lead, agreed=analysis.agreed_meeting,
                        task_status=item_status, summary=analysis.summary,
                        note=analysis.agreed_meeting_note,
                    )
                if scheduled is not None:
                    created += 1
            except Exception:  # noqa: BLE001
                logger.exception("Could not schedule the meeting agreed in %s", meeting_id)

        # ── Step 4: memory + intelligence ────────────────────────────────────
        if analysis.summary:
            await memory_ai.add_memory(
                db, org_id=org_id, lead_id=meeting.lead_id,
                text=f"Meeting summary ({lead.name if lead else ''}): {analysis.summary}",
                source_type="meeting", source_id=meeting_id,
            )
        for fact in analysis.key_facts[:5]:
            db.add(
                ClientIntelligence(
                    org_id=org_id, lead_id=meeting.lead_id,
                    note=fact, category="from_meeting", source="system",
                    added_by="system",
                )
            )
            await memory_ai.add_memory(
                db, org_id=org_id, lead_id=meeting.lead_id,
                text=f"Fact about {lead.name if lead else 'the client'}: {fact}",
                source_type="note", source_id=meeting_id,
            )

        # ── Step 5: lead-state suggestion (human confirms) ───────────────────
        if (
            lead is not None
            and analysis.real_discussion
            and lead.state == LeadState.OPEN.value
            and (org_settings.auto_suggest_lead_state if org_settings else True)
        ):
            await lead_service.suggest_state(
                db, org_id=org_id, lead_id=lead.id,
                to_state=LeadState.ACTIVE.value,
                reason="A real recorded discussion took place",
            )
            meeting.state_suggestion = LeadState.ACTIVE.value

        if lead is not None:
            await lead_service.touch(db, org_id, lead.id)

        meeting.status = (
            MeetingStatus.REVIEW_PENDING.value
            if review_required and created
            else MeetingStatus.COMPLETED.value
        )
        meeting.error = None
        if not review_required and created:
            # The Planner runs right below; the app shows its loader and then
            # the plan sheet from this state (review switch off, 1 Oct 2026).
            meeting.plan_state = MeetingPlanState.PLANNING.value
            meeting.plan_note = None

        await notification_service.notify(
            db, org_id=org_id, user_id=meeting.agent_id,
            title=(
                f"Meeting processed: {created} action item(s) "
                + ("awaiting your review" if review_required and created else "saved")
            ),
            kind="meeting_processed", entity_type="meeting", entity_id=meeting_id,
        )
        await db.commit()

        # ── Step 6: the Planner (finding F9) ─────────────────────────────────
        # Recording a meeting must start the same machine typing the notes
        # starts. With the review gate ON, that happens when the human confirms
        # what was heard (POST /review/confirm enqueues plan_meeting) — the
        # plan is then built around to-dos a person actually agreed to. With
        # the gate OFF there is no such moment, so the Planner runs here, over
        # the items the pipeline just opened.
        planned: dict[str, Any] | None = None
        if not review_required and created:
            planned = await plan_meeting(
                {
                    "meeting_id": meeting_id,
                    "agreed_tasks": [
                        {"title": i.title, "description": i.description,
                         "due_date": i.due_date.isoformat() if i.due_date else None}
                        for i in extracted
                    ],
                },
                job_id,
            )
        return {
            "transcript_words": transcript.word_count,
            "action_items": created,
            "review_required": review_required,
            "planner": planned,
        }


def _only_the_meeting(title: str) -> bool:
    from app.services.meeting_invite_service import is_only_the_meeting

    return is_only_the_meeting(title)


async def process_relationship_meeting(
    db, *, meeting: Meeting, transcript: Transcript, lead: Lead | None,
    org: Organisation,
) -> dict[str, Any]:
    """A catch-up: summarise it, remember it, and plan the next one.

    Three things happen and nothing else.

    The summary goes into `client_intelligence` with category "relationship",
    which is the feed on the client page. That is a deliberate choice against
    the `relationship_touches` table the plan left open: `client_intelligence`
    already has the shape, and `knowledge_engine.replay_story` already reads
    it, so the feed appears in the client's story for free and there is one
    less table in the reset taxonomy.

    The suggested next touch becomes an ordinary `followups` row, owned by
    whoever recorded the meeting. The table already holds a lead, an owner, a
    due date, a channel and a note -- a planned touch is exactly that, so no
    new table is needed here either.

    A person still decides everything. The follow-up is a reminder, not a
    commitment, and nothing here moves the lead.
    """
    org_id = meeting.org_id
    analysis = await extraction.analyse_relationship_meeting(
        transcript.text,
        org_name=org.name,
        client_name=lead.name if lead else "the client",
        org_id=org_id,
        user_id=meeting.agent_id,
        tz_name=str(await clock.org_zone(db, org_id)),
    )
    transcript.summary = analysis.summary

    if analysis.summary:
        db.add(
            ClientIntelligence(
                org_id=org_id, lead_id=meeting.lead_id,
                note=analysis.summary, category="relationship",
                source="system", added_by="system",
            )
        )
        await memory_ai.add_memory(
            db, org_id=org_id, lead_id=meeting.lead_id,
            text=f"Catch-up with {lead.name if lead else 'the client'}: "
                 f"{analysis.summary}",
            source_type="meeting", source_id=meeting.id,
        )
    for fact in analysis.key_facts[:5]:
        db.add(
            ClientIntelligence(
                org_id=org_id, lead_id=meeting.lead_id,
                note=fact, category="from_meeting", source="system",
                added_by="system",
            )
        )

    tz = await clock.org_zone(db, org_id)
    due = clock.today(tz) + timedelta(days=analysis.next_touch_days)
    followup = FollowUp(
        org_id=org_id,
        lead_id=meeting.lead_id,
        owner_id=meeting.agent_id,
        due_date=due,
        channel="call",
        status=FollowUpStatus.PENDING.value,
        note=analysis.next_touch_topics or "Keep in touch",
        created_by="system",
    )
    db.add(followup)

    flagged = False
    if analysis.new_opportunity:
        flagged = await _flag_opportunity(db, meeting=meeting, lead=lead,
                                          analysis=analysis)

    if lead is not None:
        await lead_service.touch(db, org_id, lead.id)
    meeting.status = MeetingStatus.COMPLETED.value
    meeting.error = None

    await notification_service.notify(
        db, org_id=org_id, user_id=meeting.agent_id,
        title=(
            f"Possible new opportunity: {lead.name if lead else 'client'}"
            if flagged
            else f"Catch-up saved: {lead.name if lead else 'client'}"
        ),
        body=(
            analysis.opportunity_reason if flagged
            else (
                f"Suggested next touch {due:%d %b}"
                + (f" — {analysis.next_touch_topics}"
                   if analysis.next_touch_topics else "")
            )
        ),
        kind="meeting_processed", entity_type="lead" if flagged else "meeting",
        entity_id=lead.id if (flagged and lead) else meeting.id,
    )
    await db.commit()
    return {
        "transcript_words": transcript.word_count,
        "relationship": True,
        "action_items": 0,
        "next_touch": due.isoformat(),
        "new_opportunity": flagged,
    }


async def _flag_opportunity(db, *, meeting: Meeting, lead: Lead | None,
                            analysis) -> bool:
    """Record that the client may want to buy again, for a person to answer.

    Returns whether a card was actually raised. It is not raised when nobody
    is looking after this client -- a card with no owner is a card nobody
    answers -- and a hint that arrives while one is already open replaces it,
    because what closes the question is a person deciding, not the number of
    times the AI noticed.
    """
    from sqlalchemy import select

    from app.core.constants import (
        DecisionType, EngagementStatus, OpportunityStatus,
    )
    from app.engines.common import record_decision
    from app.models.relationship import RelationshipEngagement

    engagement = (
        await db.execute(
            select(RelationshipEngagement).where(
                RelationshipEngagement.org_id == meeting.org_id,
                RelationshipEngagement.lead_id == meeting.lead_id,
                RelationshipEngagement.status == EngagementStatus.ACTIVE.value,
            )
        )
    ).scalars().first()
    if engagement is None:
        logger.info(
            "Opportunity hint on lead %s ignored: nobody looks after this client",
            meeting.lead_id,
        )
        return False
    if engagement.opportunity_status == OpportunityStatus.ACCEPTED.value:
        # Already agreed and handed to sales; a second hint changes nothing.
        return False

    engagement.opportunity_status = OpportunityStatus.OPEN.value
    engagement.opportunity_reason = analysis.opportunity_reason
    engagement.opportunity_quote = analysis.opportunity_quote
    engagement.opportunity_meeting_id = meeting.id
    engagement.opportunity_at = utcnow()
    engagement.opportunity_decided_by = None
    engagement.opportunity_decided_at = None

    # F10: an offered suggestion with no recorded decision leaves the "Why?"
    # button with nothing to say.
    await record_decision(
        db,
        org_id=meeting.org_id,
        decision_type=DecisionType.STATE_CHANGE.value,
        engine="relationship",
        input_summary=(
            f"Catch-up with {lead.name if lead else 'the client'}: "
            f"\"{analysis.opportunity_quote}\""
        ),
        decision=(
            f"'{lead.name if lead else 'This client'}' may be ready to buy "
            f"again — raised for a person to confirm"
        ),
        reason=analysis.opportunity_reason,
        confidence=0.6,
        needs_human=True,
        entity_type="lead",
        entity_id=meeting.lead_id,
    )
    return True


async def plan_meeting(payload: dict[str, Any], job_id: str) -> dict[str, Any]:
    """Run the Planner over a recorded meeting (finding F9).

    Enqueued by the review gate once a human has confirmed what the meeting
    agreed; called inline by the pipeline when the org has the gate switched
    off. Either way the Planner sees the full transcript AND the confirmed
    to-dos, so it plans around them instead of producing a rival task list.

    Never fatal to the meeting: the transcript, the summary, the facts and the
    confirmed items are all already saved and committed by the time this runs.

    Since 1 Oct 2026 the plan is HELD for the person who recorded the meeting
    ("Approve plan"), and `meeting.plan_state` says where it stands. It runs
    once per meeting: a second run (a second confirm, a duplicated job) finds
    the plan already made and stops (BS Carmel School, 29 Sep 2026).
    """
    meeting_id = payload["meeting_id"]
    agreed_raw = payload.get("agreed_tasks") or []
    agreed: list[dict[str, Any]] = []
    for t in agreed_raw:
        due = t.get("due_date")
        agreed.append({
            "title": t.get("title"),
            "description": t.get("description"),
            "due_date": datetime.fromisoformat(due) if isinstance(due, str) else due,
        })

    async with SessionLocal() as db:
        meeting = (
            await db.execute(select(Meeting).where(Meeting.id == meeting_id))
        ).scalar_one_or_none()
        if meeting is None:
            return {"skipped": "meeting deleted"}
        if meeting.plan_state not in (None, MeetingPlanState.PLANNING.value):
            return {"skipped": f"plan already {meeting.plan_state}"}
        from app.core.constants import PlanStatus, PlanTrigger
        from app.models.project import ActionPlan

        made = (
            await db.execute(
                select(ActionPlan.id).where(
                    ActionPlan.trigger_ref == meeting_id,
                    ActionPlan.trigger.in_([PlanTrigger.FIRST_MEETING.value,
                                            PlanTrigger.NEW_MEETING.value]),
                    ActionPlan.status.in_([PlanStatus.PENDING_REVIEW.value,
                                           PlanStatus.ACTIVE.value]),
                )
            )
        ).first()
        if made is not None:
            return {"skipped": "this meeting already has a plan"}
        transcript = (
            await db.execute(select(Transcript).where(Transcript.meeting_id == meeting_id))
        ).scalar_one_or_none()
        text = (transcript.text if transcript else None) or meeting.notes_text or ""
        if not text.strip():
            meeting.plan_state = MeetingPlanState.NO_PLAN.value
            meeting.plan_note = "There was nothing to plan from in this recording."
            await db.commit()
            return {"skipped": "no transcript to plan from"}

        from app.engines import events as event_stream
        from app.engines import planner_engine

        result = await planner_engine.process_meeting(
            db, org_id=meeting.org_id, meeting=meeting, text=text,
            agreed_tasks=agreed, hold_for_review=True,
        )
        _record_plan_outcome(meeting, result)
        await event_stream.emit(
            db, org_id=meeting.org_id, event_type=EventType.MEETING_PROCESSED.value,
            project_id=meeting.project_id, entity_type="meeting", entity_id=meeting_id,
            actor=meeting.agent_id, details={"action": result.get("action", "")},
        )
        await db.commit()
        logger.info("Planner ran on meeting %s: %s", meeting_id, result.get("action"))
        return result


def _record_plan_outcome(meeting: Meeting, result: dict[str, Any]) -> None:
    """What the app shows after the loader, for every way the Planner ends.
    A held plan has already set READY (`planner_engine._hold_for_recorder`)."""
    if meeting.plan_state == MeetingPlanState.READY.value:
        return
    action = result.get("action")
    if action == "held_for_review" and result.get("reason") == "ai_unavailable":
        state, note = MeetingPlanState.FAILED, (
            "The planner could not be reached just now. Nothing was lost: "
            "your confirmed to-dos are saved. Try again in a minute.")
    elif action == "held_for_review":
        state, note = MeetingPlanState.NO_PLAN, (
            "This recording may be about a different client, so the plan was "
            "not changed. Your confirmed to-dos are saved.")
    elif action == "held_by_conflict":
        state, note = MeetingPlanState.NO_PLAN, (
            "Something said in this meeting disagrees with an earlier one. The "
            "project's owner has been asked to settle it; the plan changes after that.")
    elif action == "followups_only":
        state, note = MeetingPlanState.NO_PLAN, (
            "No project yet: nothing concrete enough to plan. A follow-up call "
            "was added to your list.")
    elif action == "no_changes":
        state, note = MeetingPlanState.NO_PLAN, (
            "This meeting did not change the plan. Your confirmed to-dos are saved.")
    elif action in ("project_proposed", "plan_merged"):
        # Made, but not held: the plan's tasks wait on each other in a loop.
        state, note = MeetingPlanState.FAILED, (
            "The planner made a plan whose tasks wait on each other in a loop, "
            "so it was not offered. Try again, or plan it by hand.")
    else:
        state, note = MeetingPlanState.NO_PLAN, "Your confirmed to-dos are saved."
    meeting.plan_state = state.value
    meeting.plan_note = note


async def mark_plan_failed(meeting_id: str, error: str) -> None:
    """The planning job used up its retries: say so, never spin forever."""
    async with SessionLocal() as db:
        meeting = (
            await db.execute(select(Meeting).where(Meeting.id == meeting_id))
        ).scalar_one_or_none()
        if meeting is None or meeting.plan_state != MeetingPlanState.PLANNING.value:
            return
        meeting.plan_state = MeetingPlanState.FAILED.value
        meeting.plan_note = ("The planner could not finish this plan. Nothing was "
                             "lost: your confirmed to-dos are saved. Try again.")
        await notification_service.notify(
            db, org_id=meeting.org_id, user_id=meeting.agent_id,
            title="Planning failed. You can try again from the meeting",
            body=error[:300],
            kind="plan_failed", entity_type="meeting", entity_id=meeting_id,
        )
        await db.commit()


async def plan_meeting_safe(payload: dict[str, Any], job_id: str) -> dict[str, Any]:
    """`plan_meeting` that flags the meeting once retries are exhausted, as
    `process_meeting_safe` does for the pipeline. Before this, a planning job
    that kept failing ended in the dead-letter queue with nobody told."""
    from app.models.job import JobRecord

    try:
        return await plan_meeting(payload, job_id)
    except Exception as exc:
        async with SessionLocal() as db:
            job = (
                await db.execute(select(JobRecord).where(JobRecord.id == job_id))
            ).scalar_one_or_none()
            # attempts is incremented after this handler returns, hence the -1.
            if job is not None and job.attempts >= job.max_attempts - 1:
                await mark_plan_failed(payload["meeting_id"], str(exc))
        raise


async def mark_meeting_failed(meeting_id: str, error: str) -> None:
    """Called by the failure wrapper when all retries are exhausted."""
    async with SessionLocal() as db:
        meeting = (
            await db.execute(select(Meeting).where(Meeting.id == meeting_id))
        ).scalar_one_or_none()
        if meeting is not None:
            meeting.status = MeetingStatus.FAILED.value
            meeting.error = error[:1000]
            await notification_service.notify(
                db, org_id=meeting.org_id, user_id=meeting.agent_id,
                title="Meeting processing failed — you can retry from the meeting screen",
                body=error[:300],
                kind="meeting_failed", entity_type="meeting", entity_id=meeting_id,
            )
            await db.commit()


async def process_meeting_safe(payload: dict[str, Any], job_id: str) -> dict[str, Any]:
    """Wrapper that flags the meeting as failed once retries are exhausted."""
    from app.core.constants import JobStatus
    from app.models.job import JobRecord

    try:
        return await process_meeting(payload, job_id)
    except Exception as exc:
        async with SessionLocal() as db:
            job = (
                await db.execute(select(JobRecord).where(JobRecord.id == job_id))
            ).scalar_one_or_none()
            # attempts is incremented after this handler returns, hence the -1.
            if job is not None and job.attempts >= job.max_attempts - 1:
                await mark_meeting_failed(payload["meeting_id"], str(exc))
        raise
