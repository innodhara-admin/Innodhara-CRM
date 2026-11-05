"""Task 5: every in-app notification also goes to the person's WhatsApp."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.crypto import encrypt_secret
from app.models.job import JobRecord
from app.models.messaging import WhatsappLog
from app.models.organisation import OrgSettings
from app.models.user import Notification
from app.services import notification_service, whatsapp_providers, whatsapp_staff
from tests.insights.builders import make_lead, make_meeting, make_org, make_task, make_user

pytestmark = pytest.mark.asyncio

IST = clock.zone("Asia/Kolkata")


async def _org(db, **integration):
    org = await make_org(db, name="WA Staff Org")
    row = (await db.execute(select(OrgSettings).where(OrgSettings.org_id == org.id))).scalar_one()
    row.whatsapp_integration = {"provider": "wati", "wati_token_enc": encrypt_secret("tok-test"),
                                "staff_updates": True, **integration}
    asha = await make_user(db, org, name="Asha Rao", role="sales_agent")
    asha.phone = "09310524629"
    await db.flush()
    return org, asha


async def _logs(db, user_id):
    db.expire_all()
    return (await db.execute(select(WhatsappLog).where(WhatsappLog.user_id == user_id))).scalars().all()


@pytest.fixture(autouse=True)
def _always_working_hours(monkeypatch):
    """Delays are tested on their own; everything else sends straight away."""
    monkeypatch.setattr(whatsapp_staff, "send_delay", lambda *a, **k: 0)


async def test_notify_queues_one_job_and_log(db):
    org, asha = await _org(db)
    await notification_service.notify(db, org_id=org.id, user_id=asha.id,
                                      title="Asha, a task for you", kind="task_assigned")
    await db.commit()
    await whatsapp_staff.drain()
    logs = await _logs(db, asha.id)
    assert [(l.status, l.to_number, l.kind) for l in logs] == [
        ("queued", "919310524629", "task_assigned")]
    jobs = (await db.execute(select(JobRecord).where(JobRecord.type == "whatsapp_staff"))).scalars().all()
    assert logs[0].id in [j.payload.get("log_id") for j in jobs]


@pytest.mark.parametrize("case", ["off", "kind_off", "no_number", "inactive"])
async def test_nothing_is_queued_when_it_should_not_be(db, case):
    org, asha = await _org(db, **({"staff_updates": False} if case == "off" else
                                  {"kinds_off": ["task_assigned"]} if case == "kind_off" else {}))
    if case == "no_number":
        asha.phone = None
    if case == "inactive":
        asha.is_active = False
    await db.flush()
    await notification_service.notify(db, org_id=org.id, user_id=asha.id,
                                      title="t", kind="task_assigned")
    await db.commit()
    await whatsapp_staff.drain()
    assert await _logs(db, asha.id) == []


async def test_a_rolled_back_notification_sends_nothing(db):
    org, asha = await _org(db)
    org_id, asha_id = org.id, asha.id
    await db.commit()
    await notification_service.notify(db, org_id=org_id, user_id=asha_id,
                                      title="never happened", kind="task_assigned")
    await db.rollback()
    await whatsapp_staff.drain()
    assert await _logs(db, asha_id) == []


async def test_a_queueing_failure_never_reaches_the_caller(db, monkeypatch):
    org, asha = await _org(db)

    async def boom(*_a, **_k):
        raise RuntimeError("queue down")

    monkeypatch.setattr(whatsapp_staff, "_queue_later", boom)
    n = await notification_service.notify(db, org_id=org.id, user_id=asha.id,
                                          title="still saved", kind="task_assigned")
    await db.commit()
    await whatsapp_staff.drain()
    assert (await db.execute(select(Notification).where(Notification.id == n.id))).scalar_one()


async def test_send_delay_waits_for_the_working_day(db):
    org = await make_org(db, name="WA Delay Org")
    settings = (await db.execute(select(OrgSettings).where(OrgSettings.org_id == org.id))).scalar_one()
    user = await make_user(db, org, name="Late", role="sales_agent")
    from app.services.whatsapp_staff import send_delay as real_delay  # noqa: F401

    delay = whatsapp_staff._real_send_delay
    # Wednesday 4 Nov 2026, 22:00 in Kolkata = 16:30 UTC; workday opens 09:00.
    assert delay(datetime(2026, 11, 4, 16, 30), IST, settings, user) == 11 * 3600
    # 10:00 in Kolkata, inside the window: now.
    assert delay(datetime(2026, 11, 4, 4, 30), IST, settings, user) == 0


async def test_on_leave_is_skipped(db):
    org, asha = await _org(db)
    today = clock.today(IST)
    asha.on_leave_from, asha.on_leave_to = today - timedelta(days=1), today + timedelta(days=1)
    await db.flush()
    await notification_service.notify(db, org_id=org.id, user_id=asha.id,
                                      title="t", kind="task_assigned")
    await db.commit()
    await whatsapp_staff.drain()
    assert [l.status for l in await _logs(db, asha.id)] == ["skipped"]


async def test_meeting_summary_message(db, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "public_base_url", "https://crm.example")
    org, asha = await _org(db)
    lead = await make_lead(db, org, name="Nexora", state="active", created_at=datetime(2026, 11, 1))
    meeting = await make_meeting(db, org, lead, by=asha, at=datetime(2026, 11, 2, 6, 0),
                                 summary="They want the lab for classes 8 to 10.")
    for i in range(7):
        task = await make_task(db, org, assignee=asha, due=datetime(2026, 11, 10 + i),
                               meeting=meeting)
        task.title = f"Item {i}"
    await db.flush()
    n = Notification(org_id=org.id, user_id=asha.id, title="Meeting processed: 7 action item(s) saved",
                     kind="meeting_processed", entity_type="meeting", entity_id=meeting.id)
    template, values, link = await whatsapp_staff.build_message(db, asha, n)
    assert template == "staff_meeting_summary"
    assert values["name"] == "Asha" and values["client"] == "Nexora"
    assert values["summary"] == "They want the lab for classes 8 to 10."
    assert values["action_items"].count("Item ") == 5
    assert "(due 10 Nov)" in values["action_items"]
    assert link == {"k": "transcript", "o": org.id, "m": meeting.id}

    monkeypatch.setattr(get_settings(), "public_base_url", "")
    template, values, link = await whatsapp_staff.build_message(db, asha, n)
    assert template == "staff_update" and link is None
    assert "They want the lab" in values["detail"]


async def test_handle_job_sends_and_records(db, monkeypatch):
    org, asha = await _org(db)
    n = await notification_service.notify(db, org_id=org.id, user_id=asha.id,
                                          title="Approval waiting", body="Invite to Abc",
                                          kind="approval_waiting")
    await db.flush()
    n_id, asha_id = n.id, asha.id
    await db.commit()
    await whatsapp_staff.drain()
    log = (await _logs(db, asha_id))[0]
    sent = {}

    async def fake_send(cfg, **kw):
        sent.update(kw)
        return whatsapp_providers.SendResult(True, kw["local_id"])

    monkeypatch.setattr(whatsapp_providers, "send_template", fake_send)
    result = await whatsapp_staff.handle_job({"log_id": log.id}, "job-1")
    assert result["status"] == "sent"
    assert sent["template"] == "staff_update" and sent["to"] == "919310524629"
    assert sent["values"] == {"name": "Asha", "title": "Approval waiting",
                              "detail": "Invite to Abc"}
    log = (await _logs(db, asha_id))[0]
    assert (log.status, log.provider_id, log.template) == ("sent", log.id, "staff_update")
    assert n_id == log.notification_id


async def test_handle_job_skips_a_vanished_notification(db, monkeypatch):
    org, asha = await _org(db)
    log = WhatsappLog(org_id=org.id, user_id=asha.id, to_number="919310524629",
                      kind="task_assigned", notification_id="gone", status="queued")
    db.add(log)
    await db.commit()
    result = await whatsapp_staff.handle_job({"log_id": log.id}, "job-2")
    assert result["status"] == "skipped"
