"""AI usage (spec 6.10, 7.11, 7.12): what the AI costs this month and whether
its work is kept.

CRM figures come from `llm_usage`, whose cost is an ESTIMATE from the fixed
price list in `app/ai/llm.py`. Prospect Finder figures, once it is ported,
are what OpenRouter actually charged, read from its own spend table when that
table exists. The OpenRouter balance comes from the key's own endpoint and so
also covers spend `llm_usage` never sees (tests that use the live key).
"""
from __future__ import annotations

import calendar
import logging
import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, tzinfo

import httpx
from sqlalchemy import func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.constants import ApprovalEntityType, DecisionType, MeetingPlanState
from app.insights import common
from app.models.audit import LlmUsage
from app.models.comms import Approval
from app.models.meeting import Meeting, Transcript
from app.models.organisation import OrgSettings
from app.models.work import AIDecision

logger = logging.getLogger(__name__)

#: (key, label, purpose prefixes). First match wins, so the specific
#: `agent.proposal` sits before the catch-all `agent.`.
FEATURE_GROUPS: list[tuple[str, str, tuple[str, ...]]] = [
    ("proposals", "Writing proposals and contracts", ("proposal.", "agent.proposal")),
    ("meetings", "Reading meetings", ("conversation.analyse_",)),
    ("planning", "Planning tasks", ("planner.",)),
    ("emails", "Emails and replies",
     ("inbound.", "email.", "followup.", "communication.", "redraft")),
    ("cards", "Card scans", ("vision.",)),
    ("jarvis", "Jarvis assistant", ("orchestrator.", "agent.", "client_draft.", "assistant.")),
]
OTHER = ("other", "Other")

PROSPECT_TABLE = "prospect_spend"
PROSPECT_BRIEFS = "prospect_briefs"
PROSPECT_CAP_USD = 0.06
PROSPECT_STEPS = {
    "plan": "Planning the search", "quick_read": "Quick read", "offsite": "Reading their site",
    "search_exa": "Web search", "pitch": "Writing the pitch", "answer": "Answering questions",
    "video": "Video",
}

# GET https://openrouter.ai/api/v1/key (OpenRouter docs, "Limits", checked
# 23 Oct 2026) returns {"data": {"usage": credits used all time,
# "limit_remaining": credits left on the key or null when it has no limit,
# "usage_monthly": ..., ...}}.
OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
BALANCE_TTL = 600.0
SHOW_BALANCE_ENV = "SALES_HEAD_SHOW_PLATFORM_BALANCE"
BALANCE_TIMEOUT = 10.0
_balance_cache: dict[str, tuple[float, dict | None]] = {}

ACCURACY_NOTE = ("CRM figures are estimates from a price list. Prospect Finder figures are "
                 "what OpenRouter charged.")


def feature_of(purpose: str) -> tuple[str, str]:
    for key, label, prefixes in FEATURE_GROUPS:
        if any(purpose.startswith(p) for p in prefixes):
            return key, label
    return OTHER


def _provider() -> tuple[str, str]:
    s = get_settings()
    return s.llm_provider, s.openrouter_api_key


def _tier_models() -> tuple[str, str]:
    s = get_settings()
    if s.llm_provider == "openrouter":
        return s.openrouter_model_fast, s.openrouter_model_strong
    if s.llm_provider == "claude":
        return s.claude_model_fast, s.claude_model_strong
    return s.llm_model_fast, s.llm_model_strong


def platform_balance_shown() -> bool:
    """The OpenRouter key is the platform's own, shared by every organisation,
    so its balance is the platform's money and not one sales head's to see.
    Off unless the platform switches it on (SALES_HEAD_SHOW_PLATFORM_BALANCE=1)."""
    return os.environ.get(SHOW_BALANCE_ENV, "").strip().lower() in ("1", "true", "yes")


