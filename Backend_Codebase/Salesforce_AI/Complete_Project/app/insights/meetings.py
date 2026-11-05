"""Meeting intelligence (spec 6.7): how many meetings, how long the recorded
ones ran, what came out of them, the weekly rhythm, and the latest meetings
with the first line of their summary."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, tzinfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import MeetingPlanState
from app.insights import common, team
from app.models.action_item import ActionItem
from app.models.lead import Lead
from app.models.meeting import Meeting, Transcript

WEEKS = 8
LATEST = 10
SUMMARY_MAX = 140
PLAN_DECIDED = (MeetingPlanState.APPROVED.value, MeetingPlanState.DISCARDED.value,
                MeetingPlanState.SUPERSEDED.value, MeetingPlanState.SENT_FOR_APPROVAL.value,
                MeetingPlanState.READY.value)
_SENTENCE = re.compile(r"(.+?[.!?])(\s|$)", re.S)


def first_sentence(text: str | None) -> str | None:
    if not text or not text.strip():
        return None
    text = " ".join(text.split())
    match = _SENTENCE.match(text)
    line = match.group(1) if match else text
    if len(line) > SUMMARY_MAX:
        line = line[:SUMMARY_MAX - 3].rsplit(" ", 1)[0] + "..."
    return line


def _when(m: Meeting) -> datetime:
    return m.started_at or m.created_at


async def build(db: AsyncSession, org_id: str, tz: tzinfo, now: datetime, days: int = 7) -> dict:
    since = team.window_start(now, tz, days)
    today = common.local_day(now, tz)
    first_week = common.week_start(today) - timedelta(weeks=WEEKS - 1)
    earliest = min(since, common.day_bounds_utc(first_week, tz)[0])
    held_at = func.coalesce(Meeting.started_at, Meeting.created_at)
    rows = list((await db.execute(
        select(Meeting).where(Meeting.org_id == org_id, common.held_meeting(),
                              held_at >= earliest, held_at < now)
    )).scalars().all())
    in_window = [m for m in rows if _when(m) >= since]

    timed = [m.duration_seconds for m in in_window if m.duration_seconds]
    tasks = 0
    if in_window:
        tasks = (await db.execute(
            select(func.count()).select_from(ActionItem).where(
                ActionItem.org_id == org_id,
                ActionItem.meeting_id.in_([m.id for m in in_window]))
        )).scalar_one()
    fields = dict(
        count=len(in_window),
        hours=round(sum(timed) / 3600, 1),
        avg_minutes=round(sum(timed) / len(timed) / 60) if timed else None,
        tasks_created=int(tasks),
        plans_approved=sum(1 for m in in_window
                           if m.plan_state == MeetingPlanState.APPROVED.value),
        plans_total=sum(1 for m in in_window if m.plan_state in PLAN_DECIDED),
    )
    summary = (common.block(**fields) if in_window
               else common.block("empty", "No meetings in this period.", **fields))

    weekly = Counter(common.week_start(common.local_day(_when(m), tz)) for m in rows)
    weeks = [{"week_start": (first_week + timedelta(weeks=i)).isoformat(),
              "count": weekly.get(first_week + timedelta(weeks=i), 0)} for i in range(WEEKS)]
    per_week = (common.block(weeks=weeks) if any(w["count"] for w in weeks)
                else common.block("empty", "No meetings in the last eight weeks.", weeks=weeks))

    kinds = Counter(m.meeting_type or "other" for m in in_window)
    items = [{"type": k, "label": common.MEETING_TYPE_LABELS.get(k, "Not set"), "count": n}
             for k, n in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0] == "other", kv[0]))]
    types = (common.block(items=items) if items
             else common.block("empty", "No meetings in this period.", items=[]))

    return {"summary": summary, "per_week": per_week, "types": types,
            "latest": await _latest(db, org_id)}


async def _latest(db, org_id) -> dict:
    held_at = func.coalesce(Meeting.started_at, Meeting.created_at)
    rows = (await db.execute(
        select(Meeting, Lead.name, Transcript.summary)
        .join(Lead, Lead.id == Meeting.lead_id, isouter=True)
        .join(Transcript, Transcript.meeting_id == Meeting.id, isouter=True)
        .where(Meeting.org_id == org_id, common.held_meeting())
        .order_by(held_at.desc()).limit(LATEST)
    )).all()
    items = [{"meeting_id": m.id, "lead_id": m.lead_id, "lead_name": name,
              "type": m.meeting_type, "label": common.MEETING_TYPE_LABELS.get(
                  m.meeting_type or "", "Meeting"),
              "minutes": round(m.duration_seconds / 60) if m.duration_seconds else None,
              "summary": first_sentence(text), "at": common.iso_utc(_when(m))}
             for m, name, text in rows]
    if not items:
        return common.block("empty", "No meetings have been recorded yet.", items=[])
    return common.block(items=items)
