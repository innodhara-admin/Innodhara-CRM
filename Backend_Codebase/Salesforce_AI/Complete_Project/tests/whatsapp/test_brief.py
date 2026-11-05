"""Task 6: one morning WhatsApp per person, at the start of their working day."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from app.core.crypto import encrypt_secret
from app.models.messaging import WhatsappLog
from app.models.organisation import OrgSettings
from app.services import whatsapp_providers, whatsapp_staff
from tests.insights.builders import make_org, make_user

pytestmark = pytest.mark.asyncio

BEFORE_NINE = datetime(2026, 11, 4, 3, 0)     # Wed 08:30 in Kolkata
AFTER_NINE = datetime(2026, 11, 4, 3, 35)     # Wed 09:05
SUNDAY = datetime(2026, 11, 8, 3, 35)         # Sun 09:05


async def _org(db, **integration):
    org = await make_org(db, name="WA Brief Org")
    row = (await db.execute(select(OrgSettings).where(OrgSettings.org_id == org.id))).scalar_one()
    row.whatsapp_integration = {"provider": "wati", "wati_token_enc": encrypt_secret("tok-test"),
                                "staff_updates": True, **integration}
    asha = await make_user(db, org, name="Asha Rao", role="sales_agent")
    asha.phone = "9310524629"
    nophone = await make_user(db, org, name="No Phone", role="sales_agent")
    ids = (org.id, asha.id, nophone.id)
    await db.commit()
    return ids


async def _briefs(db, org_id):
    db.expire_all()
    return (await db.execute(select(WhatsappLog).where(
        WhatsappLog.org_id == org_id, WhatsappLog.kind == "daily_brief"))).scalars().all()


async def test_nothing_before_the_working_day_starts(db):
    org_id, _, _ = await _org(db)
    await whatsapp_staff.send_morning_briefs(BEFORE_NINE)
    assert await _briefs(db, org_id) == []


async def test_one_brief_per_person_per_day(db):
    org_id, asha_id, _ = await _org(db)
    await whatsapp_staff.send_morning_briefs(AFTER_NINE)
    logs = await _briefs(db, org_id)
    assert [(l.user_id, l.local_date, l.status) for l in logs] == [
        (asha_id, "2026-11-04", "queued")]
    await whatsapp_staff.send_morning_briefs(AFTER_NINE)
    assert len(await _briefs(db, org_id)) == 1


async def test_no_brief_on_a_day_off(db):
    org_id, _, _ = await _org(db)
    await whatsapp_staff.send_morning_briefs(SUNDAY)
    assert await _briefs(db, org_id) == []


async def test_no_brief_when_switched_off(db):
    org_id, _, _ = await _org(db, kinds_off=["daily_brief"])
    await whatsapp_staff.send_morning_briefs(AFTER_NINE)
    assert await _briefs(db, org_id) == []


async def test_the_brief_is_built_when_it_is_sent(db, monkeypatch):
    org_id, asha_id, _ = await _org(db)
    await whatsapp_staff.send_morning_briefs(AFTER_NINE)
    log_id = (await _briefs(db, org_id))[0].id
    sent = {}

    async def fake_send(cfg, **kw):
        sent.update(kw)
        return whatsapp_providers.SendResult(True, kw["local_id"])

    monkeypatch.setattr(whatsapp_providers, "send_template", fake_send)
    assert (await whatsapp_staff.handle_job({"log_id": log_id}, "j"))["status"] == "sent"
    assert sent["template"] == "staff_daily_brief"
    assert sent["values"]["name"] == "Asha"
    assert sent["values"]["date"] == "Wed 4 Nov"
    assert not sent["values"]["day"].startswith(("Good", "Working"))