async def openrouter_balance() -> dict | None:
    """{"remaining_usd", "usage_usd"} for the configured key, or None when
    the card is off, the provider is not OpenRouter, or the call fails.
    Cached 10 minutes."""
    provider, key = _provider()
    if not platform_balance_shown() or provider != "openrouter" or not key:
        return None
    cached = _balance_cache.get(key)
    if cached is not None and time.monotonic() - cached[0] < BALANCE_TTL:
        return cached[1]
    result: dict | None = None
    try:
        async with httpx.AsyncClient(timeout=BALANCE_TIMEOUT) as client:
            resp = await client.get(OPENROUTER_KEY_URL,
                                    headers={"Authorization": f"Bearer {key}"})
        if resp.status_code == 200:
            data = (resp.json() or {}).get("data") or {}
            remaining, usage = data.get("limit_remaining"), data.get("usage")
            result = {"remaining_usd": None if remaining is None else float(remaining),
                      "usage_usd": None if usage is None else float(usage)}
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.info("OpenRouter balance not available: %s", exc)
    _balance_cache[key] = (time.monotonic(), result)
    return result


def _month_of(now: datetime, tz: tzinfo) -> str:
    today = common.local_day(now, tz)
    return f"{today.year:04d}-{today.month:02d}"


async def _has_table(db: AsyncSession, name: str) -> list[str] | None:
    """The table's column names, or None when it does not exist."""
    def look(sync_session):
        inspector = inspect(sync_session.connection())
        if not inspector.has_table(name):
            return None
        return [c["name"] for c in inspector.get_columns(name)]
    return await db.run_sync(look)


async def _prospect_rows(db, org_id, start, end) -> list[tuple] | None:
    """(run_id, institution_id, step, cost_usd, at) in [start, end), or None
    when the Prospect Finder is not connected."""
    columns = await _has_table(db, PROSPECT_TABLE)
    if columns is None or "org_id" not in columns:
        # Fail closed: a spend table that cannot say whose spend it is would
        # show every organisation the whole platform's Prospect Finder spend.
        return None
    sql = ("SELECT run_id, institution_id, step, cost_usd, at FROM prospect_spend "
           "WHERE at >= :start AND at < :end AND org_id = :org")
    rows = (await db.execute(text(sql), {"start": start, "end": end, "org": org_id})).all()
    return [(r[0], r[1], r[2], float(r[3] or 0), common.as_dt(r[4])) for r in rows]


async def _good_fits(db, org_id, start, end) -> int | None:
    columns = await _has_table(db, PROSPECT_BRIEFS)
    if columns is None or "verdict" not in columns or "org_id" not in columns:
        return None
    sql = ("SELECT COUNT(*) FROM prospect_briefs WHERE lower(verdict) LIKE 'good%' "
           "AND org_id = :org")
    params: dict = {"org": org_id}
    if "at" in columns:
        sql += " AND at >= :start AND at < :end"
        params.update(start=start, end=end)
    return int((await db.execute(text(sql), params)).scalar_one())


async def _crm_rows(db, org_id, start, end):
    return (await db.execute(
        select(LlmUsage.user_id, LlmUsage.model, LlmUsage.purpose, LlmUsage.cost_usd,
               LlmUsage.duration_ms, LlmUsage.error, LlmUsage.at)
        .where(LlmUsage.org_id == org_id, LlmUsage.at >= start, LlmUsage.at < end)
    )).all()


async def _budget(db, org_id) -> float:
    return float((await db.execute(
        select(OrgSettings.llm_monthly_budget_usd).where(OrgSettings.org_id == org_id)
    )).scalar_one_or_none() or get_settings().llm_default_org_monthly_budget_usd)


async def month_totals(db: AsyncSession, org_id: str, tz: tzinfo, now: datetime) -> dict:
    start, end = common.month_bounds_utc(_month_of(now, tz), tz)
    end = min(end, now)
    crm = float((await db.execute(
        select(func.coalesce(func.sum(LlmUsage.cost_usd), 0.0))
        .where(LlmUsage.org_id == org_id, LlmUsage.at >= start, LlmUsage.at < end)
    )).scalar_one())
    prospect_rows = await _prospect_rows(db, org_id, start, end) or []
    prospect = sum(r[3] for r in prospect_rows)
    return {"spent_usd": round(crm + prospect, 4), "budget_usd": await _budget(db, org_id),
            "crm_usd": round(crm, 4), "prospect_usd": round(prospect, 4)}


def _r(x: float) -> float:
    return round(x, 4)


