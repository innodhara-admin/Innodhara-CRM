# tests/docx/test_fill_service.py
"""The fill session: the working memory a fill is kept in (Task C3).

D6 is why this is a row and not the chat transcript. `conversation.py` replays
twelve turns inside a six-thousand-character budget and prunes at sixty rows,
so a twenty-five-tag fill with a dozen clarifications would lose its own
working memory half way through. Everything here is about that row surviving:
a reload, a second round of answers, a week of silence.

The model is stubbed throughout. What it says is C2's subject; what is *kept*
is this one's.
"""
import io
from datetime import timedelta

import pytest
from docx import Document
from sqlalchemy import select, update

from app.ai import docx_tagfill
from app.core.context import OrgContext
from app.core.exceptions import ValidationFailedError
from app.database import SessionLocal
from app.models.base import utcnow
from app.models.program import ProposalTemplateDoc
from app.models.proposal_fill import FillStatus, ProposalFillSession
from app.services import proposal_fill_service as fs
from tests.conftest import auth

API = "/api/v1"
pytestmark = pytest.mark.asyncio


def _tagged_docx() -> bytes:
    """Two semantic tags and seven that must always be asked.

    Seven is chosen so one round of `QUESTIONS_PER_ROUND` does not exhaust
    them: D5's whole point is that nineteen questions are not a conversation,
    and a fixture with six would never show the slicing.
    """
    doc = Document()
    doc.add_heading("Proposal For", level=1)
    doc.add_paragraph("Prepared for <School Name>, a body paragraph long "
                      "enough to serve as a style reference.")
    doc.add_paragraph("Kind attention: <Principal Name>")
    items = ("Laptops", "Interactive Panel", "Magazine Rack", "Projector",
             "3D Printer", "Drone Kit", "Safety Glasses")
    t = doc.add_table(rows=len(items) + 1, cols=2)
    t.cell(0, 0).text = "Description"
    t.cell(0, 1).text = "Estimation"
    for row, item in enumerate(items, start=1):
        t.cell(row, 0).text = item
        t.cell(row, 1).text = "<ask:1 Unit>"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _semantic_only_docx() -> bytes:
    """No `ask` anywhere, so every tag can be settled without a question."""
    doc = Document()
    doc.add_heading("Proposal For", level=1)
    doc.add_paragraph("Prepared for <School Name>, a body paragraph long "
                      "enough to serve as a style reference.")
    doc.add_paragraph("Kind attention: <Principal Name>")
    doc.add_paragraph("Sent from <Sender Name> at <Organisation>.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class FakeLayer:
    """Serves one scripted reply per call, and remembers every prompt."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    async def generate_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0) if self.replies else {"resolutions": []}

    @property
    def prompt(self) -> str:
        return self.calls[-1]["messages"][-1]["content"]


def _use(monkeypatch, *replies) -> FakeLayer:
    layer = FakeLayer(*replies)
    monkeypatch.setattr(docx_tagfill, "get_model_layer", lambda: layer)
    return layer


async def _ctx(client, token) -> OrgContext:
    me = (await client.get(f"{API}/auth/me", headers=auth(token))).json()
    return OrgContext(org_id=me["org_id"], user_id=me["user_id"],
                      role=me["role"], email=me["email"])


async def _template(client, token, code) -> tuple[str, str]:
    """A programme with a current simple-flow template. Returns (program, tmpl)."""
    program = (await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": f"Fill {code}", "code": code, "description": "d"},
    )).json()
    resp = await client.post(
        f"{API}/admin/programs/{program['id']}/proposal-templates/docx",
        headers=auth(token),
        data={"name": "Tagged", "make_current": "true", "flow": "simple"},
        files={"file": ("tagged.docx", _tagged_docx(),
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")},
    )
    assert resp.status_code == 200, resp.text
    return program["id"], resp.json()["id"]


async def _lead(client, token, name) -> str:
    return (await client.post(f"{API}/leads", headers=auth(token),
                              json={"name": name})).json()["id"]


async def _plan_tags(template_id: str) -> list[dict]:
    async with SessionLocal() as db:
        row = (await db.execute(select(ProposalTemplateDoc).where(
            ProposalTemplateDoc.template_id == template_id))).scalar_one()
    return (row.plan_json or {}).get("tags") or []


def _confident(tag: dict) -> dict:
    return {"tag_id": tag["tag_id"], "value": "Orchid International School",
            "confidence": 0.97, "citation": "client.name",
            "reason": "the client's own name"}


async def _ground(client, token, code, lead_name):
    """A programme, a simple template, a lead and a context, in one line."""
    program_id, template_id = await _template(client, token, code)
    return (await _ctx(client, token), await _lead(client, token, lead_name),
            program_id, template_id)


# --- opening a fill ----------------------------------------------------------


async def test_opening_a_fill_stores_the_dossier_and_every_occurrence(
        client, org_a, monkeypatch):
    token = org_a["admin_token"]
    ctx, lead_id, program_id, template_id = await _ground(
        client, token, "FILLA", "Orchid A")
    _use(monkeypatch, {"resolutions": []})

    async with SessionLocal() as db:
        session = await fs.open_session(db, ctx, lead_id=lead_id,
                                        program_id=program_id,
                                        chat_session_id="chat-a")

    assert len(session.tags_json) == 9
    assert session.dossier_json["client"]["name"] == "Orchid A"
    assert session.dossier_json["programme"]["code"] == "FILLA"
    assert session.template_id == template_id
    assert session.asked_json == []
    assert session.proposal_id is None


async def test_a_fill_with_questions_open_is_asking_not_ready(
        client, org_a, monkeypatch):
    token = org_a["admin_token"]
    ctx, lead_id, program_id, _ = await _ground(client, token, "FILLB", "Orchid B")
    _use(monkeypatch, {"resolutions": []})

    async with SessionLocal() as db:
        session = await fs.open_session(db, ctx, lead_id=lead_id,
                                        program_id=program_id,
                                        chat_session_id="chat-b")

    assert session.status == FillStatus.ASKING
    assert len(fs.open_questions(session, limit=None)) == 9


async def test_a_fill_the_model_filled_entirely_still_goes_to_review(
        client, org_a, monkeypatch):
    """D13. `ready` is reachable only through `reviewing`, even when not one
    question was ever asked -- the 0.80 threshold is self-reported, so a human
    sees every value including the ones filled silently.

    Needs a document of nothing but semantic tags: an `ask` always asks (D4),
    so a template carrying one can never reach this state.
    """
    token = org_a["admin_token"]
    program = (await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": "Semantic only", "code": "FILLC", "description": "d"},
    )).json()
    resp = await client.post(
        f"{API}/admin/programs/{program['id']}/proposal-templates/docx",
        headers=auth(token),
        data={"name": "Semantic", "make_current": "true", "flow": "simple"},
        files={"file": ("semantic.docx", _semantic_only_docx(),
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document")},
    )
    assert resp.status_code == 200, resp.text
    ctx = await _ctx(client, token)
    lead_id = await _lead(client, token, "Orchid C")
    tags = await _plan_tags(resp.json()["id"])
    assert {t["kind"] for t in tags} == {"semantic"}
    _use(monkeypatch, {"resolutions": [_confident(t) for t in tags]})

    async with SessionLocal() as db:
        session = await fs.open_session(db, ctx, lead_id=lead_id,
                                        program_id=program["id"],
                                        chat_session_id="chat-c")

    assert fs.open_questions(session, limit=None) == []
    assert session.status == FillStatus.REVIEWING
    assert session.status != FillStatus.READY
    assert all(t["value"] for t in session.tags_json)
    assert all(t["reviewed"] is False for t in session.tags_json)


async def test_the_model_is_shown_every_tag_exactly_as_it_appears(
        client, org_a, monkeypatch):
    """The document text is built from the same walk the ordinals index into,
    so a tag in a table cell or a text box cannot be missing from the text the
    model is asked to reason about."""
    token = org_a["admin_token"]
    ctx, lead_id, program_id, template_id = await _ground(
        client, token, "FILLD", "Orchid D")
    layer = _use(monkeypatch, {"resolutions": []})

    async with SessionLocal() as db:
        await fs.open_session(db, ctx, lead_id=lead_id, program_id=program_id,
                              chat_session_id="chat-d")

    prompt = layer.prompt
    for tag in await _plan_tags(template_id):
        assert tag["raw"] in prompt
        assert tag["tag_id"] in prompt
    assert "Orchid D" in prompt          # the dossier went too


async def test_the_document_text_reaches_all_seven_places_a_tag_can_live(
        every_awkward_place_docx):
    """Section 2.3a's fixture, and the reason the text is built from the walk.

    Tested on the function rather than through the prompt on purpose: the
    occurrence list in the prompt quotes every `raw` too, so a prompt-level
    assertion passes even when the document text is missing the tag entirely
    -- which is exactly how a model comes to reason about a tag it cannot see.
    """
    text = fs._document_text(every_awkward_place_docx)

    for raw in ("<School Name>", "<Ph no. yuvipep>", "<ask:6 Units>",
                "<ask:(3 Nos)>", "<Name>", "<website yuv>", "<email yuvip>"):
        assert raw in text, f"{raw} is missing from the text the model reads"


async def test_a_first_pass_that_fails_leaves_no_half_built_fill(
        client, org_a, monkeypatch):
    """The row is written only once it is complete, so the write transaction
    is never held open across the model call -- SQLite blocks every other
    writer for the life of one, and a fill pass is seconds of model time.

    The other half of that choice is this: a failed first pass leaves nothing
    for a later turn to resume out of, rather than a `gathering` row with no
    resolutions in it that would read as having no questions to ask.
    """
    token = org_a["admin_token"]
    ctx, lead_id, program_id, _ = await _ground(client, token, "FILLV", "Orchid V")

    class Exploding:
        async def generate_json(self, **kwargs):
            raise RuntimeError("the model refused")

    monkeypatch.setattr(docx_tagfill, "get_model_layer", lambda: Exploding())
    async with SessionLocal() as db:
        with pytest.raises(RuntimeError):
            await fs.open_session(db, ctx, lead_id=lead_id,
                                  program_id=program_id,
                                  chat_session_id="chat-v")

    async with SessionLocal() as db:
        rows = (await db.execute(select(ProposalFillSession).where(
            ProposalFillSession.lead_id == lead_id))).scalars().all()
    assert rows == []


async def test_a_template_that_is_not_simple_flow_is_refused(
        client, org_a, monkeypatch):
    token = org_a["admin_token"]
    program = (await client.post(
        f"{API}/admin/programs", headers=auth(token),
        json={"name": "Markdown only", "code": "FILLE", "description": "d"},
    )).json()
    await client.post(
        f"{API}/admin/programs/{program['id']}/proposal-templates",
        headers=auth(token),
        json={"name": "Plain", "body_md": "A markdown body long enough to pass.",
              "make_current": True},
    )
    ctx = await _ctx(client, token)
    lead_id = await _lead(client, token, "Orchid E")
    _use(monkeypatch, {"resolutions": []})

    async with SessionLocal() as db:
        with pytest.raises(ValidationFailedError):
            await fs.open_session(db, ctx, lead_id=lead_id,
                                  program_id=program["id"],
                                  chat_session_id="chat-e")


# --- resuming ----------------------------------------------------------------


async def test_a_session_survives_a_reload(client, org_a, monkeypatch):
    """The row is the memory. Everything read back comes from a session that
    knows nothing about the one that wrote it."""
    token = org_a["admin_token"]
    ctx, lead_id, program_id, _ = await _ground(client, token, "FILLF", "Orchid F")
    _use(monkeypatch, {"resolutions": []})

    async with SessionLocal() as db:
        opened = await fs.open_session(db, ctx, lead_id=lead_id,
                                       program_id=program_id,
                                       chat_session_id="chat-f")
        session_id = opened.id

    async with SessionLocal() as db:
        found = await fs.find_open(db, ctx, lead_id=lead_id,
                                   program_id=program_id,
                                   chat_session_id="chat-f")

    assert found is not None
    assert found.id == session_id
    assert len(found.tags_json) == 9
    assert found.dossier_json["client"]["name"] == "Orchid F"


async def test_resuming_finds_the_fill_for_this_chat_and_not_another(
        client, org_a, monkeypatch):
    """Section 7: a fill is found by chat session, lead and programme, so
    "actually make it 3 units" an hour later lands on the right one."""
    token = org_a["admin_token"]
    ctx, lead_id, program_id, _ = await _ground(client, token, "FILLG", "Orchid G")
    other_lead = await _lead(client, token, "Different School")
    _use(monkeypatch, {"resolutions": []}, {"resolutions": []})

    async with SessionLocal() as db:
        mine = await fs.open_session(db, ctx, lead_id=lead_id,
                                     program_id=program_id,
                                     chat_session_id="chat-g")
        theirs = await fs.open_session(db, ctx, lead_id=other_lead,
                                       program_id=program_id,
                                       chat_session_id="chat-g")

    async with SessionLocal() as db:
        found = await fs.find_open(db, ctx, lead_id=lead_id,
                                   program_id=program_id,
                                   chat_session_id="chat-g")
        wrong_chat = await fs.find_open(db, ctx, lead_id=lead_id,
                                        program_id=program_id,
                                        chat_session_id="some-other-chat")

    assert found.id == mine.id
    assert found.id != theirs.id
    assert wrong_chat is None


async def test_a_fill_from_another_organisation_is_never_found(
        client, org_a, org_b, monkeypatch):
    token = org_a["admin_token"]
    ctx, lead_id, program_id, _ = await _ground(client, token, "FILLH", "Orchid H")
    _use(monkeypatch, {"resolutions": []})
    async with SessionLocal() as db:
        await fs.open_session(db, ctx, lead_id=lead_id, program_id=program_id,
                              chat_session_id="chat-h")

    intruder = await _ctx(client, org_b["admin_token"])
    async with SessionLocal() as db:
        found = await fs.find_open(db, intruder, lead_id=lead_id,
                                   program_id=program_id,
                                   chat_session_id="chat-h")
    assert found is None


async def test_a_week_old_fill_is_abandoned_rather_than_resumed(
        client, org_a, monkeypatch):
    """Question 8, answered by the owner: seven days, then abandoned, never
    resumed silently. Reviving week-old half-answers the salesperson has
    forgotten giving is worse than starting again."""
    token = org_a["admin_token"]
    ctx, lead_id, program_id, _ = await _ground(client, token, "FILLI", "Orchid I")
    _use(monkeypatch, {"resolutions": []})
    async with SessionLocal() as db:
        session = await fs.open_session(db, ctx, lead_id=lead_id,
                                        program_id=program_id,
                                        chat_session_id="chat-i")
        session_id = session.id

    # Pinned to the literal the owner answered question 8 with. Deriving the
    # stale timestamp from the constant alone would move with it, so widening
    # the window to a year would pass a test named for a week.
    assert fs.FILL_SESSION_TTL_DAYS == 7
    stale = utcnow() - timedelta(days=fs.FILL_SESSION_TTL_DAYS, hours=1)
    async with SessionLocal() as db:
        await db.execute(update(ProposalFillSession)
                         .where(ProposalFillSession.id == session_id)
                         .values(updated_at=stale))
        await db.commit()

    async with SessionLocal() as db:
        found = await fs.find_open(db, ctx, lead_id=lead_id,
                                   program_id=program_id,
                                   chat_session_id="chat-i")
    assert found is None

    async with SessionLocal() as db:
        row = await db.get(ProposalFillSession, session_id)
        assert row.status == FillStatus.ABANDONED


async def test_a_fill_just_inside_the_window_is_still_resumed(
        client, org_a, monkeypatch):
    token = org_a["admin_token"]
    ctx, lead_id, program_id, _ = await _ground(client, token, "FILLJ", "Orchid J")
    _use(monkeypatch, {"resolutions": []})
    async with SessionLocal() as db:
        session = await fs.open_session(db, ctx, lead_id=lead_id,
                                        program_id=program_id,
                                        chat_session_id="chat-j")
        session_id = session.id

    fresh = utcnow() - timedelta(days=fs.FILL_SESSION_TTL_DAYS, hours=-1)
    async with SessionLocal() as db:
        await db.execute(update(ProposalFillSession)
                         .where(ProposalFillSession.id == session_id)
                         .values(updated_at=fresh))
        await db.commit()

    async with SessionLocal() as db:
        found = await fs.find_open(db, ctx, lead_id=lead_id,
                                   program_id=program_id,
                                   chat_session_id="chat-j")
    assert found is not None and found.id == session_id


async def test_an_abandoned_fill_is_never_resumed(client, org_a, monkeypatch):
    token = org_a["admin_token"]
    ctx, lead_id, program_id, _ = await _ground(client, token, "FILLK", "Orchid K")
    _use(monkeypatch, {"resolutions": []})
    async with SessionLocal() as db:
        session = await fs.open_session(db, ctx, lead_id=lead_id,
                                        program_id=program_id,
                                        chat_session_id="chat-k")
        await fs.abandon(db, session)

    async with SessionLocal() as db:
        assert await fs.find_open(db, ctx, lead_id=lead_id,
                                  program_id=program_id,
                                  chat_session_id="chat-k") is None


# --- answering ---------------------------------------------------------------


async def test_answers_accumulate_across_rounds(client, org_a, monkeypatch):
    token = org_a["admin_token"]
    ctx, lead_id, program_id, template_id = await _ground(
        client, token, "FILLL", "Orchid L")
    tags = await _plan_tags(template_id)
    asks = [t for t in tags if t["kind"] != "semantic"]

    _use(monkeypatch, {"resolutions": []})
    async with SessionLocal() as db:
        session = await fs.open_session(db, ctx, lead_id=lead_id,
                                        program_id=program_id,
                                        chat_session_id="chat-l")
        session_id = session.id
    assert len(fs.open_questions(session, limit=None)) == 9

    _use(monkeypatch, {"resolutions": [
        {"tag_id": t["tag_id"], "value": "2 Units", "reason": "two of each"}
        for t in asks[:3]
    ]})
    async with SessionLocal() as db:
        session = await fs.find_open(db, ctx, lead_id=lead_id,
                                     program_id=program_id,
                                     chat_session_id="chat-l")
        session = await fs.apply_answers(db, ctx, session, "two of each")
    assert len(fs.open_questions(session, limit=None)) == 6
    assert len(session.asked_json) == 1

    _use(monkeypatch, {"resolutions": [
        {"tag_id": t["tag_id"], "value": "1 Unit", "reason": "one of the rest"}
        for t in asks[3:]
    ]})
    async with SessionLocal() as db:
        session = await fs.find_open(db, ctx, lead_id=lead_id,
                                     program_id=program_id,
                                     chat_session_id="chat-l")
        session = await fs.apply_answers(db, ctx, session, "one of the rest")

    assert len(session.asked_json) == 2
    # The first round's answers survived the second.
    by_id = {t["tag_id"]: t for t in session.tags_json}
    assert by_id[asks[0]["tag_id"]]["value"] == "2 Units"
    assert by_id[asks[6]["tag_id"]]["value"] == "1 Unit"
    assert len(fs.open_questions(session, limit=None)) == 2   # the two semantic


async def test_an_answer_cites_the_turn_it_was_given_in(
        client, org_a, monkeypatch):
    """D14 for a user value, and it needs the round count this row is keeping:
    C2 numbers the turn from `asked`, so a wrong ledger here makes every
    citation in the review point at the wrong message."""
    token = org_a["admin_token"]
    ctx, lead_id, program_id, template_id = await _ground(
        client, token, "FILLM", "Orchid M")
    asks = [t for t in await _plan_tags(template_id) if t["kind"] != "semantic"]

    _use(monkeypatch, {"resolutions": []})
    async with SessionLocal() as db:
        session = await fs.open_session(db, ctx, lead_id=lead_id,
                                        program_id=program_id,
                                        chat_session_id="chat-m")

    for round_no, reply in enumerate(("two of each", "make it three"), start=1):
        _use(monkeypatch, {"resolutions": [
            {"tag_id": asks[round_no - 1]["tag_id"], "value": "2 Units",
             "reason": "said so"},
        ]})
        async with SessionLocal() as db:
            session = await fs.find_open(db, ctx, lead_id=lead_id,
                                         program_id=program_id,
                                         chat_session_id="chat-m")
            session = await fs.apply_answers(db, ctx, session, reply)
        by_id = {t["tag_id"]: t for t in session.tags_json}
        got = by_id[asks[round_no - 1]["tag_id"]]
        assert got["citation"] == f'turn {round_no}: "{reply}"'
        assert got["source"] == "user"


async def test_a_round_is_at_most_six_questions(client, org_a, monkeypatch):
    """D5. Nineteen forced questions is not a conversation, it is an
    interrogation; the owner accepted six per round on 7 September."""
    token = org_a["admin_token"]
    ctx, lead_id, program_id, _ = await _ground(client, token, "FILLN", "Orchid N")
    _use(monkeypatch, {"resolutions": []})
    async with SessionLocal() as db:
        session = await fs.open_session(db, ctx, lead_id=lead_id,
                                        program_id=program_id,
                                        chat_session_id="chat-n")

    assert fs.QUESTIONS_PER_ROUND == 6
    assert len(fs.open_questions(session)) == 6
    assert len(fs.open_questions(session, limit=None)) == 9
    assert all(q["outcome"] == "question" for q in fs.open_questions(session))
    assert all(q.get("question") for q in fs.open_questions(session))


async def test_the_model_is_given_every_outstanding_question_not_just_a_round(
        client, org_a, monkeypatch):
    """Section 7 says the clarification carries "the outstanding questions".
    Six is how many a person is SHOWN (D5); the model sees all of them, so
    "two of each" can settle quantities from a round nobody has reached yet,
    and D8's duplicates of one literal resolve together whichever round they
    surfaced in."""
    token = org_a["admin_token"]
    ctx, lead_id, program_id, template_id = await _ground(
        client, token, "FILLT", "Orchid T")
    _use(monkeypatch, {"resolutions": []})
    async with SessionLocal() as db:
        session = await fs.open_session(db, ctx, lead_id=lead_id,
                                        program_id=program_id,
                                        chat_session_id="chat-t")
    assert len(fs.open_questions(session, limit=None)) == 9
    assert len(fs.open_questions(session)) == 6

    layer = _use(monkeypatch, {"resolutions": []})
    async with SessionLocal() as db:
        session = await fs.find_open(db, ctx, lead_id=lead_id,
                                     program_id=program_id,
                                     chat_session_id="chat-t")
        await fs.apply_answers(db, ctx, session, "two of each")

    for tag in await _plan_tags(template_id):
        assert tag["tag_id"] in layer.prompt


async def test_accepting_the_suggestions_never_settles_a_question_nobody_saw(
        client, org_a, monkeypatch):
    """"All the suggested values are fine" is about the round a person was
    SHOWN. This fixture's first round is six -- the two semantic tags and the
    first four rows -- so the last three rows are not on screen yet, and a
    model that accepts their suggestions anyway, as the live one did on the
    Orchid contract, must not settle them. They are asked in their own round.
    """
    token = org_a["admin_token"]
    ctx, lead_id, program_id, template_id = await _ground(
        client, token, "FILLOS", "Orchid On Screen")
    asks = {t["context"]: t for t in await _plan_tags(template_id)
            if t["kind"] != "semantic"}
    _use(monkeypatch, {"resolutions": []})
    async with SessionLocal() as db:
        await fs.open_session(db, ctx, lead_id=lead_id, program_id=program_id,
                              chat_session_id="chat-onscreen")

    _use(monkeypatch, {"resolutions": [
        {"tag_id": t["tag_id"], "value": "1 Unit", "reason": "all fine"}
        for t in asks.values()]})
    async with SessionLocal() as db:
        session = await fs.find_open(db, ctx, lead_id=lead_id,
                                     program_id=program_id,
                                     chat_session_id="chat-onscreen")
        session = await fs.apply_answers(db, ctx, session,
                                         "All the suggested values are fine")

    by_id = {t["tag_id"]: t for t in session.tags_json}
    for row in ("Laptops", "Interactive Panel", "Magazine Rack", "Projector"):
        assert by_id[asks[row]["tag_id"]]["outcome"] == "filled", row
    for row in ("3D Printer", "Drone Kit", "Safety Glasses"):
        assert by_id[asks[row]["tag_id"]]["outcome"] == "question", row


async def test_a_reply_with_nothing_open_changes_nothing(
        client, org_a, monkeypatch):
    """The boundary this task stops at. A fill in `reviewing` has no open
    question, so there is nothing for a clarification to settle -- a
    CORRECTION to an already-reviewed value is a different act, needing a
    different model call to work out which tag it means, and it belongs to J2.
    """
    ctx, session = await _answer_everything(
        client, org_a, monkeypatch, "FILLU", "Orchid U", "chat-u")
    before = [dict(t) for t in session.tags_json]

    layer = _use(monkeypatch, {"resolutions": []})
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        session = await fs.apply_answers(db, ctx, session, "make it three")

    assert layer.calls == []
    assert session.tags_json == before
    assert session.status == FillStatus.REVIEWING
    assert len(session.asked_json) == 1


async def test_answering_an_abandoned_fill_is_refused(
        client, org_a, monkeypatch):
    token = org_a["admin_token"]
    ctx, lead_id, program_id, _ = await _ground(client, token, "FILLO", "Orchid O")
    _use(monkeypatch, {"resolutions": []})
    async with SessionLocal() as db:
        session = await fs.open_session(db, ctx, lead_id=lead_id,
                                        program_id=program_id,
                                        chat_session_id="chat-o")
        await fs.abandon(db, session)
        with pytest.raises(ValidationFailedError):
            await fs.apply_answers(db, ctx, session, "two of each")


# --- reaching ready ----------------------------------------------------------


async def _answer_everything(client, org_a, monkeypatch, code, name, chat):
    """Open a fill and settle every question, leaving it in `reviewing`."""
    token = org_a["admin_token"]
    ctx, lead_id, program_id, template_id = await _ground(client, token, code, name)
    tags = await _plan_tags(template_id)

    _use(monkeypatch, {"resolutions": []})
    async with SessionLocal() as db:
        await fs.open_session(db, ctx, lead_id=lead_id, program_id=program_id,
                              chat_session_id=chat)

    _use(monkeypatch, {"resolutions": [
        {"tag_id": t["tag_id"], "value": "2 Units", "reason": "all of them"}
        for t in tags
    ]})
    async with SessionLocal() as db:
        session = await fs.find_open(db, ctx, lead_id=lead_id,
                                     program_id=program_id,
                                     chat_session_id=chat)
        session = await fs.apply_answers(db, ctx, session, "two of each")
    return ctx, session


async def test_settling_the_last_question_moves_the_fill_to_review(
        client, org_a, monkeypatch):
    _, session = await _answer_everything(
        client, org_a, monkeypatch, "FILLP", "Orchid P", "chat-p")
    assert fs.open_questions(session, limit=None) == []
    assert session.status == FillStatus.REVIEWING


async def test_ready_is_reachable_only_through_reviewing(
        client, org_a, monkeypatch):
    """D13, asserted as a TRANSITION and not just an outcome. A fill still
    asking questions cannot be marked ready by a caller that skipped the
    review, because that is exactly the mistake the review exists to stop."""
    token = org_a["admin_token"]
    ctx, lead_id, program_id, _ = await _ground(client, token, "FILLQ", "Orchid Q")
    _use(monkeypatch, {"resolutions": []})
    async with SessionLocal() as db:
        session = await fs.open_session(db, ctx, lead_id=lead_id,
                                        program_id=program_id,
                                        chat_session_id="chat-q")
        assert session.status == FillStatus.ASKING
        with pytest.raises(ValidationFailedError):
            await fs.mark_ready(db, session)
        assert session.status == FillStatus.ASKING


async def test_marking_ready_records_that_a_human_saw_every_value(
        client, org_a, monkeypatch):
    """D13's `reviewed` flag, on every tag including the ones filled silently."""
    _, session = await _answer_everything(
        client, org_a, monkeypatch, "FILLR", "Orchid R", "chat-r")
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        session = await fs.mark_ready(db, session)

    assert session.status == FillStatus.READY
    assert session.tags_json
    assert all(t["reviewed"] is True for t in session.tags_json)


async def test_a_ready_fill_reloads_ready(client, org_a, monkeypatch):
    _, session = await _answer_everything(
        client, org_a, monkeypatch, "FILLS", "Orchid S", "chat-s")
    async with SessionLocal() as db:
        session = await db.get(ProposalFillSession, session.id)
        await fs.mark_ready(db, session)
        session_id = session.id

    async with SessionLocal() as db:
        row = await db.get(ProposalFillSession, session_id)
    assert row.status == FillStatus.READY
    assert all(t["reviewed"] for t in row.tags_json)
