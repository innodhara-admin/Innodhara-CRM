"""AI usage (spec 6.10, 7.11, 7.12): spend against the monthly budget, where
it goes, which models, who, whether the AI's work is kept, the Prospect
Finder when it is connected, and the OpenRouter balance. No network: the
balance call goes through a fake transport."""
from __future__ import annotations

from datetime import datetime, timedelta

import httpx
from sqlalchemy import text

from app.core import clock
from app.insights import ai_usage
from app.models.comms import Approval
from app.models.work import AIDecision
from tests.insights.builders import (
    make_lead, make_meeting, make_org, make_usage, make_user,
)

NOW = datetime(2026, 10, 10, 6, 0)          # day 10 of a 31-day month
DAY = timedelta(days=1)
TZ = clock.zone("Asia/Kolkata")
FAST = "openai/gpt-5.4-nano"
STRONG = "google/gemini-2.5-flash"


async def _org(db, budget=50.0):
    org = await make_org(db, name="AI Org", budget=budget)
    asha = await make_user(db, org, name="Asha", role="sales_agent")
    return org, asha


async def test_month_totals_and_projection(db):
    org, asha = await _org(db)
    await make_usage(db, org, user=asha, model=FAST, purpose="orchestrator.route", cost=1.0,
                     at=NOW - DAY)
    await make_usage(db, org, model=STRONG, purpose="proposal.docx_tagfill", cost=4.0,
                     at=NOW - 2 * DAY)
    await make_usage(db, org, model=FAST, purpose="orchestrator.route", cost=9.0,
                     at=datetime(2026, 9, 20))                            # last month
    totals = await ai_usage.month_totals(db, org.id, TZ, NOW)
    assert totals == {"spent_usd": 5.0, "budget_usd": 50.0, "crm_usd": 5.0, "prospect_usd": 0.0}
    budget = (await ai_usage.build(db, org.id, TZ, NOW, month="2026-10"))["budget"]
    assert budget["spent_usd"] == 5.0 and budget["budget_usd"] == 50.0
    # 5.0 over 10 days (the 10th counts) → 15.5 by the 31st
    assert budget["projected_usd"] == 15.5
    september = (await ai_usage.build(db, org.id, TZ, NOW, month="2026-09"))["budget"]
    assert september["spent_usd"] == 9.0 and september["projected_usd"] == 9.0


async def test_health_and_daily(db):
    org, _ = await _org(db)
    await make_usage(db, org, model=FAST, purpose="orchestrator.route", cost=0.5,
                     at=NOW - DAY, duration_ms=1000)
    await make_usage(db, org, model=FAST, purpose="orchestrator.route", cost=0.0,
                     at=NOW - DAY, duration_ms=3000, error="timeout")
    result = await ai_usage.build(db, org.id, TZ, NOW, month="2026-10")
    assert (result["health"]["calls"], result["health"]["avg_ms"],
            result["health"]["failed"]) == (2, 2000, 1)
    days = result["daily"]["days"]
    assert [d["date"] for d in days][:2] == ["2026-10-01", "2026-10-02"]
    assert len(days) == 10                                   # up to today
    assert next(d for d in days if d["date"] == "2026-10-09")["crm_usd"] == 0.5


async def test_feature_grouping_and_other(db):
    org, _ = await _org(db)
    for purpose, cost in (("proposal.docx_tagfill", 1.0), ("agent.proposal", 1.0),
                          ("orchestrator.route", 0.5), ("agent.query", 0.25),
                          ("client_draft.interpret", 0.25), ("conversation.analyse_meeting", 0.4),
                          ("planner.generate_initial_plan", 0.3),
                          ("communication.gentle first nudge on a silent thread", 0.2),
                          ("email.draft_custom", 0.1), ("vision.business_card", 0.05),
                          ("something.new", 0.01)):
        await make_usage(db, org, model=FAST, purpose=purpose, cost=cost, at=NOW - DAY)
    items = {i["key"]: i for i in (await ai_usage.build(
        db, org.id, TZ, NOW, month="2026-10"))["features"]["items"]}
    assert items["proposals"]["usd"] == 2.0 and items["proposals"]["calls"] == 2
    assert items["jarvis"]["usd"] == 1.0 and items["jarvis"]["calls"] == 3
    assert items["meetings"]["usd"] == 0.4
    assert items["planning"]["usd"] == 0.3
    assert items["emails"]["usd"] == 0.3
    assert items["cards"]["usd"] == 0.05
    assert (items["other"]["label"], items["other"]["usd"]) == ("Other", 0.01)


