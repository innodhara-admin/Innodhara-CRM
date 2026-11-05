"""Task 9: Wati tells us what happened to a message."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from app.core.constants import MessageStatus
from app.models.messaging import MessageDeliveryLog, OutboundMessage, WhatsappLog
from app.models.organisation import OrgSettings
from tests.insights.builders import make_lead, make_org, make_user

pytestmark = pytest.mark.asyncio

ROUTE = "/api/v1/webhooks/wati/"


async def _org(db, secret):
    org = await make_org(db, name="WA Hook Org")
    row = (await db.execute(select(OrgSettings).where(OrgSettings.org_id == org.id))).scalar_one()
    row.whatsapp_integration = {"provider": "wati", "webhook_secret": secret}
    user = await make_user(db, org, name="Asha", role="sales_agent")
    lead = await make_lead(db, org, name="Hook Client", state="active",
                           created_at=datetime(2026, 11, 1))
    log = WhatsappLog(org_id=org.id, user_id=user.id, to_number="919310524629",
                      kind="task_assigned", status="sent")
    message = OutboundMessage(org_id=org.id, kind="follow_up", channel="whatsapp",
                              status=MessageStatus.SENT.value, lead_id=lead.id,
                              sender_user_id=user.id, to_address="919876543210", body="hi",
                              idempotency_key=f"hook-{secret}")
    db.add_all([log, message])
    await db.commit()
    return org.id, log.id, message.id


async def test_a_wrong_secret_is_404(client):
    resp = await client.post(ROUTE + "not-a-secret", json={"eventType": "x"})
    assert resp.status_code == 404


async def test_a_failed_staff_message_is_recorded(client, db):
    _, log_id, _ = await _org(db, "sec-fail-1")
    resp = await client.post(ROUTE + "sec-fail-1", json={
        "eventType": "templateMessageFailed", "localMessageId": log_id,
        "failedCode": "131026", "failedDetail": "Message undeliverable"})
    assert resp.status_code == 200 and resp.json()["updated"] == 1
    db.expire_all()
    log = await db.get(WhatsappLog, log_id)
    assert log.status == "failed" and "undeliverable" in log.error


async def test_a_delivered_client_message_is_recorded(client, db):
    _, _, message_id = await _org(db, "sec-deliv-1")
    resp = await client.post(ROUTE + "sec-deliv-1", json={
        "eventType": "sentMessageDELIVERED", "localMessageId": message_id})
    assert resp.json()["updated"] == 1
    db.expire_all()
    message = await db.get(OutboundMessage, message_id)
    assert message.status == MessageStatus.DELIVERED.value
    events = (await db.execute(select(MessageDeliveryLog.event).where(
        MessageDeliveryLog.message_id == message_id))).scalars().all()
    assert "provider_delivered" in events


async def test_another_orgs_message_is_ignored(client, db):
    _, other_log, _ = await _org(db, "sec-other-1")
    await _org(db, "sec-mine-1")
    resp = await client.post(ROUTE + "sec-mine-1", json={
        "eventType": "templateMessageFailed", "localMessageId": other_log})
    assert resp.status_code == 200 and resp.json()["updated"] == 0
    db.expire_all()
    assert (await db.get(WhatsappLog, other_log)).status == "sent"
