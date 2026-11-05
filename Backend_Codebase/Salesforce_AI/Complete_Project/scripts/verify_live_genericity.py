"""FINDING F31 — live verification that the product is domain-generic.

The unit tests prove the fixes on strings I chose. This proves them against the
real model on a client that has nothing to do with education: a colocation
provider whose pricing table is denominated **per rack**, in **USD**.

  A. First meeting → project + plan, and a **value estimate that is a real
     number**. Before F31 this was silently `None` for any unit that was not
     "per student"/"flat" — including the demo org's own per-workshop table.
  B. The client emails asking to expand scope → the amendment carries **their**
     unit ("per rack"), not a hardcoded "per student", in a client-visible
     document.
  C. `document_engine.generate_text_artifact` — the function Phase 7.1 builds
     on — writes about this client **without** education vocabulary.
  D. `GET /projects` returns the **currency** it stores, so the app has
     something to render other than a hardcoded ₹.

Only a live model can tell you about false positives (§6i): a prompt that reads
neutral to me may still push the model into an industry, and that is the failure
this script exists to catch.

Run:  python scripts/verify_live_genericity.py     (uses the key in .env)
Writes to a throwaway DB — the live database is never touched.
"""
from __future__ import annotations

import asyncio
import json as _json
import os
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "verify_genericity.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
os.environ["EMAIL_MODE"] = "dry_run"
os.environ["WHATSAPP_MODE"] = "dry_run"
os.environ["CALENDAR_MODE"] = "off"

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy import text as sql_text  # noqa: E402

PASSWORD = "Password@123"
CHECKS: list[tuple[str, bool, str]] = []

# Every word that would betray the old assumption leaking into new text.
EDUCATION_WORDS = (
    "student", "school", "pupil", "principal", "teacher", "syllabus",
    "classroom", "curriculum", "academic", "semester",
)

RACK_RATE = 18000.0
COMMISSIONING = 250000.0

MEETING = """Site visit at Meridian Colocation, Whitefield data centre campus,
with Anil Varghese (VP Infrastructure) and Fatima Sheikh (Procurement Head).

They are expanding Hall 3 and want us to deliver the full rack build-out:
- 40 racks in Hall 3, each fitted out to their standard spec. Anil was explicit
  that the per-rack rate in our price list is what they are budgeting against.
- One commissioning and handover exercise across the whole hall, priced as a
  single engagement, not per rack.
- Fatima needs the bill of materials and the power draw sheet within 12 days;
  she is the one who releases the purchase order.
- Anil wants thermal validation signed off before any customer equipment is
  racked, and he will provide the hall access schedule next week.

They asked us to quote in US dollars — their parent entity settles in USD.
"""

SCOPE_EMAIL = """Anil here. Good news, the Hall 3 board approved the expansion.

Please add another 30 racks to the build — same spec as the first 40. Can you
send across the revised commercials for the additional racks?
"""


