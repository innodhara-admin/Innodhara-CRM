"""Send one WhatsApp template through the organisation's provider (4 Nov 2026).

Wati (V3 API) and the Meta WhatsApp Cloud API, behind one call. Nothing leaves
unless WHATSAPP_MODE=cloud_api AND the organisation's provider has its
credentials; otherwise the request is written to the outbox folder as before
(dry run), without the token.

Errors: a network failure, 429 or 5xx raises ExternalServiceError so the job
queue retries; any other refusal comes back as SendResult(ok=False) and is not
retried (a wrong number or an unapproved template will not fix itself).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
from app.core.exceptions import ExternalServiceError
from app.models.base import utcnow
from app.services import storage
from app.services.whatsapp_settings import WhatsAppConfig
from app.services.whatsapp_templates import DOCUMENT_VALUE, TEMPLATES, Template
from app.services.whatsapp_text import clean_value, fold

_GRAPH_URL = "https://graph.facebook.com/v20.0"
_TIMEOUT = 30


@dataclass
class SendResult:
    ok: bool
    provider_id: str
    error: str | None = None


def _template(name: str) -> Template:
    try:
        return TEMPLATES[name]
    except KeyError:
        raise ValueError(f"Unknown WhatsApp template '{name}'") from None


def _prepared(t: Template, values: dict[str, str]) -> dict[str, str]:
    missing = [v for v in t.values if v not in values]
    if missing:
        raise ValueError(f"Template '{t.name}' needs {', '.join(missing)}")
    cleaned = {v: clean_value(values[v]) for v in t.values}
    longest_first = tuple(sorted(cleaned, key=lambda v: len(cleaned[v]), reverse=True))
    return fold(cleaned, fixed_len=t.fixed_len, shrink_order=longest_first)


async def _post(url: str, *, token: str, payload: dict[str, Any]) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                url, json=payload, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise ExternalServiceError(f"WhatsApp request failed: {exc}") from exc
    if resp.status_code == 429 or resp.status_code >= 500:
        raise ExternalServiceError(
            f"WhatsApp provider busy or unavailable ({resp.status_code})")
    return resp


async def send_template(
    cfg: WhatsAppConfig, *, org_id: str, to: str, template: str,
    values: dict[str, str], document_url: str | None = None,
    document_name: str | None = None, local_id: str,
) -> SendResult:
    t = _template(template)
    if t.document and not document_url:
        raise ValueError(f"Template '{t.name}' carries a document and none was given")
    filled = _prepared(t, values)

    if get_settings().whatsapp_mode != "cloud_api" or not cfg.ready():
        record = {"provider": cfg.provider, "to": to, "template": t.name,
                  "values": filled, "document_url": document_url}
        rel = storage.save_text(
            org_id, storage.CATEGORY_OUTBOX, f"whatsapp_{to}.json",
            json.dumps(record, indent=2, ensure_ascii=False))
        return SendResult(True, f"dry_run:{rel}")

    if cfg.provider == "wati":
        return await _send_wati(cfg, t, to, filled, document_url, local_id)
    return await _send_meta(cfg, t, to, filled, document_url, document_name)


async def _send_wati(cfg: WhatsAppConfig, t: Template, to: str, filled: dict[str, str],
                     document_url: str | None, local_id: str) -> SendResult:
    params = [{"name": k, "value": v} for k, v in filled.items()]
    if document_url:
        params.append({"name": DOCUMENT_VALUE, "value": document_url})
    payload: dict[str, Any] = {
        "template_name": t.name,
        "broadcast_name": f"crm-{t.name}-{utcnow():%Y%m%d}",
        "recipients": [{"target": to, "local_message_id": local_id,
                        "custom_params": params}],
    }
    if cfg.wati_channel:
        payload["channel"] = cfg.wati_channel
    resp = await _post(f"{cfg.wati_host}/api/ext/v3/messageTemplates/send",
                       token=cfg.wati_token or "", payload=payload)
    if resp.status_code >= 400:
        return SendResult(False, "", f"Wati refused ({resp.status_code}): {resp.text[:400]}")
    try:
        data = resp.json()
    except ValueError:
        return SendResult(False, "", f"Wati answered something unreadable: {resp.text[:200]}")
    if not data.get("success"):
        return SendResult(False, "", f"Wati refused: {data.get('error') or 'no reason given'}")
    mine = [r for r in data.get("recipients") or []
            if r.get("local_message_id") in (local_id, None)]
    if not mine:
        return SendResult(False, "", "Wati did not accept this number")
    errors = mine[0].get("errors") or []
    if errors:
        return SendResult(False, "", "Wati refused: " + "; ".join(map(str, errors))[:400])
    return SendResult(True, local_id)


async def _send_meta(cfg: WhatsAppConfig, t: Template, to: str, filled: dict[str, str],
                     document_url: str | None, document_name: str | None) -> SendResult:
    components: list[dict[str, Any]] = []
    if document_url:
        doc: dict[str, Any] = {"link": document_url}
        if document_name:
            doc["filename"] = document_name
        components.append({"type": "header", "parameters": [
            {"type": "document", "document": doc}]})
    components.append({"type": "body", "parameters": [
        {"type": "text", "text": filled[v]} for v in t.values]})
    payload = {
        "messaging_product": "whatsapp", "to": to, "type": "template",
        "template": {"name": t.name, "language": {"code": cfg.language},
                     "components": components},
    }
    resp = await _post(f"{_GRAPH_URL}/{cfg.meta_phone_number_id}/messages",
                       token=cfg.meta_token or "", payload=payload)
    if resp.status_code >= 400:
        return SendResult(False, "", f"WhatsApp send rejected: {resp.text[:400]}")
    try:
        return SendResult(True, resp.json()["messages"][0]["id"])
    except (KeyError, IndexError, ValueError):
        return SendResult(True, "whatsapp:unknown")


_LIST_KEYS = ("messageTemplates", "message_templates", "items", "data", "templates", "result")


async def list_templates(cfg: WhatsAppConfig) -> list[dict[str, Any]]:
    """The provider's templates: name, status and the value names in the body.
    Only Wati can be asked; Meta answers [] (checked in Meta Business Manager)."""
    if cfg.provider != "wati" or not cfg.ready():
        return []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{cfg.wati_host}/api/ext/v3/messageTemplates",
                params={"pageSize": 200},
                headers={"Authorization": f"Bearer {cfg.wati_token}"})
    except httpx.HTTPError as exc:
        raise ExternalServiceError(f"Wati request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise ExternalServiceError(f"Wati refused the template list ({resp.status_code})")
    data = resp.json()
    rows = data if isinstance(data, list) else next(
        (data[k] for k in _LIST_KEYS if isinstance(data.get(k), list)), [])
    out = []
    for row in rows:
        # Live V3 (4 Nov 2026): the body is numbered ({{1}}) and the value
        # names a send must use are in custom_params; older shapes name them
        # in the body.
        named = [p.get("name") for p in row.get("custom_params") or [] if p.get("name")]
        body = row.get("body") or row.get("bodyOriginal") or row.get("body_original") or ""
        out.append({
            "name": row.get("elementName") or row.get("element_name") or row.get("name"),
            "status": row.get("status"),
            "params": named or re.findall(r"\{\{(\w+)\}\}", body if isinstance(body, str) else ""),
        })
    return out
