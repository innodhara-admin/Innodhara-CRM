"""Task 1: the WhatsApp settings live in org_settings.whatsapp_integration."""
from __future__ import annotations

import pytest

from app.core.crypto import encrypt_secret
from app.services import whatsapp_settings

pytestmark = pytest.mark.asyncio


async def test_empty_is_off():
    cfg = whatsapp_settings.load({})
    assert cfg.provider == "off"
    assert not cfg.ready()
    assert whatsapp_settings.load(None).provider == "off"


async def test_legacy_meta_row_loads_as_meta():
    cfg = whatsapp_settings.load(
        {"access_token_enc": encrypt_secret("t"), "phone_number_id": "1"})
    assert cfg.provider == "meta"
    assert cfg.meta_token == "t" and cfg.meta_phone_number_id == "1"
    assert cfg.ready()


async def test_wati_needs_token():
    assert not whatsapp_settings.load({"provider": "wati"}).ready()
    cfg = whatsapp_settings.load(
        {"provider": "wati", "wati_token_enc": encrypt_secret("tok-test")})
    assert cfg.ready()
    assert cfg.wati_token == "tok-test"
    assert cfg.wati_host == "https://live-mt-server.wati.io"


async def test_bad_token_is_none():
    cfg = whatsapp_settings.load({"provider": "wati", "wati_token_enc": "garbage"})
    assert cfg.wati_token is None
    assert not cfg.ready()


async def test_kinds_off_and_defaults():
    cfg = whatsapp_settings.load({"provider": "wati", "kinds_off": ["escalation"]})
    assert cfg.country_code == "91"
    assert cfg.language == "en"
    assert cfg.staff_updates is False
    assert cfg.kinds_off == frozenset({"escalation"})


async def test_for_org_reads_the_settings_row(db):
    from tests.insights.builders import make_org
    from app.models.organisation import OrgSettings
    from sqlalchemy import select

    org = await make_org(db, name="WA Settings Org")
    row = (await db.execute(select(OrgSettings).where(OrgSettings.org_id == org.id))).scalar_one()
    row.whatsapp_integration = {"provider": "wati", "wati_token_enc": encrypt_secret("tok-test"),
                                "staff_updates": True}
    await db.flush()
    cfg = await whatsapp_settings.for_org(db, org.id)
    assert cfg.provider == "wati" and cfg.staff_updates and cfg.ready()
    assert (await whatsapp_settings.for_org(db, "no-such-org")).provider == "off"