def check(desc: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((desc, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {desc}" + (f"  ({detail})" if detail else ""))
    return bool(ok)


class Api:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.tokens: dict[str, str] = {}

    async def login(self, email: str) -> str:
        if email not in self.tokens:
            r = await self.client.post("/auth/login",
                                       json={"email": email, "password": PASSWORD})
            r.raise_for_status()
            self.tokens[email] = r.json()["access_token"]
        return self.tokens[email]

    async def call(self, method: str, path: str, *, user: str,
                   json: dict | None = None, params: dict | None = None):
        token = await self.login(user)
        r = await self.client.request(method, path, json=json, params=params,
                                      headers={"Authorization": f"Bearer {token}"})
        if r.status_code >= 400:
            raise AssertionError(f"{method} {path} → {r.status_code}: {r.text[:400]}")
        return r.json()


async def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()

    from app.config import get_settings
    s = get_settings()
    assert s.llm_provider != "stub", "This verification needs a real LLM provider in .env"
    print(f"LIVE run — provider={s.llm_provider}\n")

    from app.database import init_db, engine, SessionLocal
    from app.jobs import register_handlers
    from app.engines import sync_engine
    from app.main import app
    from scripts.seed_workflows import seed

    await init_db()
    register_handlers()
    sync_engine.register()
    await seed()

    from app.models.program import Program, PricingTable, ProposalTemplate
    from app.models.project import Project
    from app.models.proposal import Proposal
    from app.models.user import User

    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test/api/v1",
                               timeout=300)
    api = Api(client)
    rahul, ananya = "rahul@yuvipep.com", "ananya@yuvipep.com"

    # ── A catalogue offering priced PER RACK, in USD ─────────────────────────
    async with SessionLocal() as db:
        org_id = (await db.execute(select(User).where(
            User.email == rahul
        ))).scalar_one().org_id
        program = Program(
            org_id=org_id, name="Data Centre Rack Build-out", code="dc_rack_buildout",
            description="Rack fit-out, power and thermal commissioning for "
                        "colocation halls",
            is_active=True,
        )
        db.add(program)
        await db.flush()
        pricing = PricingTable(
            org_id=org_id, program_id=program.id, version=1, currency="USD",
            is_current=True,
            items=[
                {"code": "rack", "label": "Rack fit-out", "unit": "per rack",
                 "unit_price": RACK_RATE},
                {"code": "commissioning", "label": "Hall commissioning",
                 "unit": "flat per hall", "unit_price": COMMISSIONING},
            ],
        )
        db.add(pricing)
        await db.flush()
        template = (await db.execute(select(ProposalTemplate).where(
            ProposalTemplate.org_id == org_id
        ))).scalars().first()
        await db.commit()
        program_id, program_name = program.id, program.name
        pricing_id, template_id = pricing.id, template.id
        template_ver = template.version

    print("Catalogue: 'Data Centre Rack Build-out' — per rack (USD), flat per hall\n")

    lead = await api.call("POST", "/leads", user=rahul, json={
        "name": "Meridian Colocation", "city": "Bengaluru", "source": "referral",
    })
    lead_id = lead["id"]
    # `POST /leads` creates in `cold_calling` since pre-sales shipped, and a
    # meeting cannot be recorded against a lead nobody has phoned. This stands
    # in for the cold call.
    await api.call("PATCH", f"/leads/{lead_id}/state", user=rahul,
                   json={"state": "open", "reason": "cold call went well"})
    await api.call("POST", f"/leads/{lead_id}/contacts", user=rahul, json={
        "name": "Anil Varghese", "title": "VP Infrastructure",
        "email": "anil@meridiancolo.example", "is_primary": True,
    })

    # ── A. value_estimate is a real number for a per-rack client ─────────────
    print("A. First meeting → project, plan, and a REAL value estimate")
    res = await api.call("POST", "/meetings/notes", user=rahul, json={
        "lead_id": lead_id, "title": "Meridian Hall 3 rack build — site visit",
        "text": MEETING, "meeting_type": "first_visit",
    })
    planner = res["planner"]
    if not check("project proposed from the meeting",
                 planner.get("action") == "project_proposed", str(planner)[:200]):
        raise SystemExit("Scenario A produced no project (likely a model/quota "
                         "hiccup) — aborting cleanly.")
    project_id = planner["project_id"]

    async with SessionLocal() as db:
        project = (await db.execute(select(Project).where(
            Project.id == project_id
        ))).scalar_one()
        value, matched = project.value_estimate, project.program_id

    check("the planner matched the per-rack catalogue offering",
          matched == program_id, f"program_id={matched}")
    # THE defect, stated as a number: this was silently None for any unit that
    # did not contain "student".
    check("value_estimate is a real number, not None (F31 defect 1)",
          value is not None and value > 0, f"value_estimate={value}")
    if value is not None and matched == program_id:
        racks = (value - COMMISSIONING) / RACK_RATE
        check("the estimate is the org's own arithmetic (n × per-rack + flat)",
              float(racks).is_integer() and racks > 0,
              f"{value} = {racks:g} × {RACK_RATE:g} + {COMMISSIONING:g}")

    # ── D. the currency travels with the amount ──────────────────────────────
    print("\nD. GET /projects carries the currency it stores")
    async with SessionLocal() as db:
        await db.execute(sql_text(
            "UPDATE projects SET currency = 'USD' WHERE id = :pid"
        ), {"pid": project_id})
        await db.commit()
    listed = await api.call("GET", "/projects", user=rahul, params={"lead_id": lead_id})
    row = next((p for p in listed if p["id"] == project_id), None)
    check("GET /projects returns `currency` (F31 defect 3 — the app had nothing "
          "to render but ₹)",
          row is not None and row.get("currency") == "USD",
          f"currency={row.get('currency') if row else None}")
    detail = await api.call("GET", f"/projects/{project_id}", user=rahul)
    check("GET /projects/{id} returns it too",
          detail.get("currency") == "USD", f"currency={detail.get('currency')}")

    # ── B. the amendment speaks the client's own unit ────────────────────────
    print("\nB. Scope grows → the amendment carries THEIR unit, not 'per student'")
    async with SessionLocal() as db:
        base = Proposal(
            org_id=org_id, lead_id=lead_id, program_id=program_id,
            project_id=project_id, title=f"{program_name} — Hall 3",
            status="accepted", currency="USD",
            template_id=template_id, template_version=template_ver,
            pricing_table_id=pricing_id, pricing_version=1,
            content_md=f"# {program_name} — Hall 3\n\n40 racks fitted out.",
            line_items=[{
                "code": "rack", "label": "Rack fit-out", "unit": "per rack",
                "unit_price": RACK_RATE, "quantity": 40,
                "line_total": RACK_RATE * 40,
            }],
            total_amount=RACK_RATE * 40, created_by="ai",
        )
        db.add(base)
        await db.commit()

    resp = await api.call("POST", "/inbound/ingest", user=ananya, json={
        "channel": "email", "from_address": "anil@meridiancolo.example",
        "subject": "Re: Hall 3 build-out — board approved",
        "body": SCOPE_EMAIL,
    })
    points = resp.get("extracted_points") or []
    scope = [p for p in points if p.get("type") == "scope_change"]
    check("the model read it as a scope change",
          bool(scope), f"points={[p.get('type') for p in points]}")
    delta = (scope[0].get("quantity_delta") or scope[0].get("students_delta")) if scope else None
    check("the count came through on a client counting RACKS, not students "
          "(the schema no longer calls the field students_delta)",
          delta == 30, f"quantity_delta={delta}")

    async with SessionLocal() as db:
        amendment = (await db.execute(select(Proposal).where(
            Proposal.project_id == project_id,
            Proposal.amends_proposal_id.is_not(None),
        ))).scalars().first()

    if check("an amendment was raised", amendment is not None):
        items = amendment.line_items or []
        unit = str(items[0].get("unit") or "") if items else ""
        code = str(items[0].get("code") or "") if items else ""
        check("the amendment line carries the CLIENT's unit (F31 defect 2)",
              unit == "per rack", f"unit={unit!r} code={code!r}")
        check("no education word in the client-visible amendment line",
              not any(w in (unit + code).lower() for w in EDUCATION_WORDS),
              f"unit={unit!r} code={code!r}")
        check("the amendment is priced from the locked per-rack rate",
              amendment.total_amount == RACK_RATE * 30,
              f"{amendment.total_amount} vs {RACK_RATE * 30}")
        check("the amendment inherits the client's currency",
              amendment.currency == "USD", f"currency={amendment.currency}")

    # ── C. the Phase 7.1 surface writes no education vocabulary ──────────────
    print("\nC. document_engine.generate_text_artifact — the Phase 7.1 file")
    from app.engines import document_engine

    text = await document_engine.generate_text_artifact(
        org_id=org_id, dtype="closure_report",
        title="Hall 3 rack build-out — handover note",
        context={
            "client": "Meridian Colocation",
            "scope": "70 racks fitted out in Hall 3",
            "commissioning": "thermal validation signed off",
            "contact": "Anil Varghese, VP Infrastructure",
        },
    )
    leaked = [w for w in EDUCATION_WORDS if w in text.lower()]
    check("the artifact names no education vocabulary (F31 landmine)",
          not leaked, f"leaked={leaked}")
    check("the artifact is real text about this client",
          "meridian" in text.lower() and len(text) > 120,
          f"{len(text)} chars")
    print(f"\n  --- artifact opening ---\n  {text.strip()[:300]}\n  ---")

    await client.aclose()
    await engine.dispose()

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print("\n" + "=" * 68)
    for desc, ok, detail in CHECKS:
        if not ok:
            print(f"  FAILED: {desc}  ({detail})")
    print(f"{passed}/{len(CHECKS)} checks passed")
    sys.exit(0 if passed == len(CHECKS) else 1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        # §6g/§6i: a script that raises must not leave a live python.exe holding
        # the database. This ran on a throwaway DB, but the habit is the point.
        try:
            from app.database import engine as _engine
            asyncio.run(_engine.dispose())
        except Exception:  # noqa: BLE001
            pass
