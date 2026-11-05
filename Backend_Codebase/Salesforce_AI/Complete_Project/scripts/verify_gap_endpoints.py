"""Verification of the 2026-07-17 mobile-gap endpoints (G1–G7) + renamed
lead state — deterministic (stub provider), fresh DB.

Covers, end to end through the real API:
  G7  /auth/me carries org branding (slug, colors) + designation
  G4  /auth/refresh issues a working fresh token
  G1  /devices register → upsert → unregister (push dormant without key)
  G2  /notifications?since= delta filter
  G5  offset pagination on /leads
  G6  admin reset-password → temp login → forced change → normal login
  G3  proposal upload-revision: the ORIGINAL pdf is accepted (total found),
      a TAMPERED pdf is refused, and status drops to draft for re-review
  NEW /leads state walk: active → execution_in_progress →
      client_execution_in_progress (the renamed generic state)

Run:  python scripts/verify_gap_endpoints.py
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "data" / "verify_gaps.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
os.environ["LLM_PROVIDER"] = "stub"
os.environ["EMAIL_MODE"] = "dry_run"
os.environ["WHATSAPP_MODE"] = "dry_run"
os.environ["CALENDAR_MODE"] = "off"

import httpx  # noqa: E402

PASSWORD = "Password@123"
CHECKS: list[tuple[str, bool, str]] = []


def check(desc: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((desc, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {desc}"
          + (f"  ({detail})" if detail and not ok else ""))
    return bool(ok)


class Api:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.tokens: dict[str, str] = {}

    async def login(self, email: str, password: str = PASSWORD):
        r = await self.client.post("/auth/login",
                                   json={"email": email, "password": password})
        r.raise_for_status()
        data = r.json()
        self.tokens[email] = data["access_token"]
        return data

    async def call(self, method: str, path: str, *, user: str,
                   json: dict | None = None, params: dict | None = None,
                   files: dict | None = None, token: str | None = None,
                   expect_error: bool = False):
        tok = token or self.tokens.get(user) or (await self.login(user))["access_token"]
        r = await self.client.request(
            method, path, json=json, params=params, files=files,
            headers={"Authorization": f"Bearer {tok}"},
        )
        if expect_error:
            return r.status_code, r.text
        if r.status_code >= 400:
            raise AssertionError(f"{method} {path} → {r.status_code}: {r.text[:300]}")
        return r.json()

    async def raw(self, path: str, *, user: str, params: dict | None = None) -> bytes:
        tok = self.tokens.get(user) or (await self.login(user))["access_token"]
        r = await self.client.get(path, params=params,
                                  headers={"Authorization": f"Bearer {tok}"})
        r.raise_for_status()
        return r.content


def make_tampered_pdf() -> bytes:
    """A well-formed PDF whose total is NOT the locked 126,000."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(72, 760, "Android Bootcamp Proposal for Swami Vivekananda School")
    c.drawString(72, 730, "Special one-time offer, hand edited.")
    c.drawString(72, 700, "Grand total: 999,999 INR")
    c.save()
    return buf.getvalue()


