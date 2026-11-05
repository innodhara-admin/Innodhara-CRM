"""The final review's Important findings (4 Nov 2026), each pinned by a test."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core import clock, signed_links
from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.exceptions import ValidationFailedError
from app.models.messaging import WhatsappLog
from app.models.organisation import OrgSettings
from app.services import notification_service, whatsapp_providers, whatsapp_staff
from tests.conftest import auth, create_org
from tests.insights.builders import make_lead, make_meeting, make_org, make_user

pytestmark = pytest.mark.asyncio

IST = clock.zone("Asia/Kolkata")


@pytest.fixture(autouse=True)
def _now(monkeypatch):
    monkeypatch.setattr(whatsapp_staff, "send_delay", lambda *a, **k: 0)


async def _org(db, n_people=1, **integration):
    org = await make_org(db, name="WA Review Org")
    row = (await db.execute(select(OrgSettings).where(OrgSettings.org_id == org.id))).scalar_one()
    row.whatsapp_integration = {"provider": "wati", "wati_token_enc": encrypt_secret("tok-test"),
                                "staff_updates": True, **integration}
    people = []
    for i in range(n_people):
        u = await make_user(db, org, name=f"Person {i}", role="sales_agent")
        u.phone = f"98765432{i:02d}"
        people.append(u)
    await db.flush()
    return org, people


async def _logs(db, org_id):
    db.expire_all()
    return (await db.execute(select(WhatsappLog).where(WhatsappLog.org_id == org_id))).scalars().all()


async def _ok(cfg, **kw):
    return whatsapp_providers.SendResult(True, kw["local_id"])


# Important 1: a savepoint released after notify() must not queue early.
async def test_a_savepoint_does_not_lose_the_whatsapp(db):
    org, [p] = await _org(db)
    org_id = org.id
    await notification_service.notify(db, org_id=org_id, user_id=p.id, title="t",
                                      kind="task_assigned")
    async with db.begin_nested():
        await db.flush()
    await whatsapp_staff.drain()          # anything spawned at the release runs NOW
    await db.commit()
    await whatsapp_staff.drain()
    assert [l.status for l in await _logs(db, org_id)] == ["queued"]


# Important 2: switches, kinds and leave are checked again when it is sent.
@pytest.mark.parametrize("change", ["kind_off", "staff_off", "leave"])
async def test_the_job_rechecks_at_send_time(db, monkeypatch, change):
    org, [p] = await _org(db)
    org_id, pid = org.id, p.id
    await notification_service.notify(db, org_id=org_id, user_id=pid, title="t",
                                      kind="escalation")
    await db.commit()
    await whatsapp_staff.drain()
    log_id = (await _logs(db, org_id))[0].id
    row = (await db.execute(select(OrgSettings).where(OrgSettings.org_id == org_id))).scalar_one()
    raw = dict(row.whatsapp_integration)
    if change == "kind_off":
        raw["kinds_off"] = ["escalation"]
    elif change == "staff_off":
        raw["staff_updates"] = False
    row.whatsapp_integration = raw
    if change == "leave":
        from app.models.user import User

        user = await db.get(User, pid)
        today = clock.today(IST)
        user.on_leave_from, user.on_leave_to = today, today + timedelta(days=2)
    await db.commit()
    monkeypatch.setattr(whatsapp_providers, "send_template", _ok)
    assert (await whatsapp_staff.handle_job({"log_id": log_id}, "j"))["status"] == "skipped"


# Important 3: one commit with many notifications = one task, one session.
async def test_one_task_per_commit(db, monkeypatch):
    org, people = await _org(db, n_people=4)
    org_id = org.id
    spawned = []
    real = whatsapp_staff._spawn

    def counting(items):
        spawned.append(len(items))
        real(items)

    monkeypatch.setattr(whatsapp_staff, "_spawn", counting)
    for p in people:
        await notification_service.notify(db, org_id=org_id, user_id=p.id, title="t",
                                          kind="reminder")
    await db.commit()
    await whatsapp_staff.drain()
    assert spawned == [4]
    assert len(await _logs(db, org_id)) == 4


# Important 4: no "today" brief once the working day is over.
async def test_no_brief_after_the_working_day(db):
    org, _ = await _org(db)
    org_id = org.id
    await db.commit()
    await whatsapp_staff.send_morning_briefs(datetime(2026, 11, 4, 14, 0))  # 19:30 Kolkata
    assert [l for l in await _logs(db, org_id) if l.kind == "daily_brief"] == []


# Important 5: the transcript PDF is rendered off the event loop.
async def test_transcript_renders_in_a_worker_thread(client, db, monkeypatch):
    from app.services import document_service

    seen = {}
    real = document_service.render_pdf

    def spy(md, title):
        seen["thread"] = threading.current_thread() is threading.main_thread()
        return real(md, title)

    monkeypatch.setattr(document_service, "render_pdf", spy)
    org = await make_org(db, name="WA Thread Org")
    asha = await make_user(db, org, name="Asha", role="sales_agent")
    lead = await make_lead(db, org, name="Thread Client", state="active",
                           created_at=datetime(2026, 11, 1))
    meeting = await make_meeting(db, org, lead, by=asha, at=datetime(2026, 11, 2), summary="s")
    token = signed_links.make({"k": "transcript", "o": org.id, "m": meeting.id})
    await db.commit()
    resp = await client.get("/api/v1/public/wa/" + token)
    assert resp.status_code == 200
    assert seen["thread"] is False


async def _admin(client, super_token):
    tag = uuid.uuid4().hex[:8]
    org = await create_org(client, super_token, name=f"WA Rev {tag}", slug=f"wa-rev-{tag}",
                           domain=f"wa-rev-{tag}.example.com")
    return org, auth(org["admin_token"])


# Important 6: the Wati host is a Wati host; a new host needs the token again.
async def test_only_wati_hosts(client, super_token):
    _, h = await _admin(client, super_token)
    base = "/api/v1/admin/integrations/whatsapp"
    evil = await client.put(base, headers=h, json={
        "provider": "wati", "wati_token": "tok-test", "wati_host": "https://intranet.example.com"})
    assert evil.status_code == 422
    ok = await client.put(base, headers=h, json={
        "provider": "wati", "wati_token": "tok-test", "wati_host": "https://eu-api.wati.io"})
    assert ok.status_code == 200, ok.text
    moved = await client.put(base, headers=h, json={
        "provider": "wati", "wati_host": "https://live-mt-server.wati.io"})
    assert moved.status_code == 422, "a new host must not receive the old token unasked"
    blank = await client.put(base, headers=h, json={
        "provider": "wati", "wati_host": "", "country_code": ""})
    assert blank.status_code == 200, "a cleared box means 'keep', not an error"


# Important 7: what is approved is what the client gets.
async def test_the_preview_is_the_message_the_client_gets(db, monkeypatch):
    from app.ai.agents.base import AgentRuntime
    from app.ai.agents.email_agent import EmailAgent
    from app.core.context import OrgContext
    from app.models.lead import Contact

    org = await make_org(db, name="WA Preview Org")
    ek = await make_user(db, org, name="Ekaghni Mukherjee", role="sales_lead")
    lead = await make_lead(db, org, name="Preview Client", state="active", owner=ek,
                           created_at=datetime(2026, 11, 1))
    db.add(Contact(org_id=org.id, lead_id=lead.id, name="Ravi Kumar", phone="9876543210",
                   is_primary=True))
    await db.flush()
    rt = AgentRuntime(db=db, ctx=OrgContext(org_id=org.id, user_id=ek.id, role=ek.role,
                                            email=ek.email, name=ek.name), extra_context={})
    result = await EmailAgent()._send_whatsapp(rt, client="Preview Client",
                                               message="We will call on Monday.")
    assert result["body_preview"].startswith("Dear Ravi Kumar, ")
    assert "We will call on Monday." in result["body_preview"]
    assert result["body_preview"].endswith("You can reply here with any questions.")
    with pytest.raises(ValidationFailedError, match="too long"):
        await EmailAgent()._send_whatsapp(rt, client="Preview Client", message="x " * 600)
    with pytest.raises(ValidationFailedError, match="separate"):
        await EmailAgent()._send_whatsapp(rt, client="Preview Client", message="hi",
                                          attach_proposal=True)


# Important 8: an intro already written as a letter is not greeted twice.
async def test_an_existing_greeting_and_sign_off_are_not_doubled():
    from app.services.whatsapp_service import message_value

    body = "Dear Ravi,\n\nThank you for meeting us today.\nWe will share the plan.\n\nWarm regards,\nEkaghni"
    assert message_value(body) == "Thank you for meeting us today.\nWe will share the plan."
    assert message_value("Hi Ravi, quick note: see you Monday.") == "Hi Ravi, quick note: see you Monday."
    assert message_value("Thanks for your time today. Regards, Ek") == "Thanks for your time today."


# Important 9: a token pasted with "Bearer " in front still works.
async def test_a_bearer_prefix_is_stripped(client, super_token):
    org, h = await _admin(client, super_token)
    resp = await client.put("/api/v1/admin/integrations/whatsapp", headers=h,
                            json={"provider": "wati", "wati_token": "Bearer tok-test"})
    assert resp.status_code == 200
    from app.database import SessionLocal

    async with SessionLocal() as s:
        row = (await s.execute(select(OrgSettings).where(
            OrgSettings.org_id == org["id"]))).scalar_one()
        assert decrypt_secret(row.whatsapp_integration["wati_token_enc"]) == "tok-test"
