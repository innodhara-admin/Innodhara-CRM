# tests/docx/test_client_dossier.py
"""Everything the model is told about a client, assembled once (Task C1).

D7's decision, and the measurement behind it: the busiest real client in the
database is about 11,900 tokens, the largest real template under 5,600, and the
window is a million. There is no size reason to summarise, sample or cap
anything, so this does not -- the first draft of D7 capped meetings at 5 and
notes at 10 and would have hidden from the model exactly the sentences it needs.

`DOSSIER_CHAR_CEILING` is a safety valve, not a budget.
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.context import OrgContext
from app.database import SessionLocal
from app.models.lead import Lead
from app.models.lead import ClientIntelligence
from app.models.program import Program
from app.services import client_dossier as cd
from tests.conftest import auth

API = "/api/v1"
pytestmark = pytest.mark.asyncio

LIVE_DB = Path(__file__).resolve().parents[2] / "data" / "salesplatform.db"

#: Every key D7 names. A section that is empty is still a section: a model told
#: "meetings: []" knows there were none, and one told nothing does not.
SECTIONS = {
    "client", "state_history", "contacts", "notes", "meetings",
    "project", "plans", "commitments", "stakeholders", "deliverables",
    "invoices", "action_items", "followups", "demos", "proposals",
    "threads", "messages", "consent", "memory",
    "programme", "rate_card", "sender", "organisation", "omitted",
}


async def _ctx(client, token) -> OrgContext:
    me = (await client.get(f"{API}/auth/me", headers=auth(token))).json()
    return OrgContext(
        org_id=me["org_id"], user_id=me["user_id"],
        role=me["role"], email=me["email"],
    )


async def _bare_client(client, token, name, code):
    """A lead and a programme with nothing else attached."""
    lead = (await client.post(f"{API}/leads", headers=auth(token),
                              json={"name": name})).json()
    program = (await client.post(f"{API}/admin/programs", headers=auth(token),
                                 json={"name": name, "code": code,
                                       "description": "d"})).json()
    return lead["id"], program["id"]


# --- the shape ---------------------------------------------------------------


async def test_every_section_is_present_even_when_it_is_empty(client, org_a):
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    lead_id, program_id = await _bare_client(client, token, "Empty School", "DOSA")

    async with SessionLocal() as db:
        dossier = await cd.build(db, ctx, lead_id, program_id)

    assert set(dossier) == SECTIONS
    assert dossier["meetings"] == []
    assert dossier["notes"] == []
    assert dossier["client"]["name"] == "Empty School"
    assert dossier["programme"]["name"] == "Empty School"
    assert dossier["organisation"]["name"]
    assert dossier["sender"]["email"] == ctx.email


async def test_a_client_with_no_history_still_produces_a_valid_dossier(client, org_a):
    """The common case for a new client, and it must not raise."""
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    lead_id, program_id = await _bare_client(client, token, "Brand New", "DOSB")

    async with SessionLocal() as db:
        dossier = await cd.build(db, ctx, lead_id, program_id)

    assert json.dumps(dossier, default=str)
    assert dossier["project"] is None
    assert dossier["rate_card"] is None
    assert dossier["omitted"] == []


# --- what is deliberately left out -------------------------------------------


async def test_the_engines_own_reasoning_is_not_fed_back_to_it(client, org_a):
    """D7 excludes ai_decisions and progress_events on QUALITY grounds.

    Feeding a model its own earlier guesses invites it to treat them as
    established fact, and state-machine bookkeeping is volume without meaning.
    Together they were 15,570 of the measured 47,525 characters, so removing
    them makes the dossier better and smaller at once.
    """
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    lead_id, program_id = await _bare_client(client, token, "No Echo", "DOSC")

    async with SessionLocal() as db:
        dossier = await cd.build(db, ctx, lead_id, program_id)

    assert "ai_decisions" not in dossier
    assert "progress_events" not in dossier
    assert cd.EXCLUDED == ("ai_decisions", "progress_events")


async def test_no_secret_ever_reaches_the_dossier(client, org_a):
    """The sender is a user row, and user rows carry a password hash and an
    encrypted SMTP password. Neither has any business in a prompt."""
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    lead_id, program_id = await _bare_client(client, token, "No Secrets", "DOSD")

    async with SessionLocal() as db:
        dossier = await cd.build(db, ctx, lead_id, program_id)

    text = json.dumps(dossier, default=str)
    for forbidden in ("password_hash", "smtp_app_password_enc", "embedding"):
        assert forbidden not in text


# --- nothing is capped -------------------------------------------------------


async def test_every_note_is_included_not_the_most_recent_few(client, org_a):
    """`_client_details` in the query agent caps notes at 5, which is right for
    a chat summary and wrong here: the sentence that says when the programme
    runs may be the oldest note there is."""
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    lead_id, program_id = await _bare_client(client, token, "Many Notes", "DOSE")

    async with SessionLocal() as db:
        for i in range(30):
            db.add(ClientIntelligence(
                org_id=ctx.org_id, lead_id=lead_id,
                note=f"note number {i}", category="general", source="test",
            ))
        await db.commit()
        dossier = await cd.build(db, ctx, lead_id, program_id)

    assert len(dossier["notes"]) == 30
    assert dossier["omitted"] == []


# --- the safety valve --------------------------------------------------------


async def test_a_dossier_over_the_ceiling_drops_oldest_first(client, org_a):
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    lead_id, program_id = await _bare_client(client, token, "Very Busy", "DOSF")

    async with SessionLocal() as db:
        for i in range(100):
            db.add(ClientIntelligence(
                org_id=ctx.org_id, lead_id=lead_id,
                note=f"note {i:03d} " + ("x" * 1000), category="general",
                source="test",
            ))
        await db.commit()
        dossier = await cd.build(db, ctx, lead_id, program_id)

    kept = dossier["notes"]
    assert 0 < len(kept) < 100, "the ceiling should have dropped some, not all"
    # Oldest-first: the survivors are the newest, and they are contiguous.
    numbers = [int(n["note"][5:8]) for n in kept]
    assert numbers == sorted(numbers)
    assert numbers[-1] == 99, "the newest note must survive"
    assert numbers == list(range(numbers[0], 100)), "a contiguous newest run"


async def test_nothing_is_ever_truncated_mid_record(client, org_a):
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    lead_id, program_id = await _bare_client(client, token, "Whole Records", "DOSG")

    async with SessionLocal() as db:
        for i in range(100):
            db.add(ClientIntelligence(
                org_id=ctx.org_id, lead_id=lead_id,
                note=f"note {i:03d} " + ("x" * 1000), category="general",
                source="test",
            ))
        await db.commit()
        dossier = await cd.build(db, ctx, lead_id, program_id)

    for note in dossier["notes"]:
        assert len(note["note"]) == 1009, "a surviving record must be whole"


async def test_the_prompt_is_told_what_was_dropped_and_how_much(client, org_a):
    """A model told "the 12 oldest notes were omitted" can ask about them.
    One handed a silently truncated dossier cannot."""
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    lead_id, program_id = await _bare_client(client, token, "Told Plainly", "DOSH")

    async with SessionLocal() as db:
        for i in range(100):
            db.add(ClientIntelligence(
                org_id=ctx.org_id, lead_id=lead_id,
                note=f"note {i:03d} " + ("x" * 1000), category="general",
                source="test",
            ))
        await db.commit()
        dossier = await cd.build(db, ctx, lead_id, program_id)

    assert len(dossier["omitted"]) == 1
    dropped = dossier["omitted"][0]
    assert dropped["section"] == "notes"
    assert dropped["dropped"] + len(dossier["notes"]) == 100
    assert dropped["dropped"] > 0
    assert "oldest" in dropped["why"].lower()


async def test_one_record_bigger_than_the_whole_ceiling_terminates(client, org_a):
    """A four-hour meeting transcript could be bigger than the ceiling on its own.

    Dropping whole records cannot get under the ceiling then, and the loop must
    stop rather than spin: it empties what it can, says so, and returns. Pinned
    because a trim loop that cannot make progress is the one bug in here that
    hangs a request instead of producing a wrong answer.
    """
    token = org_a["admin_token"]
    ctx = await _ctx(client, token)
    lead_id, program_id = await _bare_client(client, token, "One Huge Note", "DOSI")

    async with SessionLocal() as db:
        db.add(ClientIntelligence(
            org_id=ctx.org_id, lead_id=lead_id,
            note="x" * (cd.DOSSIER_CHAR_CEILING + 5_000),
            category="general", source="test",
        ))
        await db.commit()
        dossier = await cd.build(db, ctx, lead_id, program_id)

    assert dossier["notes"] == []
    assert dossier["omitted"][0]["section"] == "notes"
    assert dossier["omitted"][0]["dropped"] == 1


async def test_the_ceiling_is_a_safety_valve_well_above_the_busiest_client():
    """The number D7 fixed, kept exactly as the plan wrote it.

    D7 called it "about 25% above the busiest client today". Measured against
    this serialisation it is 8,481 characters above -- about 16%. Recorded as a
    finding rather than corrected here: raising a ceiling is the owner's call,
    and quietly moving it would hide that a real client is closer to it than
    the plan believed.
    """
    assert cd.DOSSIER_CHAR_CEILING == 60_000


# --- the client the plan measured --------------------------------------------


live = pytest.mark.skipif(
    not LIVE_DB.exists(), reason="the live database is not present"
)


@live
async def test_the_measured_client_produces_every_section():
    """Meridian Data Centres, the busiest client in the database on 7 Sep.

    Read straight out of the live file rather than the test fixture, because
    the point is the real shape of a real client. Skips on any machine that
    does not have it.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{LIVE_DB}")
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            lead = (
                await db.execute(
                    select(Lead).where(Lead.name == "Meridian Data Centres")
                )
            ).scalars().first()
            if lead is None:
                pytest.skip("Meridian Data Centres is not in this database")
            program = (
                await db.execute(select(Program).where(Program.org_id == lead.org_id))
            ).scalars().first()
            ctx = OrgContext(org_id=lead.org_id, user_id=lead.owner_id or "",
                             role="org_admin", email="measured@test")
            dossier = await cd.build(db, ctx, lead.id, program.id if program else "")
    finally:
        await engine.dispose()

    assert set(dossier) == SECTIONS
    assert dossier["client"]["name"] == "Meridian Data Centres"
    # Measured 7 Sep: 5 contacts, 36 notes, 5 meetings with 5 transcripts,
    # 31 action items, 12 outbound messages. Nothing is capped.
    assert len(dossier["contacts"]) == 5
    assert len(dossier["notes"]) == 36
    assert len(dossier["meetings"]) == 5
    assert len(dossier["action_items"]) == 31
    assert len(dossier["messages"]) == 12
    assert sum(1 for m in dossier["meetings"] if m["transcript"]) == 5

    # The transcripts arrive WHOLE, not summarised. Measured 8,450 characters
    # across the five, and they are the single richest source on this client --
    # precisely where "the programme runs 28 September to 2 October" would have
    # been said. A dossier carrying only the summaries would pass every other
    # assertion here and lose the sentences the fill actually needs.
    transcript_text = sum(
        len(m["transcript"]["text"] or "")
        for m in dossier["meetings"] if m["transcript"]
    )
    assert transcript_text > 8_000, f"only {transcript_text} characters of transcript"


