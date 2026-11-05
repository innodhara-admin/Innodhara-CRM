"""Task 3: one template send, through Wati or Meta, or into the outbox."""
from __future__ import annotations

import json

import httpx
import pytest

from app.core.crypto import encrypt_secret
from app.core.exceptions import ExternalServiceError
from app.services import storage, whatsapp_providers
from app.services.whatsapp_settings import load
from app.services.whatsapp_templates import TEMPLATES

pytestmark = pytest.mark.asyncio


def _wati(channel=None):
    raw = {"provider": "wati", "wati_token_enc": encrypt_secret("tok-test")}
    if channel:
        raw["wati_channel"] = channel
    return load(raw)


def _meta():
    return load({"provider": "meta", "access_token_enc": encrypt_secret("tok-test"),
                 "phone_number_id": "555"})


def _ok_wati(request):
    body = json.loads(request.content)
    rid = body["recipients"][0]["local_message_id"]
    return httpx.Response(200, json={"success": True, "broadcast_id": "b1", "recipients": [
        {"local_message_id": rid, "phone_number": "919310524629", "errors": None}]})


def _params(request):
    recipient = json.loads(request.content)["recipients"][0]
    return {p["name"]: p["value"] for p in recipient["custom_params"]}


async def test_every_template_names_its_values_and_fixed_text():
    assert set(TEMPLATES) == {"staff_update", "staff_meeting_summary", "staff_daily_brief",
                              "client_proposal", "client_message", "test_message"}
    t = TEMPLATES["staff_update"]
    assert t.values == ("name", "title", "detail")
    assert t.fixed_len == len(t.body) - sum(len("{{%s}}" % v) for v in t.values)
    assert TEMPLATES["client_proposal"].document
    assert not TEMPLATES["test_message"].document


async def test_wati_request_shape(fake_http, sending_for_real):
    seen = fake_http(_ok_wati)
    result = await whatsapp_providers.send_template(
        _wati(channel="917975779676"), org_id="o1", to="919310524629",
        template="client_proposal",
        values={"contact_name": "Ravi", "programme": "IBC\nProposal", "sender_name": "Ek"},
        document_url="https://x.example/doc.pdf", local_id="L1")
    assert result.ok and result.provider_id == "L1"
    request = seen[0]
    assert str(request.url) == "https://live-mt-server.wati.io/api/ext/v3/messageTemplates/send"
    assert request.headers["authorization"] == "Bearer tok-test"
    body = json.loads(request.content)
    assert body["template_name"] == "client_proposal"
    assert body["channel"] == "917975779676"
    assert body["broadcast_name"].startswith("crm-client_proposal-")
    recipient = body["recipients"][0]
    assert recipient["target"] == "919310524629" and recipient["local_message_id"] == "L1"
    assert _params(request) == {"contact_name": "Ravi", "programme": "IBC Proposal",
                                "sender_name": "Ek",
                                "document_url": "https://x.example/doc.pdf"}


async def test_wati_without_channel_or_document(fake_http, sending_for_real):
    seen = fake_http(_ok_wati)
    await whatsapp_providers.send_template(
        _wati(), org_id="o1", to="919310524629", template="test_message",
        values={"name": "Ek"}, local_id="L2")
    assert "channel" not in json.loads(seen[0].content)
    assert list(_params(seen[0])) == ["name"]


async def test_wati_recipient_error_is_not_ok(fake_http, sending_for_real):
    fake_http(lambda r: httpx.Response(200, json={"success": True, "recipients": [
        {"local_message_id": "L3", "errors": ["Invalid WhatsApp number"]}]}))
    result = await whatsapp_providers.send_template(
        _wati(), org_id="o1", to="919310524629", template="test_message",
        values={"name": "Ek"}, local_id="L3")
    assert not result.ok and "Invalid WhatsApp number" in result.error


async def test_wati_success_false_is_not_ok(fake_http, sending_for_real):
    fake_http(lambda r: httpx.Response(200, json={"success": False,
                                                  "error": "Template not approved"}))
    result = await whatsapp_providers.send_template(
        _wati(), org_id="o1", to="919310524629", template="test_message",
        values={"name": "Ek"}, local_id="L4")
    assert not result.ok and "Template not approved" in result.error


