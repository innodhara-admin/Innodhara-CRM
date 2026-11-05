"""Business-card reading (Vision/OCR) via the model layer.

Low-confidence scans are flagged for human review, never silently guessed
(doc §12 "Low confidence is flagged, not hidden").
"""
from __future__ import annotations

import base64
from dataclasses import dataclass

from app.ai.llm import TIER_FAST, extract_json, get_model_layer
from app.core.exceptions import ExternalServiceError

_PROMPT = (
    "Read this business card photo. Extract the person's details as JSON:\n"
    '  "name": full name,\n'
    '  "title": job title/designation,\n'
    '  "email": email address,\n'
    '  "phone": phone number with country code if visible,\n'
    '  "organisation": company or organisation name,\n'
    '  "confidence": 0.0-1.0 — how clearly you could read the card.\n'
    "Use null for anything not on the card. Never invent values. "
    "Return ONLY the JSON object."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "nullable": True},
        "title": {"type": "string", "nullable": True},
        "email": {"type": "string", "nullable": True},
        "phone": {"type": "string", "nullable": True},
        "organisation": {"type": "string", "nullable": True},
        "confidence": {"type": "number"},
    },
    "required": ["confidence"],
}


@dataclass
class CardScanResult:
    name: str | None
    title: str | None
    email: str | None
    phone: str | None
    organisation: str | None
    confidence: float

    @property
    def needs_review(self) -> bool:
        return self.confidence < 0.7 or not self.name


async def read_business_card(
    image: bytes,
    mime: str,
    *,
    org_id: str | None = None,
    user_id: str | None = None,
) -> CardScanResult:
    if not mime.startswith("image/"):
        mime = "image/jpeg"
    response = await get_model_layer().generate(
        purpose="vision.business_card",
        tier=TIER_FAST,
        org_id=org_id,
        user_id=user_id,
        messages=[
            {
                "role": "user",
                "content": [
                    {"inlineData": {"mimeType": mime, "data": base64.b64encode(image).decode()}},
                    {"text": _PROMPT},
                ],
            }
        ],
        json_schema=_SCHEMA,
        temperature=0.1,
        max_tokens=2048,
    )
    try:
        data = extract_json(response.text)
    except Exception as exc:  # noqa: BLE001
        raise ExternalServiceError(f"Could not parse card scan output: {exc}") from exc

    def _clean(value: object) -> str | None:
        if isinstance(value, str) and value.strip() and value.strip().lower() != "null":
            return value.strip()
        return None

    return CardScanResult(
        name=_clean(data.get("name")),
        title=_clean(data.get("title")),
        email=_clean(data.get("email")),
        phone=_clean(data.get("phone")),
        organisation=_clean(data.get("organisation")),
        confidence=float(data.get("confidence", 0.0) or 0.0),
    )