async def test_models_shares_sum_to_one(db):
    org, _ = await _org(db)
    for _ in range(3):
        await make_usage(db, org, model=FAST, purpose="orchestrator.route", cost=0.1,
                         at=NOW - DAY)
    await make_usage(db, org, model=STRONG, purpose="proposal.docx_tagfill", cost=0.7,
                     at=NOW - DAY)
    models = (await ai_usage.build(db, org.id, TZ, NOW, month="2026-10"))["models"]["items"]
    by = {m["model"]: m for m in models}
    assert by[FAST]["calls_share"] == 0.75 and by[STRONG]["spend_share"] == 0.7
    assert abs(sum(m["calls_share"] for m in models) - 1) < 1e-9
    assert abs(sum(m["spend_share"] for m in models) - 1) < 1e-9
    assert {m["tier"] for m in models} <= {"fast", "strong", "other"}


async def test_people_and_automatic(db):
    org, asha = await _org(db)
    await make_usage(db, org, user=asha, model=FAST, purpose="orchestrator.route", cost=0.3,
                     at=NOW - DAY)
    await make_usage(db, org, user="former-person", model=FAST, purpose="agent.query",
                     cost=0.2, at=NOW - DAY)
    await make_usage(db, org, model=FAST, purpose="inbound.classify", cost=0.5, at=NOW - DAY)
    people = (await ai_usage.build(db, org.id, TZ, NOW, month="2026-10"))["people"]
    assert people["items"] == [{"user_id": asha.id, "name": "Asha", "usd": 0.3},
                               {"user_id": "former-person", "name": "Former colleague",
                                "usd": 0.2}]
    assert people["automatic_usd"] == 0.5


async def test_work_kept(db):
    org, asha = await _org(db)
    for status in ("approved", "approved", "rejected", "pending"):
        db.add(Approval(org_id=org.id, entity_type="outbound_message", status=status,
                        requested_at=NOW - 2 * DAY,
                        decided_at=None if status == "pending" else NOW - DAY))
    lead = await make_lead(db, org, name="Kept Client", state="open", created_at=NOW - 9 * DAY)
    await make_meeting(db, org, lead, by=asha, at=NOW - DAY, plan_state="approved")
    await make_meeting(db, org, lead, by=asha, at=NOW - DAY, plan_state="discarded",
                       minutes=90, summary="A summary.")
    for override in (None, None, "Gave it to Bala"):
        db.add(AIDecision(org_id=org.id, decision_type="assignment", human_override=override,
                          created_at=NOW - DAY))
    await db.flush()
    result = await ai_usage.build(db, org.id, TZ, NOW, month="2026-10")
    kept = result["kept"]
    assert kept["emails"] == {"approved": 2, "rejected": 1}
    assert kept["plans"] == {"approved": 1, "discarded": 1}
    assert kept["assignments"] == {"kept": 2, "overridden": 1}
    assert result["free"] == {"status": "ok", "note": None, "meeting_audio_hours": 1.5,
                              "meetings_read": 1}


async def test_prospect_not_connected(db):
    org, _ = await _org(db)
    prospect = (await ai_usage.build(db, org.id, TZ, NOW, month="2026-10"))["prospect"]
    assert prospect["status"] == "empty"
    assert prospect["note"] == "Prospect Finder is not connected yet."
    assert prospect["cap_usd"] == 0.06 and prospect["steps"] == []


async def test_prospect_connected_when_table_exists(db):
    org, _ = await _org(db)
    await db.execute(text(
        "CREATE TABLE prospect_spend (id INTEGER PRIMARY KEY, org_id TEXT, run_id TEXT, "
        "institution_id TEXT, step TEXT, model TEXT, tokens INTEGER, cost_usd REAL, "
        "at TIMESTAMP)"))
    for org_id, run, inst, step, cost in ((org.id, "r1", "i1", "plan", 0.01),
                                          (org.id, "r1", "i1", "pitch", 0.03),
                                          (org.id, "r2", "i2", "plan", 0.02),
                                          ("another-org", "r9", "i9", "plan", 5.0)):
        await db.execute(text(
            "INSERT INTO prospect_spend (org_id, run_id, institution_id, step, model, tokens, "
            "cost_usd, at) VALUES (:o, :r, :i, :s, 'm', 10, :c, :a)"),
            {"o": org_id, "r": run, "i": inst, "s": step, "c": cost, "a": NOW - DAY})
    result = await ai_usage.build(db, org.id, TZ, NOW, month="2026-10")
    prospect = result["prospect"]
    assert prospect["status"] == "ok"
    assert (prospect["searches"], prospect["institutions"]) == (2, 2)
    assert prospect["cost_per_institution"] == 0.03 and prospect["good_fits"] is None
    assert {s["step"]: s["usd"] for s in prospect["steps"]} == {"plan": 0.03, "pitch": 0.03}
    assert result["budget"]["spent_usd"] == 0.06
    totals = await ai_usage.month_totals(db, org.id, TZ, NOW)
    assert (totals["crm_usd"], totals["prospect_usd"]) == (0.0, 0.06)


