"""Person report card (spec 6.9) and consistency flags (7.10).

What the records show about one person over the last 7 or 30 days, beside
the middle of their colleagues in the same role (7.14). A sales agent is
read as the opener of their deals and everyone else as the closer (7.1b):
the owner of a lead is usually the person who opened it, and the person who
wins it is someone else, so a sales lead moving an agent's lead forward is
the normal hand-over and never a flag.

The flags are evidence, not a verdict. Each names the date and the client
or task, so the sales head can look for themselves.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta, tzinfo
from statistics import median

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DeclineReason, LeadState, Role
from app.core.exceptions import NotFoundError
from app.insights import common, team
from app.models.action_item import ActionItem
from app.models.audit import AuditLog
from app.models.demo import Demo
from app.models.followup import FollowUp
from app.models.lead import Contact, Lead
from app.models.location import STATUS_DENIED, STATUS_OK, LocationPing
from app.models.meeting import Meeting
from app.models.messaging import OutboundMessage
from app.models.organisation import OrgSettings
from app.models.proposal import Proposal
from app.models.user import User
from app.models.work import Assignment

DECLINE_LABELS = {
    DeclineReason.BUSY.value: "Too busy",
    DeclineReason.WRONG_SKILL.value: "Not the right skills",
    DeclineReason.ON_SITE_ELSEWHERE.value: "On site elsewhere",
    DeclineReason.OTHER.value: "Other",
}
EFFORT = (("meetings", "Meetings"), ("emails", "Emails sent"), ("notes", "Client notes"),
          ("contacts", "Contacts added"), ("jarvis", "Jarvis chats"),
          ("active_days", "Active days"))
NOT_COUNTED = ("cancelled", "superseded", "declined")
OPEN_STATUSES = ("open", "in_progress", "pending_review")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
BURST_SIZE = 5
BURST_WINDOW = timedelta(minutes=10)
MOVE_LOOKBACK = timedelta(days=7)
FOLLOWUP_SLACK = timedelta(days=1)
REFUSED_DAYS = 3
BY_STATE_ORDER = common.STAGE_ORDER + (LeadState.COLD.value, LeadState.LOST_FOR_NOW.value)


def _day_text(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


def _days_text(n: float | None) -> str:
    if n is None:
        return "Not yet"
    n = int(math.floor(n + 0.5))
    return f"{n} day" if n == 1 else f"{n} days"


def _middle(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return median(values) if values else None


def _whole(x: float | None) -> int:
    return 0 if x is None else int(math.floor(x + 0.5))


class _Context:
    """Everything the card reads, loaded once for the whole organisation."""

    async def load(self, db: AsyncSession, org_id: str, tz: tzinfo, now: datetime,
                   days: int) -> "_Context":
        self.db, self.org_id, self.tz, self.now = db, org_id, tz, now
        self.since = team.window_start(now, tz, days)
        self.today = common.local_day(now, tz)
        self.first_day = self.today - timedelta(days=days - 1)
        self.people = await common.org_people(db, org_id)
        self.leads = list((await db.execute(
            select(Lead).where(Lead.org_id == org_id))).scalars().all())
        self.lead_by_id = {lead.id: lead for lead in self.leads}
        self.past = await common.history(db, org_id)
        self.owners = await common.deal_people(db, org_id, self.leads)
        self.counts = await team.counts_by_person(db, org_id, self.since, now)
        self.actions = await team.actions(db, org_id, self.since, now)
        self.logins = (await db.execute(
            select(AuditLog.user_id, AuditLog.at).where(
                AuditLog.org_id == org_id, AuditLog.action == "auth.login",
                AuditLog.at >= self.since, AuditLog.at < now)
        )).all()
        self.pings = list((await db.execute(
            select(LocationPing).where(LocationPing.org_id == org_id,
                                       LocationPing.captured_at >= self.since,
                                       LocationPing.captured_at < now)
        )).scalars().all())
        self.handovers = await self._handovers()
        self.tasks = list((await db.execute(
            select(ActionItem).where(ActionItem.org_id == org_id))).scalars().all())
        quiet = await common.last_activity(
            db, org_id, [lead.id for lead in self.leads if lead.state in common.IN_PLAY], now)
        self.quiet_days = {
            lead_id: common.days_between(at or self.lead_by_id[lead_id].created_at, now)
            for lead_id, at in quiet.items()}
        return self

    async def _handovers(self) -> list[tuple[str, str, datetime]]:
        """(lead_id, to_user, at): a lead created for someone else, or its
        owner changed, in the window."""
        out = []
        for action, by, lead_id, detail, at in (await self.db.execute(
            select(AuditLog.action, AuditLog.user_id, AuditLog.entity_id, AuditLog.detail,
                   AuditLog.at).where(
                AuditLog.org_id == self.org_id,
                AuditLog.action.in_(("lead.created", "lead.updated")),
                AuditLog.at >= self.since, AuditLog.at < self.now)
        )).all():
            to = (detail or {}).get("owner_id")
            if not to or (action == "lead.created" and to == by):
                continue
            out.append((lead_id, to, at))
        return out

    def moves_by(self, user_id: str):
        for lead_id, rows in self.past.items():
            for row in rows:
                if (row.changed_by == user_id and row.from_state is not None
                        and self.since <= row.changed_at < self.now):
                    yield lead_id, row

    def activity_times(self, user_id: str) -> list[datetime]:
        times = [at for who, _kind, at, _s in self.actions if who == user_id]
        times += [at for who, at in self.logins if who == user_id]
        times += [p.captured_at for p in self.pings if p.user_id == user_id]
        times += [row.changed_at for _lead, row in self.moves_by(user_id)]
        return sorted(times)

    def active_days(self, user_id: str) -> set[date]:
        return {common.local_day(at, self.tz) for at in self.activity_times(user_id)}

    def colleagues(self, user: User) -> list[User]:
        return [u for u in self.people.values()
                if u.role == user.role and u.id != user.id and u.is_active]


# ── tasks ───────────────────────────────────────────────────────────────────

def _task_split(ctx: _Context, user_id: str) -> dict:
    due_in_window = [t for t in ctx.tasks
                     if t.assignee_id == user_id and t.due_date is not None
                     and t.status not in NOT_COUNTED
                     and ctx.since <= t.due_date <= ctx.now]
    on_time = late = 0
    for t in due_in_window:
        if t.completed_at is None:
            continue
        if common.local_day(t.completed_at, ctx.tz) <= common.local_day(t.due_date, ctx.tz):
            on_time += 1
        else:
            late += 1
    overdue = sum(1 for t in ctx.tasks
                  if t.assignee_id == user_id and t.status in OPEN_STATUSES
                  and t.due_date is not None and t.due_date < ctx.now)
    return {"assigned": len(due_in_window), "on_time": on_time, "late": late,
            "overdue": overdue}


async def _tasks_block(ctx: _Context, user: User) -> dict:
    split = _task_split(ctx, user.id)
    declined = (await ctx.db.execute(
        select(Assignment.decline_reason, Assignment.decline_note).where(
            Assignment.org_id == ctx.org_id, Assignment.to_user_id == user.id,
            Assignment.status == "declined", Assignment.decided_at >= ctx.since,
            Assignment.decided_at < ctx.now)
    )).all()
    reasons = []
    for reason, note in declined:
        label = DECLINE_LABELS.get(reason or "", "No reason given")
        reasons.append(f"{label}: {note}" if note else label)
    followups = (await ctx.db.execute(
        select(FollowUp).where(FollowUp.org_id == ctx.org_id, FollowUp.owner_id == user.id,
                               FollowUp.due_date >= ctx.first_day,
                               FollowUp.due_date <= ctx.today)
    )).scalars().all()
    done_on_day = sum(1 for f in followups if f.completed_at is not None
                      and common.local_day(f.completed_at, ctx.tz) <= f.due_date)
    missed = sum(1 for f in followups if f.due_date < ctx.today and not (
        f.completed_at is not None and common.local_day(f.completed_at, ctx.tz) <= f.due_date))
    fields = dict(split, declined=len(declined), decline_reasons=reasons,
                  followups={"due": len(followups), "done_on_day": done_on_day,
                             "missed": missed})
    if not split["assigned"] and not split["overdue"] and not declined and not followups:
        return common.block("empty", "No tasks or follow-ups were due in this period.",
                            **fields)
    return common.block(**fields)


def _rate(split: dict) -> float | None:
    return round(split["on_time"] / split["assigned"], 2) if split["assigned"] else None


# ── the role-aware block ────────────────────────────────────────────────────

def _untouched(ctx: _Context, user_id: str) -> int:
    return sum(1 for lead_id, (opener, closer) in ctx.owners.items()
               if user_id in (opener, closer)
               and ctx.lead_by_id[lead_id].state in common.IN_PLAY
               and ctx.quiet_days.get(lead_id, 0) >= common.UNTOUCHED_DAYS)


def _opener_stats(ctx: _Context, user_id: str) -> list[tuple[str, float | None, str]]:
    mine = [lead for lead in ctx.leads if lead.owner_id == user_id]
    calling = [lead for lead in mine if lead.state == LeadState.COLD_CALLING.value]
    calling_days = [common.days_between(
        common.current_visit_start(ctx.past.get(lead.id, []), lead.created_at), ctx.now)
        for lead in calling]
    moves = list(ctx.moves_by(user_id))
    handed = [(lead_id, at) for lead_id, to, at in ctx.handovers if to == user_id]
    first_contact = []
    for lead_id, at in handed:
        later = [c.created_at for c in ctx.contact_rows
                 if c.lead_id == lead_id and c.created_by == user_id and c.created_at >= at]
        if later:
            first_contact.append((min(later) - at).total_seconds() / 86400)
    return [
        ("Leads handed over", len(handed), "count"),
        ("Still in cold calling", len(calling), "count"),
        ("Days in cold calling", sum(calling_days) / len(calling_days) if calling_days else None,
         "days"),
        ("Opened", sum(1 for _l, r in moves if r.from_state == LeadState.COLD_CALLING.value
                       and r.to_state == LeadState.OPEN.value), "count"),
        ("Lost for now", sum(1 for _l, r in moves if r.to_state == LeadState.LOST_FOR_NOW.value),
         "count"),
        ("Contacts added", ctx.counts.get(user_id, {}).get("contacts", 0), "count"),
        ("Hand-over to first contact", median(first_contact) if first_contact else None, "days"),
        ("Deals untouched 10+ days", _untouched(ctx, user_id), "count"),
    ]


def _closer_stats(ctx: _Context, user_id: str) -> list[tuple[str, float | None, str]]:
    moves = list(ctx.moves_by(user_id))
    closing = {lead_id for lead_id, (_o, closer) in ctx.owners.items() if closer == user_id}
    demos = sum(1 for d in ctx.demo_rows if d.lead_id in closing and d.completed_at is not None
                and ctx.since <= d.completed_at < ctx.now)
    proposals = sum(1 for p in ctx.proposal_rows if p.created_by == user_id
                    and p.sent_at is not None and ctx.since <= p.sent_at < ctx.now)
    handed_out = sum(1 for lead_id, to, at in ctx.handovers
                     if to != user_id and ctx.creator.get(lead_id) == user_id)
    c = ctx.counts.get(user_id, {})
    return [
        ("Moved forward", sum(1 for _l, r in moves if common.is_forward(r.from_state, r.to_state)),
         "count"),
        ("Meetings held", c.get("meetings", 0), "count"),
        ("Demos done", demos, "count"),
        ("Proposals sent", proposals, "count"),
        ("Follow-ups done", c.get("followups", 0), "count"),
        ("Leads created and handed out", handed_out, "count"),
        ("Deals untouched 10+ days", _untouched(ctx, user_id), "count"),
    ]


def _format(value: float | None, kind: str) -> str:
    if kind == "days":
        return _days_text(value)
    return str(_whole(value))


def _by_state(ctx: _Context, lead_ids) -> list[dict]:
    counts: dict[str, int] = defaultdict(int)
    for lead_id in lead_ids:
        counts[ctx.lead_by_id[lead_id].state] += 1
    return [{"state": s, "label": common.STATE_LABELS[s], "count": counts[s]}
            for s in BY_STATE_ORDER if counts.get(s)]


def _leads_block(ctx: _Context, user: User) -> dict:
    opener = user.role == Role.SALES_AGENT.value
    stats_of = _opener_stats if opener else _closer_stats
    mine = stats_of(ctx, user.id)
    theirs = [stats_of(ctx, u.id) for u in ctx.colleagues(user)]
    stats = []
    for i, (label, value, kind) in enumerate(mine):
        middle = _middle([row[i][1] for row in theirs])
        stats.append({"label": label, "value": _format(value, kind),
                      "team_value": None if not theirs or middle is None
                      else _format(middle, kind)})
    if opener:
        ids = [lead.id for lead in ctx.leads if lead.owner_id == user.id]
    else:
        ids = [lead_id for lead_id, (_o, closer) in ctx.owners.items() if closer == user.id]
    return common.block(role_kind="opener" if opener else "closer",
                        by_state=_by_state(ctx, ids), stats=stats)


# ── effort and the working day ──────────────────────────────────────────────

def _effort_values(ctx: _Context, user_id: str) -> dict[str, int]:
    c = ctx.counts.get(user_id, {})
    out = {key: int(c.get(key, 0)) for key, _ in EFFORT if key != "active_days"}
    out["active_days"] = len(ctx.active_days(user_id))
    return out


def _effort_block(ctx: _Context, user: User) -> dict:
    mine = _effort_values(ctx, user.id)
    theirs = [_effort_values(ctx, u.id) for u in ctx.colleagues(user)]
    items = [{"key": key, "label": label, "value": mine[key],
              "team_middle": _whole(_middle([t[key] for t in theirs])) if theirs else mine[key]}
             for key, label in EFFORT]
    if not theirs:
        return common.block("thin", "Nobody else has this role, so there is no middle to compare.",
                            items=items)
    return common.block(items=items)


def _spans_block(ctx: _Context, user_id: str) -> dict:
    by_day: dict[date, list[datetime]] = defaultdict(list)
    for at in ctx.activity_times(user_id):
        by_day[common.local_day(at, ctx.tz)].append(at)
    days = []
    for i in range((ctx.today - ctx.first_day).days + 1):
        d = ctx.first_day + timedelta(days=i)
        times = by_day.get(d)
        days.append({
            "date": d.isoformat(),
            "first": None if not times else common.to_local_hm(min(times), ctx.tz),
            "last": None if not times else common.to_local_hm(max(times), ctx.tz),
        })
    if not by_day:
        return common.block("empty", "Nothing was recorded for this person in this period.",
                            days=days)
    return common.block(days=days)


def _field_block(ctx: _Context, user_id: str) -> dict:
    mine = [p for p in ctx.pings if p.user_id == user_id]
    seen = {common.local_day(p.captured_at, ctx.tz) for p in mine if p.status == STATUS_OK}
    fake = sum(1 for p in mine if p.is_mock)
    if not mine:
        return common.block("empty", "No field readings from this person in this period.",
                            days_seen=0, fake_gps=0)
    return common.block(days_seen=len(seen), fake_gps=fake)


# ── flags (spec 7.10) ───────────────────────────────────────────────────────

async def _flags(ctx: _Context, user: User) -> list[dict]:
    out: list[dict] = []

    def flag(kind, title, evidence, at, subject=None):
        out.append({"kind": kind, "title": title, "evidence": evidence,
                    "at": common.iso_utc(at), "subject": subject})

    # 1. A forward move with nothing on the lead in the week before.
    for lead_id, row in ctx.moves_by(user.id):
        if not common.is_forward(row.from_state, row.to_state):
            continue
        lead = ctx.lead_by_id.get(lead_id)
        if lead is None:
            continue
        owner_role = ctx.people[lead.owner_id].role if lead.owner_id in ctx.people else None
        if (user.role == Role.SALES_LEAD.value and owner_role == Role.SALES_AGENT.value
                and row.from_state != LeadState.COLD_CALLING.value):
            continue        # the closer taking an opener's deal on: the normal hand-over
        before = await common.activity_by_lead(ctx.db, ctx.org_id,
                                               row.changed_at - MOVE_LOOKBACK, row.changed_at)
        if before.get(lead_id):
            continue
        flag("moved_without_activity", "Moved with nothing behind it",
             f"Moved {lead.name} from {common.STATE_LABELS.get(row.from_state, row.from_state)}"
             f" to {common.STATE_LABELS.get(row.to_state, row.to_state)} on "
             f"{_day_text(common.local_day(row.changed_at, ctx.tz))}, with nothing recorded "
             "on it in the week before.",
             row.changed_at, {"type": "deal", "id": lead_id})

    # 2. Five or more tasks closed within ten minutes, none with a note.
    closed = sorted((t for t in ctx.tasks
                     if t.assignee_id == user.id and t.completed_at is not None
                     and ctx.since <= t.completed_at < ctx.now and not (t.result_note or "").strip()
                     and t.completion_method != "manual_upload"),
                    key=lambda t: t.completed_at)
    i = 0
    while i < len(closed):
        j = i
        while (j + 1 < len(closed)
               and closed[j + 1].completed_at - closed[i].completed_at <= BURST_WINDOW):
            j += 1
        if j - i + 1 >= BURST_SIZE:
            first, last = closed[i].completed_at, closed[j].completed_at
            flag("task_burst", "Tasks closed in a burst",
                 f"{j - i + 1} tasks marked done between {common.to_local_hm(first, ctx.tz)} "
                 f"and {common.to_local_hm(last, ctx.tz)} on "
                 f"{_day_text(common.local_day(first, ctx.tz))}, none with a note.", first)
            i = j + 1
        else:
            i += 1

    # 3. A follow-up marked done with no message and no meeting near it.
    done = (await ctx.db.execute(
        select(FollowUp).where(FollowUp.org_id == ctx.org_id, FollowUp.owner_id == user.id,
                               FollowUp.completed_at >= ctx.since,
                               FollowUp.completed_at < ctx.now,
                               FollowUp.message_id.is_(None))
    )).scalars().all()
    for f in done:
        lo, hi = f.completed_at - FOLLOWUP_SLACK, f.completed_at + FOLLOWUP_SLACK
        sent = (await ctx.db.execute(select(OutboundMessage.id).where(
            OutboundMessage.org_id == ctx.org_id, OutboundMessage.lead_id == f.lead_id,
            OutboundMessage.sent_at >= lo, OutboundMessage.sent_at <= hi).limit(1))).first()
        met = (await ctx.db.execute(select(Meeting.id).where(
            Meeting.org_id == ctx.org_id, Meeting.lead_id == f.lead_id,
            common.held_meeting(),
            Meeting.started_at >= lo, Meeting.started_at <= hi).limit(1))).first()
        if sent or met:
            continue
        lead = ctx.lead_by_id.get(f.lead_id)
        name = lead.name if lead else "a client"
        flag("followup_nothing_sent", "Follow-up done, nothing sent",
             f"The follow-up with {name} was marked done on "
             f"{_day_text(common.local_day(f.completed_at, ctx.tz))}, but no message or "
             "meeting was recorded within a day of it.",
             f.completed_at, {"type": "deal", "id": f.lead_id} if lead else None)

    # 4. Location: fake GPS, or location refused on three days or more.
    mine = [p for p in ctx.pings if p.user_id == user.id]
    fake = sorted((p for p in mine if p.is_mock), key=lambda p: p.captured_at)
    if fake:
        days = sorted({common.local_day(p.captured_at, ctx.tz) for p in fake})
        flag("location", "Fake GPS reading",
             f"{len(fake)} reading{'s' if len(fake) != 1 else ''} came from a fake GPS app "
             f"({', '.join(_day_text(d) for d in days)}).", fake[-1].captured_at)
    refused = sorted({common.local_day(p.captured_at, ctx.tz) for p in mine
                      if p.status == STATUS_DENIED})
    if len(refused) >= REFUSED_DAYS:
        last = max(p.captured_at for p in mine if p.status == STATUS_DENIED)
        flag("location", "Location refused",
             f"Location permission was refused on {len(refused)} days "
             f"({', '.join(_day_text(d) for d in refused)}).", last)

    # 5. A working day with nothing recorded and no app open, not on leave.
    working = user.working_days or ctx.working_days
    joined = common.local_day(user.created_at, ctx.tz) if user.created_at else ctx.first_day
    active = ctx.active_days(user.id)
    d = max(ctx.first_day, joined)
    while d < ctx.today:
        on_leave = (user.on_leave_from is not None and user.on_leave_to is not None
                    and user.on_leave_from <= d <= user.on_leave_to)
        if WEEKDAYS[d.weekday()] in working and not on_leave and d not in active:
            flag("silent_working_day", "A working day with nothing recorded",
                 f"Nothing was recorded on {d.strftime('%A')} {_day_text(d)}, and the app "
                 "was not opened.", common.day_bounds_utc(d, ctx.tz)[0])
        d += timedelta(days=1)

    out.sort(key=lambda f: f["at"] or "", reverse=True)
    return out


async def _context(db, org_id, tz, now, days) -> _Context:
    ctx = await _Context().load(db, org_id, tz, now, days)
    ctx.contact_rows = list((await db.execute(
        select(Contact).where(Contact.org_id == org_id))).scalars().all())
    ctx.demo_rows = list((await db.execute(
        select(Demo).where(Demo.org_id == org_id))).scalars().all())
    ctx.proposal_rows = list((await db.execute(
        select(Proposal).where(Proposal.org_id == org_id))).scalars().all())
    ctx.creator = dict((await db.execute(
        select(AuditLog.entity_id, AuditLog.user_id).where(
            AuditLog.org_id == org_id, AuditLog.action == "lead.created"))).all())
    ctx.working_days = (await db.execute(
        select(OrgSettings.working_days).where(OrgSettings.org_id == org_id)
    )).scalar_one_or_none() or ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    return ctx


def _user(ctx: _Context, user_id: str) -> User:
    user = ctx.people.get(user_id)
    if user is None:
        raise NotFoundError("Person not found")
    return user


async def flags(db: AsyncSession, org_id: str, tz: tzinfo, now: datetime, user_id: str,
                days: int) -> list[dict]:
    ctx = await _context(db, org_id, tz, now, days)
    return await _flags(ctx, _user(ctx, user_id))


async def build(db: AsyncSession, org_id: str, tz: tzinfo, now: datetime, user_id: str,
                days: int = 7) -> dict:
    ctx = await _context(db, org_id, tz, now, days)
    user = _user(ctx, user_id)
    split = _task_split(ctx, user.id)
    colleagues = ctx.colleagues(user)
    team_split = [_task_split(ctx, u.id) for u in colleagues]
    team_due = sum(s["assigned"] for s in team_split)
    team_rate = (round(sum(s["on_time"] for s in team_split) / team_due, 2)
                 if team_due else None)
    rate = _rate(split)
    follow_through = common.block(
        "ok" if rate is not None else "empty",
        None if rate is not None else "No tasks were due in this period.",
        on_time_rate=rate, team_rate=team_rate)
    found = await _flags(ctx, user)
    return {
        "person": common.block(
            user_id=user.id, name=user.name, role=user.role,
            role_label=common.ROLE_LABELS.get(user.role, user.role.replace("_", " ")),
            since=common.local_day(user.created_at, tz).isoformat() if user.created_at else None,
            is_active=bool(user.is_active)),
        "follow_through": follow_through,
        "leads": _leads_block(ctx, user),
        "tasks": await _tasks_block(ctx, user),
        "effort": _effort_block(ctx, user),
        "day_spans": _spans_block(ctx, user.id),
        "field": _field_block(ctx, user.id),
        "flags": common.block(
            "ok", None if found else "Nothing unusual in this period.", items=found),
    }
