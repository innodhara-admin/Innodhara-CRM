"""Shared builders for the email template tests."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.ai import docx_tagfill
from app.core.context import OrgContext
from app.database import SessionLocal
from app.models.user import User
from tests.conftest import add_reached_contact, auth, fresh_lead

API = "/api/v1"
FIXTURES = Path(__file__).parent / "fixtures"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_LINE = re.compile(r"^([0-9a-f]{12})  (\S+)  (.*?)(?:  \|  |$)", re.M)


class Layer:
    """The fill model: answers by the tag's raw text (first pass) or by the
    question's tag id (answer rounds), from scripts the test hands it."""

    def __init__(self, by_raw=None, answers=None, revisions=None):
        self.by_raw = by_raw or {}
        self.answers = list(answers or [])
        self.revisions = list(revisions or [])
        self.calls = []

    async def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        purpose = kwargs["purpose"]
        prompt = kwargs["messages"][0]["content"]
        if purpose.endswith("_answer"):
            return self.answers.pop(0) if self.answers else {"resolutions": []}
        if purpose.endswith("_revise"):
            return self.revisions.pop(0) if self.revisions else {"resolutions": []}
        out = []
        for tag_id, _kind, raw in _LINE.findall(prompt):
            if raw in self.by_raw:
                value, citation = self.by_raw[raw]
                out.append({"tag_id": tag_id, "value": value, "confidence": 0.95,
                            "citation": citation, "reason": "test"})
            else:
                out.append({"tag_id": tag_id, "question": f"What goes in {raw}?"})
        return {"resolutions": out}


@pytest.fixture
def layer(monkeypatch):
    def install(**kw):
        made = Layer(**kw)
        monkeypatch.setattr(docx_tagfill, "get_model_layer", lambda: made)
        return made
    return install


#: What the record can back in every template.
FACTS = {
    "<School Name>": ("Green Valley", "client.name"),
    "<Surname>": ("Menon", "recipient.name"),
    "<Your Name>": ("Asha Admin", "sender.name"),
    "<Designation>": ("Sales Lead", "sender.designation"),
    "<Mobile Number>": ("+91 90000 11111", "sender.phone"),
}


async def admin(org) -> User:
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(
            User.email == org["admin_email"]))).scalar_one()
        user.designation, user.phone = "Sales Lead", "+91 90000 11111"
        await db.commit()
        return user


async def ctx_for(org) -> OrgContext:
    user = await admin(org)
    return OrgContext(org_id=user.org_id, user_id=user.id, role=user.role,
                      email=user.email, name=user.name)


async def make_program(client, token) -> str:
    code = f"P{uuid.uuid4().hex[:6].upper()}"
    resp = await client.post(f"{API}/admin/programs", headers=auth(token),
                             json={"name": f"Prog {code}", "code": code,
                                   "description": "d"})
    return resp.json()["id"]


async def make_template(client, token, filename, *, program_id=None,
                    built="none", category="follow_up") -> str:
    form = {"name": f"T {uuid.uuid4().hex[:6]}", "built_document": built,
            "template_type": "product" if program_id else "common"}
    if program_id:
        form["program_id"] = program_id
    else:
        form["category"] = category
    resp = await client.post(f"{API}/admin/email-templates", headers=auth(token),
                             data=form, files={"file": (
                                 filename, (FIXTURES / filename).read_bytes(), DOCX)})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def lead_with_contact(client, token) -> tuple[str, str]:
    lead = await fresh_lead(client, token, "Quillmere Academy")
    contact = await add_reached_contact(client, token, lead["id"],
                                        name="Sunil Menon", title="Head",
                                        email="sunil@greenvalley.example")
    return lead["id"], contact["id"]




async def make_proposal(ctx, lead_id, program_id, *, status="draft",
                        title="IBC Proposal - Green Valley") -> str:
    """A built proposal with its PDF in storage, as the fill would leave it."""
    from app.models.proposal import Proposal  # noqa: PLC0415
    from app.services import storage  # noqa: PLC0415

    async with SessionLocal() as db:
        proposal = Proposal(
            org_id=ctx.org_id, lead_id=lead_id, program_id=program_id,
            title=title, template_id="t", template_version=1, content_md="x",
            created_by=ctx.user_id, status=status, template_kind="docx_simple")
        db.add(proposal)
        await db.flush()
        proposal.docx_path = storage.save_bytes(ctx.org_id, "proposals", "p.docx", b"d")
        proposal.pdf_path = storage.save_bytes(ctx.org_id, "proposals", "p.pdf",
                                               b"%PDF-1.4 proposal")
        await db.commit()
        return proposal.id