@live
async def test_the_measured_client_fits_under_the_ceiling_with_room_to_spare():
    """D7's whole argument: no retrieval layer is needed, because the busiest
    real client is comfortably inside a window of a million tokens."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(f"sqlite+aiosqlite:///{LIVE_DB}")
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            lead = (
                await db.execute(
                    select(Lead).where(Lead.name == "Meridian Data Centres")
                )
            ).scalars().first()
            if lead is None:
                pytest.skip("Meridian Data Centres is not in this database")
            program = (
                await db.execute(select(Program).where(Program.org_id == lead.org_id))
            ).scalars().first()
            ctx = OrgContext(org_id=lead.org_id, user_id=lead.owner_id or "",
                             role="org_admin", email="measured@test")
            dossier = await cd.build(db, ctx, lead.id, program.id if program else "")
    finally:
        await engine.dispose()

    size = cd.size_of(dossier)
    assert dossier["omitted"] == [], "the busiest real client must not be trimmed"
    assert size < cd.DOSSIER_CHAR_CEILING

    # MEASURED 7 September 2026: 51,519 characters of JSON, of which 39,138 are
    # the text itself and 12,381 the structure around it.
    #
    # The plan projected about 31,955 characters of text (47,525 measured for a
    # complete dossier, minus ai_decisions 10,199 and progress_events 5,371).
    # This one carries 39,138. The difference is almost entirely the project
    # layer that D7 asks for and that projection did not count: action_plans
    # (3,676) and client_commitments (2,188). The transcripts reproduce the
    # plan's own figure closely -- 12,496 for the whole meetings section
    # against its 12,063 for transcripts alone -- which is what says the
    # extraction is right rather than merely large.
    #
    # The headroom is therefore 8,481 characters, not the 25% D7 assumed. That
    # is a finding recorded for the owner, not a number to fix by widening the
    # ceiling here.
    assert 45_000 < size < 56_000, f"measured {size} characters"