async def build(db: AsyncSession, org_id: str, tz: tzinfo, now: datetime,
                month: str | None = None) -> dict:
    month = month or _month_of(now, tz)
    start, end = common.month_bounds_utc(month, tz)
    current = month == _month_of(now, tz)
    future = start > now
    end = min(end, now)
    crm = await _crm_rows(db, org_id, start, end) if not future else []
    prospect_rows = await _prospect_rows(db, org_id, start, end) if not future else None
    prospect_list = prospect_rows or []
    crm_usd = sum(float(r.cost_usd or 0) for r in crm)
    prospect_usd = sum(r[3] for r in prospect_list)
    spent = crm_usd + prospect_usd
    budget_usd = await _budget(db, org_id)

    year, mon = (int(x) for x in month.split("-"))
    days_in_month = calendar.monthrange(year, mon)[1]
    if current:
        elapsed = common.local_day(now, tz).day
        projected = _r(spent / elapsed * days_in_month) if spent else None
    else:
        projected = _r(spent)
    nothing = not crm and not prospect_list
    budget = common.block("empty" if nothing else "ok",
                          "No AI use in this month yet." if nothing else None,
                          spent_usd=_r(spent), budget_usd=budget_usd, projected_usd=projected)

    timed = [r.duration_ms for r in crm if r.duration_ms]
    health = common.block("empty" if not crm else "ok",
                          "No AI calls in this month yet." if not crm else None,
                          calls=len(crm), avg_ms=round(sum(timed) / len(timed)) if timed else None,
                          failed=sum(1 for r in crm if r.error))

    first = date(year, mon, 1)
    last = common.local_day(now, tz) if current else date(year, mon, days_in_month)
    per_day_crm: dict[date, float] = defaultdict(float)
    per_day_pf: dict[date, float] = defaultdict(float)
    for r in crm:
        per_day_crm[common.local_day(r.at, tz)] += float(r.cost_usd or 0)
    for r in prospect_list:
        per_day_pf[common.local_day(r[4], tz)] += r[3]
    days = []
    d = first
    while d <= last and not future:
        days.append({"date": d.isoformat(), "crm_usd": _r(per_day_crm.get(d, 0.0)),
                     "prospect_usd": _r(per_day_pf.get(d, 0.0))})
        d += timedelta(days=1)
    daily = common.block("empty" if nothing else "ok",
                         "No AI use in this month yet." if nothing else None, days=days)

    groups: dict[str, dict] = {}
    for r in crm:
        key, label = feature_of(r.purpose or "")
        g = groups.setdefault(key, {"key": key, "label": label, "usd": 0.0, "calls": 0})
        g["usd"] += float(r.cost_usd or 0)
        g["calls"] += 1
    feature_items = sorted(({**g, "usd": _r(g["usd"])} for g in groups.values()),
                           key=lambda g: (-g["usd"], g["key"]))
    features = (common.block(items=feature_items) if feature_items
                else common.block("empty", "No AI calls in this month yet.", items=[]))

    fast, strong = _tier_models()
    by_model: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for r in crm:
        by_model[r.model][0] += 1
        by_model[r.model][1] += float(r.cost_usd or 0)
    model_items = [{"model": m, "tier": "fast" if m == fast else "strong" if m == strong
                    else "other",
                    "calls_share": round(n / len(crm), 4),
                    "spend_share": round(usd / crm_usd, 4) if crm_usd else 0.0}
                   for m, (n, usd) in by_model.items()]
    model_items.sort(key=lambda m: -m["calls_share"])
    models = (common.block(items=model_items) if model_items
              else common.block("empty", "No AI calls in this month yet.", items=[]))

    people_names = await common.org_people(db, org_id)
    per_person: dict[str, float] = defaultdict(float)
    automatic = 0.0
    for r in crm:
        if r.user_id:
            per_person[r.user_id] += float(r.cost_usd or 0)
        else:
            automatic += float(r.cost_usd or 0)
    person_items = sorted(({"user_id": uid, "name": common.person_name(people_names, uid),
                            "usd": _r(usd)} for uid, usd in per_person.items()),
                          key=lambda p: (-p["usd"], p["name"] or ""))
    people = common.block("empty" if not crm else "ok",
                          "No AI calls in this month yet." if not crm else None,
                          items=person_items, automatic_usd=_r(automatic))

    return {
        "budget": budget, "health": health, "daily": daily, "features": features,
        "prospect": await _prospect_block(db, org_id, start, end, prospect_rows),
        "models": models, "people": people,
        "kept": await _kept(db, org_id, start, end),
        "free": await _free(db, org_id, start, end),
        "balance": await _balance_block(),
        "accuracy_note": ACCURACY_NOTE,
    }