async def test_wati_5xx_raises(fake_http, sending_for_real):
    fake_http(lambda r: httpx.Response(503, text="down"))
    with pytest.raises(ExternalServiceError):
        await whatsapp_providers.send_template(
            _wati(), org_id="o1", to="919310524629", template="test_message",
            values={"name": "Ek"}, local_id="L5")


async def test_meta_template_shape(fake_http, sending_for_real):
    seen = fake_http(lambda r: httpx.Response(200, json={"messages": [{"id": "wamid.X"}]}))
    result = await whatsapp_providers.send_template(
        _meta(), org_id="o1", to="919310524629", template="client_proposal",
        values={"sender_name": "Ek", "contact_name": "Ravi", "programme": "IBC"},
        document_url="https://x.example/doc.pdf", document_name="IBC.pdf", local_id="L6")
    assert result.ok and result.provider_id == "wamid.X"
    assert str(seen[0].url) == "https://graph.facebook.com/v20.0/555/messages"
    body = json.loads(seen[0].content)
    assert body["type"] == "template" and body["to"] == "919310524629"
    tpl = body["template"]
    assert tpl["name"] == "client_proposal" and tpl["language"] == {"code": "en"}
    header, main = tpl["components"]
    assert header == {"type": "header", "parameters": [{"type": "document", "document": {
        "link": "https://x.example/doc.pdf", "filename": "IBC.pdf"}}]}
    assert [p["text"] for p in main["parameters"]] == ["Ravi", "IBC", "Ek"]


async def test_dry_run_writes_outbox_without_token(fake_http):
    seen = fake_http(lambda r: httpx.Response(500))
    result = await whatsapp_providers.send_template(
        _wati(), org_id="o-dry", to="919310524629", template="test_message",
        values={"name": "Ek"}, local_id="L7")
    assert result.ok and result.provider_id.startswith("dry_run:")
    assert seen == []
    saved = storage.read_bytes("o-dry", result.provider_id[len("dry_run:"):]).decode()
    assert "tok-test" not in saved and "test_message" in saved


async def test_unknown_template_or_missing_document_raises(sending_for_real):
    with pytest.raises(ValueError):
        await whatsapp_providers.send_template(
            _wati(), org_id="o1", to="1", template="nope", values={}, local_id="L8")
    with pytest.raises(ValueError):
        await whatsapp_providers.send_template(
            _wati(), org_id="o1", to="919310524629", template="client_proposal",
            values={"contact_name": "a", "programme": "b", "sender_name": "c"},
            local_id="L9")


async def test_long_values_are_folded(fake_http, sending_for_real):
    seen = fake_http(_ok_wati)
    await whatsapp_providers.send_template(
        _wati(), org_id="o1", to="919310524629", template="staff_update",
        values={"name": "Ek", "title": "T", "detail": "d" * 3000}, local_id="L10")
    params = _params(seen[0])
    assert TEMPLATES["staff_update"].fixed_len + sum(len(v) for v in params.values()) <= 1024


async def test_list_templates_reads_wati(fake_http, sending_for_real):
    seen = fake_http(lambda r: httpx.Response(200, json={"messageTemplates": [
        {"elementName": "test_message", "status": "APPROVED",
         "body": "Hi {{name}}, this is a test"}]}))
    rows = await whatsapp_providers.list_templates(_wati())
    assert str(seen[0].url).startswith(
        "https://live-mt-server.wati.io/api/ext/v3/messageTemplates")
    assert rows == [{"name": "test_message", "status": "APPROVED", "params": ["name"]}]
    assert await whatsapp_providers.list_templates(_meta()) == []


async def test_no_body_starts_or_ends_with_a_value():
    """WhatsApp rejects a template whose body starts or ends with a variable."""
    for t in TEMPLATES.values():
        assert not t.body.startswith("{{"), t.name
        assert not t.body.rstrip(" .").endswith("}}"), t.name


async def test_list_templates_reads_the_real_v3_shape(fake_http, sending_for_real):
    """Seen live 4 Nov 2026: the list is under "templates", status is lower
    case, the body is numbered ({{1}}) and the value NAMES are in custom_params."""
    fake_http(lambda r: httpx.Response(200, json={"templates": [
        {"name": "test_message", "status": "approved", "body": "Hi {{1}}, this is a test",
         "custom_params": [{"name": "name", "value": "Asha"}]}],
        "page_number": 1, "page_size": 100, "total": 1}))
    rows = await whatsapp_providers.list_templates(_wati())
    assert rows == [{"name": "test_message", "status": "approved", "params": ["name"]}]
