"""The loader that puts the 11 templates into one organisation (plan Task 10)."""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.email_template import EmailTemplate
from app.models.program import Program
from tests.conftest import auth, create_org
from tests.email.helpers import API, FIXTURES
from tests.email.test_word_files import MANIFEST

# Loaded from its path, as tests/insights/test_demo_seed.py loads its script:
# scripts/ is not a package.
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "load_email_templates.py"
_spec = importlib.util.spec_from_file_location("load_email_templates", _SCRIPT)
loader = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(loader)


async def _org(client, super_token) -> dict:
    tag = uuid.uuid4().hex[:6]
    org = await create_org(client, super_token, name=f"Loader Org {tag}",
                           slug=f"loader-{tag}", domain=f"loader{tag}.example")
    for code, name in (("IBC", "IBC Program"), ("YFIL", "Futuristic Innovation Lab")):
        resp = await client.post(f"{API}/admin/programs", headers=auth(org["admin_token"]),
                                 json={"name": name, "code": code, "description": "d"})
        assert resp.status_code == 200, resp.text
    return org


async def _counts(org_id: str) -> tuple[int, int]:
    async with SessionLocal() as db:
        templates = (await db.execute(select(func.count(EmailTemplate.id)).where(
            EmailTemplate.org_id == org_id))).scalar_one()
        programs = (await db.execute(select(func.count(Program.id)).where(
            Program.org_id == org_id))).scalar_one()
    return templates, programs


def test_manifest_matches_the_tested_files():
    assert loader.MANIFEST == MANIFEST


async def test_dry_run_changes_nothing(client, super_token):
    org = await _org(client, super_token)
    before = await _counts(org["id"])
    lines = await loader.run(org["name"], FIXTURES, dry_run=True)
    assert len(lines) == 11
    assert await _counts(org["id"]) == before


async def test_load_creates_two_products_and_eleven_templates(client, super_token):
    org = await _org(client, super_token)
    lines = await loader.run(org["name"], FIXTURES, dry_run=False)
    assert [line["status"] for line in lines] == ["published"] * 11
    templates, programs = await _counts(org["id"])
    assert (templates, programs) == (11, 4)
    async with SessionLocal() as db:
        codes = set((await db.execute(select(Program.code).where(
            Program.org_id == org["id"]))).scalars().all())
        rows = (await db.execute(select(EmailTemplate).where(
            EmailTemplate.org_id == org["id"]))).scalars().all()
    assert {"KBKV", "IFEST"} <= codes
    by_name = {r.name: r for r in rows}
    assert by_name["IBC MoU cover letter"].built_document == "mou"
    assert by_name["Onboarding"].category == "onboarding"
    assert by_name["Final follow-up"].when_to_use.startswith("No response")


async def test_second_run_is_a_no_op(client, super_token):
    org = await _org(client, super_token)
    await loader.run(org["name"], FIXTURES, dry_run=False)
    lines = await loader.run(org["name"], FIXTURES, dry_run=False)
    assert [line["status"] for line in lines] == ["unchanged"] * 11
    assert await _counts(org["id"]) == (11, 4)


async def test_unknown_org_is_refused(client):
    assert await loader._main(["--org-name", "No Such Org", "--dir", str(FIXTURES)]) == 1


async def test_refuses_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert await loader._main(["--org-name", "x", "--dir", str(FIXTURES)]) == 2