async def _prospect_block(db, org_id, start, end, rows) -> dict:
    empty = dict(searches=0, institutions=0, good_fits=None, cost_per_institution=None,
                 cap_usd=PROSPECT_CAP_USD, cost_per_good_fit=None, steps=[])
    if rows is None:
        return common.block("empty", "Prospect Finder is not connected yet.", **empty)
    if not rows:
        return common.block("empty", "No Prospect Finder searches in this month.", **empty)
    total = sum(r[3] for r in rows)
    institutions = len({r[1] for r in rows if r[1]})
    good = await _good_fits(db, org_id, start, end)
    steps: dict[str, float] = defaultdict(float)
    for r in rows:
        steps[r[2] or "other"] += r[3]
    return common.block(
        searches=len({r[0] for r in rows if r[0]}), institutions=institutions,
        good_fits=good,
        cost_per_institution=_r(total / institutions) if institutions else None,
        cap_usd=PROSPECT_CAP_USD,
        cost_per_good_fit=_r(total / good) if good else None,
        steps=[{"step": s, "label": PROSPECT_STEPS.get(s, s.replace("_", " ").capitalize()),
                "usd": _r(usd)} for s, usd in sorted(steps.items(), key=lambda kv: -kv[1])])


async def _kept(db, org_id, start, end) -> dict:
    emails = {"approved": 0, "rejected": 0}
    for status, n in (await db.execute(
        select(Approval.status, func.count()).where(
            Approval.org_id == org_id,
            Approval.entity_type == ApprovalEntityType.OUTBOUND_MESSAGE.value,
            Approval.status.in_(("approved", "rejected")),
            Approval.decided_at >= start, Approval.decided_at < end)
        .group_by(Approval.status)
    )).all():
        emails[status] = int(n)
    held_at = func.coalesce(Meeting.started_at, Meeting.created_at)
    plans = {"approved": 0, "discarded": 0}
    for state, n in (await db.execute(
        select(Meeting.plan_state, func.count()).where(
            Meeting.org_id == org_id,
            Meeting.plan_state.in_((MeetingPlanState.APPROVED.value,
                                    MeetingPlanState.DISCARDED.value)),
            held_at >= start, held_at < end)
        .group_by(Meeting.plan_state)
    )).all():
        plans[state] = int(n)
    overrides = (await db.execute(
        select(AIDecision.human_override).where(
            AIDecision.org_id == org_id,
            AIDecision.decision_type == DecisionType.ASSIGNMENT.value,
            AIDecision.created_at >= start, AIDecision.created_at < end)
    )).scalars().all()
    assignments = {"kept": sum(1 for o in overrides if not (o or "").strip()),
                   "overridden": sum(1 for o in overrides if (o or "").strip())}
    if not any(emails.values()) and not any(plans.values()) and not overrides:
        return common.block("empty", "Nothing the AI drafted was decided on this month.",
                            emails=emails, plans=plans, assignments=assignments)
    return common.block(emails=emails, plans=plans, assignments=assignments)


async def _free(db, org_id, start, end) -> dict:
    held_at = func.coalesce(Meeting.started_at, Meeting.created_at)
    seconds = (await db.execute(
        select(func.coalesce(func.sum(Meeting.duration_seconds), 0)).where(
            Meeting.org_id == org_id, common.held_meeting(), held_at >= start, held_at < end)
    )).scalar_one()
    read = (await db.execute(
        select(func.count()).select_from(Meeting)
        .join(Transcript, Transcript.meeting_id == Meeting.id)
        .where(Meeting.org_id == org_id, held_at >= start, held_at < end)
    )).scalar_one()
    fields = dict(meeting_audio_hours=round(float(seconds or 0) / 3600, 1),
                  meetings_read=int(read))
    if not seconds and not read:
        return common.block("empty", "No meeting audio was transcribed this month.", **fields)
    return common.block(**fields)


async def _balance_block() -> dict:
    balance = await openrouter_balance()
    if balance is None:
        return common.block("empty", "Balance not available.", remaining_usd=None,
                            usage_usd=None)
    return common.block(**balance)