async def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    for side in (".db-wal", ".db-shm"):
        p = Path(str(DB_PATH).replace(".db", side))
        if p.exists():
            p.unlink()

    from app.database import init_db
    from app.engines import sync_engine
    from app.jobs import register_handlers
    from app.main import app
    from scripts.seed_workflows import seed

    await init_db()
    register_handlers()
    sync_engine.register()
    await seed()

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                               base_url="http://test/api/v1", timeout=120)
    api = Api(client)
    rahul, ananya, priya = ("rahul@yuvipep.com", "ananya@yuvipep.com",
                            "priya@yuvipep.com")

    # ── G7: branding on /auth/me ─────────────────────────────────────────────
    print("G7 — /auth/me carries the org's identity")
    me = await api.call("GET", "/auth/me", user=rahul)
    check("org slug present", me.get("org_slug") == "yuvipep", str(me.get("org_slug")))
    check("brand colors present", isinstance(me.get("org_brand_colors"), dict),
          str(me.get("org_brand_colors")))
    check("designation/department fields exposed",
          "designation" in me and "department" in me)

    # ── G4: refresh ──────────────────────────────────────────────────────────
    print("G4 — token refresh")
    refreshed = await api.call("POST", "/auth/refresh", user=rahul)
    new_tok = refreshed["access_token"]
    me2 = await api.call("GET", "/auth/me", user=rahul, token=new_tok)
    check("refreshed token works and names the same user",
          bool(new_tok) and me2["user_id"] == me["user_id"])

    # ── G1: device registration (push dormant without Firebase key) ─────────
    print("G1 — device push registration")
    fake = "fake-fcm-token-" + "x" * 40
    reg = await api.call("POST", "/devices", user=rahul,
                         json={"fcm_token": fake, "app_version": "0.0-verify"})
    check("registered; push honestly reported dormant",
          reg["registered"] is True and reg["push_enabled"] is False, str(reg))
    reg2 = await api.call("POST", "/devices", user=rahul,
                          json={"fcm_token": fake, "app_version": "0.0-verify2"})
    check("same token re-registers as upsert (no duplicate)", reg2["registered"] is True)
    unreg = await api.call("POST", "/devices/unregister", user=rahul,
                           json={"fcm_token": fake})
    check("unregister works (logout path)", unreg["unregistered"] is True)

    # ── G2 + G5: delta polling & pagination ──────────────────────────────────
    print("G2/G5 — notifications since= and leads offset=")
    all_notifs = await api.call("GET", "/notifications", user=rahul)
    future = await api.call("GET", "/notifications", user=rahul,
                            params={"since": "2030-01-01T00:00:00"})
    check("since= filters (future cutoff yields empty)",
          isinstance(all_notifs, list) and future == [], f"{len(all_notifs)}/{len(future)}")
    bad = await api.call("GET", "/notifications", user=rahul,
                         params={"since": "not-a-date"}, expect_error=True)
    check("bad since= rejected with a clear message", bad[0] >= 400 and "ISO" in bad[1])
    page1 = await api.call("GET", "/leads", user=rahul, params={"limit": 2, "offset": 0})
    page2 = await api.call("GET", "/leads", user=rahul, params={"limit": 2, "offset": 2})
    ids1, ids2 = {l["id"] for l in page1}, {l["id"] for l in page2}
    check("leads pages don't overlap", len(page1) == 2 and not (ids1 & ids2))

    # ── G6: admin password reset ─────────────────────────────────────────────
    print("G6 — forgotten password: admin issues a temp password")
    staff = await api.call("GET", "/admin/users", user=ananya)
    shyam = next(u for u in staff if u["email"].startswith("shyam"))
    reset = await api.call("POST", f"/admin/users/{shyam['id']}/reset-password",
                           user=ananya)
    temp = reset["temp_password"]
    check("temp password issued once", reset["reset"] is True and len(temp) >= 8)
    shyam_login = await api.login(shyam["email"], temp)
    check("temp login forces a change", shyam_login["must_change_password"] is True)
    await api.call("POST", "/auth/change-password", user=shyam["email"],
                   json={"current_password": temp, "new_password": PASSWORD})
    shyam_login2 = await api.login(shyam["email"], PASSWORD)
    check("changed password logs in normally",
          shyam_login2["must_change_password"] is False)

    # ── Renamed state walk ───────────────────────────────────────────────────
    print("RENAME — the generic on-site state works through the API")
    lead = await api.call("POST", "/leads", user=rahul, json={
        "name": "Meridian Logistics Pvt Ltd", "city": "Pune", "source": "expo",
    })
    # `POST /leads` creates in `cold_calling` -- a lead is a name and a phone
    # number until somebody has actually called. `open` stands in for that call.
    # Without it this walk raises on the first move and the whole script dies
    # before G3 below ever runs, which is how G3 quietly stopped being verified.
    check("a new lead starts in cold calling", lead["state"] == "cold_calling",
          lead["state"])
    for target in ("open", "active", "execution_in_progress",
                   "client_execution_in_progress"):
        await api.call("PATCH", f"/leads/{lead['id']}/state", user=rahul,
                       json={"state": target, "reason": "verification walk"})
    detail = await api.call("GET", f"/leads/{lead['id']}", user=rahul)
    check("lead reached client_execution_in_progress",
          detail["state"] == "client_execution_in_progress", detail["state"])
    old = await api.call("PATCH", f"/leads/{lead['id']}/state", user=rahul,
                         json={"state": "school_execution_in_progress"},
                         expect_error=True)
    check("the OLD state name is no longer accepted", old[0] >= 400)

    # ── G3: manual proposal revision upload ──────────────────────────────────
    print("G3 — manual PDF re-submit: honest file wins, tampered file refused")
    leads = await api.call("GET", "/leads", user=priya, params={"q": "Swami"})
    svs_id = leads[0]["id"]
    programs = await api.call("GET", "/admin/programs", user=ananya)
    android = next(p for p in programs if p["code"] == "ANDROID_BC")
    proposal = await api.call("POST", "/proposals", user=priya, json={
        "lead_id": svs_id, "program_id": android["id"],
        "context_summary": "7-day bootcamp, classes 5-9, ~400 students",
        "quantities": {"per_student": 400, "materials": 1},
    })
    check("proposal priced from the table (126,000 — never typed)",
          proposal["total_amount"] == 126000, str(proposal["total_amount"]))
    original_pdf = await api.raw(f"/proposals/{proposal['id']}/download", user=priya)
    check("rendered PDF downloads", original_pdf[:4] == b"%PDF", str(original_pdf[:8]))

    status, text = await api.call(
        "POST", f"/proposals/{proposal['id']}/upload-revision", user=priya,
        files={"file": ("edited.pdf", make_tampered_pdf(), "application/pdf")},
        expect_error=True,
    )
    check("tampered total REFUSED with the pricing rule spelled out",
          status >= 400 and "locked total" in text, f"{status}: {text[:120]}")

    upload = await api.call(
        "POST", f"/proposals/{proposal['id']}/upload-revision", user=priya,
        files={"file": ("edited.pdf", original_pdf, "application/pdf")},
    )
    check("honest edited file accepted, total machine-verified",
          upload["uploaded"] is True and upload["total_verified"] is True, str(upload))
    check("manual edit forces re-review (status back to draft)",
          upload["status"] == "draft", upload["status"])
    after = await api.call("GET", f"/proposals/{proposal['id']}", user=priya)
    check("revision recorded in the proposal's history",
          any("Manually edited file" in (r.get("instruction") or "")
              for r in after["revisions"]), str(after["revisions"][:2]))

    await client.aclose()
    failed = [c for c in CHECKS if not c[1]]
    print(f"\n{'='*68}\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed"
          + (f" — {len(failed)} FAILED" if failed else ""))
    for desc, _, detail in failed:
        print(f"  FAILED: {desc}  ({detail})")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
