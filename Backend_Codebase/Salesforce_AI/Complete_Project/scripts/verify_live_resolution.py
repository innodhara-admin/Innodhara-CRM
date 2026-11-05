"""Live verification of FINDING F28 — the assistant understands a short,
natural command, and when it genuinely cannot it ASKS instead of failing.

Against a REAL model, with nothing forced: no `agent` override (so the router
has to choose — that is fix 4) and no context chip (so the client has to be
read out of the sentence — that is fix 1).

  1. "Draft an email to <PERSON> at <CLIENT> about X" — the phrase observed
     failing on the device — produces a real draft addressed to that person.
     Before F28 `resolvers.py:142` only asked whether the typed hint sat INSIDE
     the stored name, so a hint longer than the name could never match.
  2. Nothing is sent: the draft waits for the human's one-tap approval.
  3. "Reply to their question…" reaches the EMAIL agent and becomes a draft.
     Before F28 the proposal agent took it and answered in the chat — prose in
     a bubble is not a reply the client ever receives.
  4. A genuinely ambiguous person is a QUESTION, not a failure: the action
     carries `outcome: needs_confirmation` with the candidates, and no message
     is created behind the user's back. ASK, NEVER GUESS.
  5. Answering that question in the same conversation completes the job.
  6. A command naming nobody asks who, rather than picking a recipient.

Runs on its own throwaway database (a verify script must never write llm_usage
rows into the live one — the §6g lesson). Model calls only: EMAIL_MODE=dry_run
and CALENDAR_MODE=off, so no mail leaves the machine and no calendar is
touched.

Run:  python scripts/verify_live_resolution.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "verify_resolution.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
os.environ["EMAIL_MODE"] = "dry_run"
os.environ["WHATSAPP_MODE"] = "dry_run"
os.environ["CALENDAR_MODE"] = "off"

import httpx  # noqa: E402

CHECKS: list[tuple[str, bool, str]] = []


def check(desc: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((desc, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {desc}" + (f"  ({detail})" if detail else ""))
    return bool(ok)


def _asked(resp: dict) -> dict | None:
    """The needs-confirmation action, if the run produced one."""
    for action in resp.get("actions", []):
        if action.get("outcome") == "needs_confirmation":
            return action
    return None


def _drafted(resp: dict) -> list[dict]:
    return resp.get("pending_approvals", [])


async def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()

    from app.config import get_settings

    s = get_settings()
    assert s.llm_provider != "stub", "Needs a real LLM provider in .env"
    print(f"LIVE F28 resolution run — provider={s.llm_provider}, "
          f"email={s.email_mode}, calendar={s.calendar_mode}\n")

    from app.database import SessionLocal, init_db
    from app.jobs import register_handlers
    from app.main import _seed_super_admin, app
    from app.models.messaging import OutboundMessage
    from sqlalchemy import select

    await init_db()
    await _seed_super_admin()
    register_handlers()

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(
        transport=transport, base_url="http://test/api/v1", timeout=300
    )
    tokens: dict[str, str] = {}

    async def login(email: str, password: str) -> str:
        r = await client.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["access_token"]

    async def call(method: str, path: str, *, user: str, json: dict | None = None):
        r = await client.request(
            method, path, json=json,
            headers={"Authorization": f"Bearer {tokens[user]}"},
        )
        if r.status_code >= 400:
            raise AssertionError(f"{method} {path} → {r.status_code}: {r.text[:400]}")
        return r.json()

    # ── Seed ────────────────────────────────────────────────────────────────
    super_token = await login(s.super_admin_email, s.super_admin_password)
    org = (
        await client.post(
            "/orgs",
            headers={"Authorization": f"Bearer {super_token}"},
            json={"name": "Resolution Test Co", "slug": "res-test",
                  "email_domain": "res-example.com",
                  "admin_email": "admin@res-example.com",
                  "admin_name": "Res Admin"},
        )
    ).json()
    tokens["admin"] = await login(org["admin_email"], org["admin_temp_password"])
    created = await call("POST", "/admin/users", user="admin",
                         json={"email": "asha@res-example.com", "name": "Asha Agent",
                               "role": "sales_agent"})
    tokens["asha"] = await login("asha@res-example.com", created["temp_password"])

    async def make_lead(name: str) -> str:
        return (await call("POST", "/leads", user="asha", json={"name": name}))["id"]

    async def add_contact(lead_id: str, **fields) -> None:
        await call("POST", f"/leads/{lead_id}/contacts", user="asha", json=fields)

    # A multi-word client name, so "PERSON at CLIENT" is a genuinely long hint.
    orchid = await make_lead("Orchid International School")
    await add_contact(orchid, name="EKAGHNI MUKHERJEE", title="CSR Manager",
                      email="ekaghni@orchid-example.com", is_primary=True)

    # Two people sharing a surname, neither marked primary: the ambiguity is
    # real, and picking one would be a guess.
    kirloskar = await make_lead("Kirloskar Industries")
    await add_contact(kirloskar, name="Priya Nair", title="Finance Controller",
                      email="priya@kirloskar-example.com")
    await add_contact(kirloskar, name="Anita Nair", title="Operations Head",
                      email="anita@kirloskar-example.com")

    async def messages() -> list[OutboundMessage]:
        async with SessionLocal() as db:
            return list((await db.execute(
                select(OutboundMessage).where(OutboundMessage.org_id == org["id"])
            )).scalars().all())

    async def command(text: str, **extra) -> dict:
        """No agent forced and no lead_id: the router and the resolvers have to
        do the work, which is the whole point of F28."""
        return await call("POST", "/assistant/command", user="asha",
                          json={"text": text, **extra})

    # ── 1. The phrase that failed on the device ─────────────────────────────
    print("1. \"Draft an email to <PERSON> at <CLIENT> about X\" — typed naturally")
    r1 = await command(
        "Draft an email to EKAGHNI MUKHERJEE at Orchid International School "
        "about the workshop dates for next month"
    )
    print(f"     agent: {r1['agent']}\n     reply: {r1['reply'][:220]}")
    check("the router sends it to the email agent", r1["agent"] == "email", r1["agent"])
    after1 = await messages()
    to_ekaghni = [m for m in after1 if (m.to_address or "") == "ekaghni@orchid-example.com"]
    check("a real draft was created, addressed to the person named in the phrase",
          len(to_ekaghni) == 1,
          str([(m.to_address, m.status) for m in after1]))
    check("no lookup failure was reported for the long phrase",
          _asked(r1) is None and all(a.get("ok") for a in r1["actions"]),
          str([(a["tool"], a.get("ok"), a.get("error", "")[:80]) for a in r1["actions"]]))
    # Ask-never-guess's other half: when it DOES resolve, say who.
    check("the reply names the recipient out loud",
          "ekaghni" in r1["reply"].lower(), r1["reply"][:160])

    # ── 2. Nothing was sent ────────────────────────────────────────────────
    print("2. The draft waits for a human")
    check("the draft is parked for approval, not sent",
          bool(to_ekaghni) and to_ekaghni[0].status == "pending_approval",
          to_ekaghni[0].status if to_ekaghni else "no message")
    check("the app is handed an inline approval to render", bool(_drafted(r1)),
          str(len(_drafted(r1))))

    # ── 3. A reply to an inbound question becomes a DRAFT, not chat prose ───
    print("3. \"Reply to their question…\" — fix 4's routing line")
    before3 = len(await messages())
    r3 = await command(
        "Reply to EKAGHNI MUKHERJEE at Orchid International School — she asked "
        "whether we can refund a cancelled workshop. Tell her we can, within 30 days."
    )
    print(f"     agent: {r3['agent']}\n     reply: {r3['reply'][:220]}")
    check("a reply request reaches the email agent, not the proposal agent",
          r3["agent"] == "email", r3["agent"])
    check("the reply became a real draft rather than words in a chat bubble",
          len(await messages()) > before3,
          f"{before3} → {len(await messages())}")

    # ── 4. Genuinely ambiguous: ask, do not guess ──────────────────────────
    print("4. An ambiguous person must ask — never pick one")
    before4 = len(await messages())
    session = uuid.uuid4().hex
    r4 = await command(
        "Draft an email to Nair at Kirloskar Industries about the pending invoice",
        session_id=session,
    )
    asked = _asked(r4)
    print(f"     agent: {r4['agent']}\n     reply: {r4['reply'][:260]}")
    check("the run reports a question, not a failure", asked is not None,
          str([(a["tool"], a.get("outcome"), a.get("error", "")[:70])
               for a in r4["actions"]]))
    if asked:
        check("both candidates are carried as data the app can offer as taps",
              {"Priya Nair", "Anita Nair"} <= set(asked.get("candidates") or []),
              str(asked.get("candidates")))
    check("nothing was drafted to a recipient the user did not choose",
          len(await messages()) == before4,
          f"{before4} → {len(await messages())}")
    check("the assistant asks the user which person is meant",
          "?" in r4["reply"] and "nair" in r4["reply"].lower(), r4["reply"][:200])
    # No fake success (§7 rule 3): the first live run of this script caught the
    # model opening with "I drafted the email… ready for your one-tap approval"
    # and only THEN asking which Nair — announcing work it had not done.
    #
    # Only PAST-TENSE claims of a finished draft count. "ready for your
    # approval" was tried first and had to be dropped: a later run said "Once
    # you confirm, the email WILL BE ready for your one-tap approval", which is
    # both honest and exactly what we want it to say. Assert the property (it
    # must not claim the draft exists), not a phrase that appears in the
    # correct sentence too.
    claimed = [
        phrase for phrase in ("i drafted", "i've drafted", "i have drafted",
                              "i’ve drafted", "drafted the email", "i prepared",
                              "i've prepared", "i’ve prepared", "i created",
                              "draft ready", "i've sent", "i sent")
        if phrase in r4["reply"].lower()
    ]
    check("the reply does not claim a draft that does not exist",
          not claimed, f"claimed: {claimed}")

    # ── 5. Answering the question finishes the job ─────────────────────────
    print("5. Answering the question completes the command")
    r5 = await command("Priya Nair — the finance controller", session_id=session)
    print(f"     reply: {r5['reply'][:220]}")
    after5 = await messages()
    to_priya = [m for m in after5 if (m.to_address or "") == "priya@kirloskar-example.com"]
    check("the answer resolves the person and the draft is created",
          len(to_priya) == 1, str([(m.to_address, m.status) for m in after5]))
    check("still nothing went to the person the user did not pick",
          not [m for m in after5 if (m.to_address or "") == "anita@kirloskar-example.com"],
          "anita has no message")

    # ── 6. Naming nobody asks who ──────────────────────────────────────────
    print("6. A command naming nobody asks who, rather than choosing")
    before6 = len(await messages())
    r6 = await command(
        "Draft an email to Kirloskar Industries about the pending invoice"
    )
    print(f"     reply: {r6['reply'][:260]}")
    check("a recipient is asked for rather than picked out of the list",
          _asked(r6) is not None or len(await messages()) == before6,
          str([(a["tool"], a.get("outcome")) for a in r6["actions"]]))

    # ── 7. F30: the blanks fence, against real model output ────────────────
    # The unit tests prove the detector both ways on fixed strings. What only a
    # live run can tell us is whether it FALSE-POSITIVES on genuine AI-written
    # emails — a fence that blocks real sends is worse than the bug it stops.
    print("7. The unfinished-draft fence does not block real AI-written emails")
    real_drafts = [m for m in await messages() if m.status == "pending_approval"]
    from app.services import draft_check  # noqa: E402 — after settings are set

    false_positives = [
        (m.subject, draft_check.find_blanks(m.subject, m.body))
        for m in real_drafts
        if draft_check.find_blanks(m.subject, m.body)
    ]
    check("no genuine draft from this run was flagged as unfinished",
          not false_positives, str(false_positives)[:300])
    for message in real_drafts[:1]:
        approved = await call("POST", f"/messages/{message.id}/approve", user="asha")
        check("a real draft still approves and queues normally",
              approved.get("approved") is True, str(approved))

    # And the other direction, through the API, on a draft that IS unfinished.
    print("   …and it does stop one that is unfinished")
    from app.core.context import OrgContext  # noqa: E402
    from app.services import message_service  # noqa: E402

    async with SessionLocal() as db:
        ctx = OrgContext(org_id=org["id"], user_id=org["admin_id"] if org.get("admin_id")
                         else org["id"], role="sales_agent", email="asha@res-example.com")
        blanked = await message_service.create_message(
            db, ctx, kind="follow_up", channel="email",
            to_address="someone@res-example.com", subject="Workshop confirmation",
            body="Hello,\n\nThe workshop is confirmed.\n\nDate: [Insert Date]\n\nSiva",
        )
        await db.commit()
        blanked_id = blanked.id
    r7 = await client.post(
        f"/messages/{blanked_id}/approve",
        headers={"Authorization": f"Bearer {tokens['asha']}"},
    )
    check("approving a draft with a blank is refused, verbatim",
          r7.status_code == 422 and "[Insert Date]" in r7.text, f"{r7.status_code} {r7.text[:160]}")

    await client.aclose()

    print("\n" + "=" * 70)
    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print(f"{passed}/{len(CHECKS)} checks passed")
    for desc, ok, detail in CHECKS:
        if not ok:
            print(f"  FAILED: {desc} — {detail}")
    sys.exit(0 if passed == len(CHECKS) else 1)


async def _run() -> None:
    # aiosqlite's threads are non-daemon: without an explicit dispose a failed
    # run keeps a lock on its own DB file and the next run dies with
    # PermissionError (§6g).
    try:
        await main()
    finally:
        from app.database import engine

        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
