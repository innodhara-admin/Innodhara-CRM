"""`auto_approve` is a rule about *who signs off*, not a licence to send
unfinished text with nobody's name on it.

Two fences were built on the human decision path and neither reached this one:

* **F30/F47** — `_refuse_unfinished_drafts` refuses to release a draft still
  carrying `[Name]` or `[Insert Date]`. It is called from `decide()` only.
* **D13 / Roles §2** — *"no proposal, message, or invoice goes out without a
  recorded approval (`outbound_messages.approved_by` is the proof)"*. The
  auto-approve branch built its `Approval` with no `requested_from_user_id`, so
  `_release_message` copied `None` into `approved_by` and the proof was absent.

Reproduced before the fix: a draft reading `Dear [Name], … on [Insert Date]`
went to `queued` with `approved_by = None`.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.constants import ApprovalStatus, MessageStatus
from app.core.context import OrgContext
from app.database import SessionLocal
from app.models.comms import Approval
from app.models.messaging import OutboundMessage
from app.services import message_service
from tests.conftest import auth, create_org

pytestmark = pytest.mark.asyncio

WITH_A_BLANK = (
    "Dear [Name],\n\nThank you for your time on [Insert Date]. "
    "We will follow up shortly.\n\nBest regards"
)
FINISHED = (
    "Dear Ravi,\n\nThank you for your time on Tuesday. "
    "We will follow up shortly.\n\nBest regards"
)


async def _org_with_auto_rule(client, super_token, slug):
    org = await create_org(client, super_token, name=f"Auto {slug}",
                           slug=slug, domain=f"{slug}-example.com")
    resp = await client.post(
        "/api/v1/approval-rules", headers=auth(org["admin_token"]),
        json={"entity_type": "outbound_message", "condition": {},
              "approver_role": "sales_lead", "auto_approve": True, "rank": 10})
    assert resp.status_code == 200, resp.text
    me = (await client.get("/api/v1/auth/me",
                           headers=auth(org["admin_token"]))).json()
    return org, me


async def _draft(org, me, body):
    async with SessionLocal() as db:
        ctx = OrgContext(org_id=org["id"], user_id=me["user_id"], role=me["role"],
                         email=me["email"], name=me["name"])
        message = await message_service.create_message(
            db, ctx, channel="email", kind="follow_up",
            to_address="client@example.com", subject="Following up",
            body=body, request_approval=True)
        await db.commit()
        row = (await db.execute(select(OutboundMessage).where(
            OutboundMessage.id == message.id))).scalar_one()
        approvals = (await db.execute(select(Approval).where(
            Approval.entity_id == message.id))).scalars().all()
        return row, approvals


async def test_an_auto_approved_message_records_who_the_rule_delegated_to(
    client, super_token
):
    org, me = await _org_with_auto_rule(client, super_token, "auto-proof")
    row, _ = await _draft(org, me, FINISHED)
    assert row.status == MessageStatus.QUEUED.value
    assert row.approved_by is not None, (
        "auto-approved and sent with nobody recorded as the approver — "
        "`approved_by` is the proof the Roles doc points at"
    )


async def test_auto_approve_does_not_release_a_draft_with_blanks(
    client, super_token
):
    """The fence, on the path that had none."""
    org, me = await _org_with_auto_rule(client, super_token, "auto-blank")
    row, approvals = await _draft(org, me, WITH_A_BLANK)
    assert row.status != MessageStatus.QUEUED.value, (
        "a draft still reading '[Name]' was queued for sending"
    )
    assert row.approved_by is None


async def test_a_blocked_auto_approval_waits_for_a_person_rather_than_vanishing(
    client, super_token
):
    """Refusing must not strand the message. `auto_approve` said nobody needs to
    look; the blanks say somebody does — so it becomes an ordinary pending
    approval, addressed to the role the rule named."""
    org, me = await _org_with_auto_rule(client, super_token, "auto-waits")
    _, approvals = await _draft(org, me, WITH_A_BLANK)
    assert len(approvals) == 1, "the message must still have an approval on it"
    approval = approvals[0]
    assert approval.status == ApprovalStatus.PENDING.value
    assert approval.requested_from_user_id is not None
    assert "[Name]" in (approval.reason or "") or "blank" in (approval.reason or "").lower(), (
        "the approver is not told why the rule's auto-approval did not apply"
    )


async def test_the_finished_draft_still_auto_approves(client, super_token):
    """The fence must not quietly disable the feature."""
    org, me = await _org_with_auto_rule(client, super_token, "auto-clean")
    row, approvals = await _draft(org, me, FINISHED)
    assert row.status == MessageStatus.QUEUED.value
    assert approvals and approvals[0].status == ApprovalStatus.APPROVED.value