def _fake_client(handler):
    real = httpx.AsyncClient

    def make(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)
    return make


async def test_balance_success(db, monkeypatch):
    seen = {}

    def handler(request):
        seen["url"], seen["auth"] = str(request.url), request.headers.get("authorization")
        return httpx.Response(200, json={"data": {"usage": 3.25, "limit_remaining": 46.75}})
    monkeypatch.setattr(ai_usage.httpx, "AsyncClient", _fake_client(handler))
    monkeypatch.setattr(ai_usage, "_provider", lambda: ("openrouter", "sk-test"))
    monkeypatch.setenv("SALES_HEAD_SHOW_PLATFORM_BALANCE", "1")
    assert await ai_usage.openrouter_balance() == {"remaining_usd": 46.75, "usage_usd": 3.25}
    assert seen["url"] == "https://openrouter.ai/api/v1/key"
    assert seen["auth"] == "Bearer sk-test"
    org, _ = await _org(db)
    balance = (await ai_usage.build(db, org.id, TZ, NOW, month="2026-10"))["balance"]
    assert (balance["status"], balance["remaining_usd"]) == ("ok", 46.75)


async def test_balance_failure_hides_card(db, monkeypatch):
    def handler(request):
        return httpx.Response(500, json={"error": "down"})
    monkeypatch.setattr(ai_usage.httpx, "AsyncClient", _fake_client(handler))
    monkeypatch.setattr(ai_usage, "_provider", lambda: ("openrouter", "sk-test"))
    monkeypatch.setenv("SALES_HEAD_SHOW_PLATFORM_BALANCE", "1")
    assert await ai_usage.openrouter_balance() is None
    org, _ = await _org(db)
    balance = (await ai_usage.build(db, org.id, TZ, NOW, month="2026-10"))["balance"]
    assert (balance["status"], balance["note"]) == ("empty", "Balance not available.")


async def test_no_balance_call_for_another_provider(db, monkeypatch):
    def handler(request):
        raise AssertionError("no call expected")
    monkeypatch.setattr(ai_usage.httpx, "AsyncClient", _fake_client(handler))
    monkeypatch.setattr(ai_usage, "_provider", lambda: ("gemini", "key"))
    assert await ai_usage.openrouter_balance() is None


async def test_empty_month(db):
    org, _ = await _org(db)
    result = await ai_usage.build(db, org.id, TZ, NOW, month="2026-10")
    for name in ("budget", "health", "daily", "features", "models", "people", "kept", "free"):
        assert result[name]["status"] == "empty", name
    assert result["accuracy_note"]


async def test_a_prospect_table_without_org_column_is_not_read(db):
    """Fail closed: a spend table that cannot say whose spend it is would show
    every organisation the whole platform's Prospect Finder spend."""
    org, _ = await _org(db)
    await db.execute(text(
        "CREATE TABLE prospect_spend (id INTEGER PRIMARY KEY, run_id TEXT, "
        "institution_id TEXT, step TEXT, model TEXT, tokens INTEGER, cost_usd REAL, "
        "at TIMESTAMP)"))
    await db.execute(text(
        "INSERT INTO prospect_spend (run_id, institution_id, step, model, tokens, cost_usd, at) "
        "VALUES ('r1', 'i1', 'plan', 'm', 10, 3.0, :a)"), {"a": NOW - DAY})
    prospect = (await ai_usage.build(db, org.id, TZ, NOW, month="2026-10"))["prospect"]
    assert prospect["status"] == "empty"
    assert prospect["note"] == "Prospect Finder is not connected yet."
    assert (await ai_usage.month_totals(db, org.id, TZ, NOW))["prospect_usd"] == 0.0


async def test_the_platform_balance_is_not_shown_unless_switched_on(db, monkeypatch):
    """The OpenRouter key is the platform's, shared by every organisation: its
    balance is the platform's money, not the sales head's, so the card stays
    off unless the platform turns it on."""
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"data": {"usage": 1.0, "limit_remaining": 2.0}})
    monkeypatch.setattr(ai_usage.httpx, "AsyncClient", _fake_client(handler))
    monkeypatch.setattr(ai_usage, "_provider", lambda: ("openrouter", "sk-test"))
    monkeypatch.delenv("SALES_HEAD_SHOW_PLATFORM_BALANCE", raising=False)
    assert await ai_usage.openrouter_balance() is None
    assert calls == []
    monkeypatch.setenv("SALES_HEAD_SHOW_PLATFORM_BALANCE", "1")
    assert await ai_usage.openrouter_balance() == {"remaining_usd": 2.0, "usage_usd": 1.0}
