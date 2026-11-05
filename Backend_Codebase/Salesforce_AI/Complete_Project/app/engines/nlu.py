"""Natural-language understanding used by the engines.

Two paths, one contract:
- LLM path (when a provider key is configured): structured-output calls.
- Deterministic path (always available): pattern/keyword understanding.

The deterministic path is what makes the whole platform dry-runnable and
reproducible — it is generic (cue words, amount/date grammars), never
scenario-specific. Confidence is reported honestly; engines route low
confidence to a human instead of acting (rule 3 of the design).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from app.models.base import utcnow
from app.config import get_settings

logger = logging.getLogger(__name__)


def llm_available() -> bool:
    s = get_settings()
    if s.llm_provider == "stub":
        return False
    if s.llm_provider == "claude":
        return bool(s.anthropic_api_key)
    if s.llm_provider == "openrouter":
        return bool(s.openrouter_api_key)
    return bool(s.gemini_api_key)


# ─────────────────────────────────────────────────────────────────────────────
# Amount / date grammars (generic, Indian-English aware)
# ─────────────────────────────────────────────────────────────────────────────

_WORD_NUMS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "half": 0.5,
}

_MONTHS = {
    m.lower(): i + 1
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"]
    )
}
_MONTHS.update({m[:3].lower(): i for m, i in [(k.capitalize(), v) for k, v in _MONTHS.items()]})


def parse_amounts(text: str) -> list[float]:
    """Find money amounts: ₹1,26,000 / Rs 45,000 / 1.26 lakh / one lakh / 2 crore."""
    amounts: list[float] = []
    t = text.lower()
    # lakh / crore forms (digit or word multiplier)
    for m in re.finditer(
        r"(?:₹|rs\.?|inr)?\s*([\d.]+|" + "|".join(_WORD_NUMS) + r")\s*(lakh|lakhs|lac|crore|crores)",
        t,
    ):
        raw = m.group(1)
        num = _WORD_NUMS.get(raw, None)
        if num is None:
            try:
                num = float(raw)
            except ValueError:
                continue
        mult = 10_000_000 if m.group(2).startswith("crore") else 100_000
        amounts.append(num * mult)
    # plain currency figures: ₹1,26,000 / Rs. 45,000 / INR 55000
    for m in re.finditer(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)", t):
        try:
            amounts.append(float(m.group(1).replace(",", "")))
        except ValueError:
            continue
    return amounts


def parse_dates(text: str, *, base: datetime | None = None) -> list[datetime]:
    """Find dates: '3 December', 'Dec 3', '2026-12-03', 'tomorrow', 'next week'."""
    base = base or utcnow()
    found: list[datetime] = []
    t = text.lower()
    for m in re.finditer(r"(\d{4})-(\d{2})-(\d{2})", t):
        try:
            found.append(datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            continue
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(_MONTHS) + r")\w*", t):
        month = _MONTHS.get(m.group(2))
        if month:
            year = base.year + (1 if month < base.month - 1 else 0)
            try:
                found.append(datetime(year, month, int(m.group(1))))
            except ValueError:
                continue
    for m in re.finditer(r"\b(" + "|".join(_MONTHS) + r")\w*\s+(\d{1,2})(?:st|nd|rd|th)?\b", t):
        month = _MONTHS.get(m.group(1))
        if month:
            year = base.year + (1 if month < base.month - 1 else 0)
            try:
                found.append(datetime(year, month, int(m.group(2))))
            except ValueError:
                continue
    if "tomorrow" in t:
        found.append(base + timedelta(days=1))
    if "next week" in t:
        found.append(base + timedelta(days=7))
    if "day after tomorrow" in t:
        found.append(base + timedelta(days=2))
    # de-duplicate, keep order
    seen: set[str] = set()
    unique = []
    for d in found:
        k = d.strftime("%Y-%m-%d")
        if k not in seen:
            seen.add(k)
            unique.append(d)
    return unique


_ABBREVIATIONS = r"(?:Mr|Mrs|Ms|Dr|Prof|St|No|vs|etc|Rs|approx)\."


def split_sentences(text: str) -> list[str]:
    """Sentence split that does not break after common abbreviations
    ('Meeting with Mr. Singhania' is ONE sentence)."""
    guarded = re.sub(_ABBREVIATIONS, lambda m: m.group(0).replace(".", "\x00"), text.strip())
    parts = re.split(r"(?<=[.!?])\s+", guarded)
    return [p.replace("\x00", ".") for p in parts if p.strip()]


def first_sentence(text: str, limit: int = 180) -> str:
    s = split_sentences(text)
    out = s[0] if s else text.strip()
    return out[:limit]


# ─────────────────────────────────────────────────────────────────────────────
# Inbound message classification
# ─────────────────────────────────────────────────────────────────────────────

_INTENT_CUES: dict[str, list[str]] = {
    "complaint": [
        "late", "not working", "disappointed", "unacceptable", "complaint",
        "problem", "issue", "fix this", "no working", "didn't show", "did not show",
        "poor", "unhappy", "angry", "worst",
    ],
    "approval": [
        "approved", "go ahead", "agreed", "let's proceed", "lets proceed",
        "proceed", "confirmed", "confirm the", "yes please", "sounds good",
        "we accept", "accepted", "deal", "sign", "okay to", "ok to", "green light",
    ],
    "rejection": [
        "not interested", "cancel", "we decline", "declined", "won't proceed",
        "will not proceed", "drop this", "no longer", "not this year",
        "was never signed", "we dispute", "disagree",
    ],
    "payment_info": [
        "cheque", "payment", "paid", "transfer", "upi", "invoice", "neft",
        "collect", "amount credited", "instalment", "installment",
    ],
    "scheduling": [
        "reschedule", "can we meet", "book a", "available on", "slot",
        "schedule a call", "meeting on", "visit on", "come on",
    ],
    "change_request": [
        "can you do it in", "instead", "change", "reduce", "increase", "add ",
        "include", "remove", "simplify", "postpone", "prepone", "shift",
        "move the", "make it", "discount", "above our budget", "too advanced",
        "compress", "extend", "start on", "drop classes",
    ],
    "acknowledgement": [
        "thank you", "thanks", "noted", "received", "got it", "perfect",
        "great, ", "wonderful",
    ],
    "question": ["?", "will you", "does the", "can you tell", "what is", "how many", "kotlin"],
}

_CHANGE_TYPE_CUES: dict[str, list[str]] = {
    "price": [
        "budget", "price", "cost", "discount", "lakh", "₹", "rs ", "rs.",
        "cheaper", "expensive", "amount", "instalment", "installment", "free",
    ],
    "date": [
        "date", "december", "january", "february", "march", "april", "may",
        "june", "july", "august", "september", "october", "november",
        "postpone", "prepone", "start on", "instead of", "shift", "tomorrow",
        "next week", "inspection", "reschedule",
    ],
    "scope": [
        "add classes", "include classes", "also include", "more students",
        "another", "as well", "drop classes", "expand", "reduce scope",
        "add on", "additionally cover",
    ],
    "content": [
        "syllabus", "content", "too advanced", "simplify", "session on",
        "curriculum", "topic", "module", "material",
    ],
}

_NEGATIVE_CUES = _INTENT_CUES["complaint"] + ["sorry to say", "regret", "concern"]
_POSITIVE_CUES = [
    "thank", "great", "wonderful", "delighted", "excellent", "happy",
    "looks good", "perfect", "love", "impressed", "agreed",
]


def _cue_hit(t: str, cue: str) -> bool:
    """Cue match with word boundaries — 'add on' must not fire inside
    'add one session'. Cues without word characters (e.g. '?') fall back to
    plain substring."""
    if not re.search(r"\w", cue):
        return cue in t
    prefix = r"\b" if cue[0].isalnum() else ""
    # Allow plain inflections (change→changes/changed/changing) but never a
    # bleed into a different word (on→one).
    suffix = r"(?:s|es|d|ed|ing)?\b" if cue[-1].isalnum() else ""
    return re.search(prefix + re.escape(cue) + suffix, t) is not None


def _score(text: str, cues: list[str]) -> int:
    t = text.lower()
    return sum(1 for c in cues if _cue_hit(t, c))


def classify_inbound_heuristic(subject: str | None, body: str) -> dict[str, Any]:
    """Deterministic intent/sentiment/points classification."""
    text = f"{subject or ''}\n{body}"
    t = text.lower()

    scores = {intent: _score(text, cues) for intent, cues in _INTENT_CUES.items()}
    # Complaint outranks everything when negative signals are present.
    intent = max(scores, key=lambda k: (scores[k], k == "change_request"))
    if scores.get(intent, 0) == 0:
        intent = "unknown"
    # A question mark with no stronger signal is a question.
    if intent == "unknown" and "?" in t:
        intent = "question"
    # Approvals must beat change_request when both fire weakly but an explicit
    # yes-phrase exists.
    if scores.get("approval", 0) >= 2 and scores.get("change_request", 0) <= scores["approval"]:
        intent = "approval"
    if scores.get("complaint", 0) >= 2:
        intent = "complaint"
    if scores.get("rejection", 0) >= 1 and "dispute" in t:
        intent = "rejection"

    neg, pos = _score(text, _NEGATIVE_CUES), _score(text, _POSITIVE_CUES)
    sentiment = "negative" if neg > pos else ("positive" if pos > neg else "neutral")

    change_scores = {ct: _score(text, cues) for ct, cues in _CHANGE_TYPE_CUES.items()}
    change_type = None
    if intent == "change_request":
        change_type = max(change_scores, key=lambda k: change_scores[k])
        if change_scores[change_type] == 0:
            change_type = "other"

    # Extracted points — one per detected ask.
    points: list[dict[str, Any]] = []
    amounts = parse_amounts(text)
    dates = parse_dates(text)
    if change_scores["price"] >= 1 and amounts and intent in ("change_request", "question"):
        point: dict[str, Any] = {"type": "discount_request" if intent == "change_request" else "price_question"}
        if len(amounts) >= 2:
            point["from"], point["to"] = max(amounts), min(amounts)
        else:
            point["to"] = amounts[0]
        points.append(point)
    if change_scores["date"] >= 1 and dates and intent in ("change_request", "scheduling"):
        point = {"type": "date_change", "dates": [d.strftime("%Y-%m-%d") for d in dates]}
        m = re.search(r"(?:end|finish|before|by)\s+(?:the\s+)?(\d{1,2})", t)
        if m:
            point["constraint"] = f"end by {m.group(1)}"
        points.append(point)
    if change_scores["scope"] >= 1 and intent == "change_request":
        # F31: a count of whatever the client is counting — students, seats,
        # racks, sites. The old form required the literal word "students", so a
        # non-education client's delta was simply never read.
        m = (
            re.search(r"(\d+)\s+(?:more|additional|extra|further|fewer|less)\s+[a-z]+", t)
            or re.search(r"(?:add|include|expand\s+by)\s+(\d+)\s+[a-z]+", t)
            or re.search(r"(\d+)\s+[a-z]{3,}", t)
        )
        point = {"type": "scope_change", "detail": first_sentence(body)}
        if m:
            point["quantity_delta"] = int(m.group(1))
        if "drop" in t or "remove" in t or "reduce" in t:
            point["direction"] = "shrink"
        else:
            point["direction"] = "grow"
        points.append(point)
    if change_scores["content"] >= 1 and intent == "change_request":
        # One point per content-ask sentence containing a content cue.
        for sent in re.split(r"(?<=[.!?])\s+|,\s+and\s+", body):
            if _score(sent, _CHANGE_TYPE_CUES["content"]) >= 1 and len(sent.strip()) > 8:
                points.append({"type": "content_change", "detail": sent.strip()[:200]})
    if intent == "question":
        for sent in re.split(r"(?<=[.!?])\s+", body):
            if "?" in sent:
                points.append({"type": "question", "detail": sent.strip()[:200]})
    if intent == "complaint":
        for sent in re.split(r"(?<=[.!?])\s+", body):
            if _score(sent, _INTENT_CUES["complaint"]) >= 1 and len(sent.strip()) > 8:
                points.append({"type": "complaint_item", "detail": sent.strip()[:200]})
    if intent == "payment_info":
        points.append({"type": "payment_info", "detail": first_sentence(body)})
        if amounts:
            points[-1]["amount"] = amounts[0]
    if intent == "approval":
        points.append({"type": "approval", "detail": first_sentence(body)})

    # Mixed asks: price + content in one email → both points already captured;
    # promote intent to change_request when an approval also asks for changes.
    if intent == "approval" and (change_scores["content"] >= 1 or (change_scores["price"] >= 1 and amounts)):
        intent = "change_request"
        change_type = "price" if amounts else "content"

    strongest = scores.get(intent if intent in scores else "question", 0)
    confidence = min(0.95, 0.45 + 0.15 * strongest) if intent != "unknown" else 0.3

    return {
        "intent": intent,
        "change_type": change_type,
        "sentiment": sentiment,
        "summary": first_sentence(body),
        "extracted_points": points,
        "confidence": round(confidence, 2),
    }


async def screen_stranger_email(
    *, org_id: str, from_address: str, subject: str, body: str
) -> tuple[bool, str]:
    """An email arrived from an address we don't know. The model judges
    whether a human wrote it to this company about actual or potential
    business (enquiry, reply, complaint, payment, scheduling) or whether it
    is marketing/newsletter/notification noise. Returns (relevant, reason).

    Doubt never drops mail: stub provider, model failure, or model
    uncertainty all yield relevant=True so a human sees it in triage."""
    if not llm_available():
        return True, "stub provider — kept for a human"
    try:
        from app.ai.llm import get_model_layer

        result = await get_model_layer().generate_json(
            purpose="inbound.screen_email",
            org_id=org_id,
            system=(
                "You screen the inbox of a services company. Given an email "
                "from an address the company has no record of, decide whether "
                "a HUMAN wrote it to this company about actual or potential "
                "business — an enquiry, a reply, a complaint, a payment, a "
                "scheduling request — (relevant=true) or whether it is "
                "automated/marketing/newsletter/notification noise "
                "(relevant=false). When in doubt, relevant=true: a human "
                "will look at it."
            ),
            messages=[{"role": "user", "content": (
                f"From: {from_address}\nSubject: {subject}\n\n{body[:6000]}"
            )}],
            json_schema={
                "type": "object",
                "properties": {
                    "relevant": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["relevant", "reason"],
            },
        )
        if isinstance(result, dict) and "relevant" in result:
            return bool(result["relevant"]), str(result.get("reason") or "")[:300]
    except Exception as exc:  # noqa: BLE001 — screening is best-effort
        logger.warning("Stranger-email screening unavailable: %s", exc)
    return True, "screening unavailable — kept for a human"


async def classify_inbound(
    *, org_id: str, subject: str | None, body: str, context: str = ""
) -> dict[str, Any]:
    """Classify an inbound message — LLM when available, heuristics otherwise."""
    if llm_available():
        try:
            from app.ai.llm import get_model_layer

            schema = {
                "type": "object",
                "properties": {
                    "intent": {"type": "string", "enum": [
                        "question", "change_request", "approval", "rejection",
                        "complaint", "payment_info", "scheduling",
                        "acknowledgement", "unknown"]},
                    "change_type": {"type": "string", "enum": ["price", "content", "date", "scope", "other", ""]},
                    "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
                    "summary": {"type": "string"},
                    "extracted_points": {"type": "array", "maxItems": 10, "items": {"type": "object", "properties": {
                        # The routing vocabulary — handlers key off these exact
                        # names (price → approval rules, date/scope → Planner,
                        # content_change → revision task). F31: these names are
                        # LLM-facing, so they must not carry a domain word — a
                        # field called `students_delta` invites the model to leave
                        # it empty for a client ordering racks. Readers accept the
                        # older `syllabus_change` / `students_delta` too.
                        "type": {"type": "string", "enum": [
                            "discount_request", "price_question",
                            "content_change", "date_change", "scope_change",
                            "question", "complaint_item", "payment_info",
                            "approval", "other"]},
                        "detail": {"type": "string"},
                        "dates": {"type": "array", "items": {"type": "string"}},
                        "quantity_delta": {"type": "integer"},
                        "direction": {"type": "string", "enum": ["grow", "shrink", ""]},
                        "from": {"type": "number"},
                        "to": {"type": "number"},
                    }, "required": ["type", "detail"]}},
                    # Client-side people the message introduces — the Inbound
                    # Engine syncs them onto the project's stakeholder map.
                    "stakeholders": {"type": "array", "maxItems": 5, "items": {
                        "type": "object", "properties": {
                            "name": {"type": "string"},
                            "role": {"type": "string"},
                            "influence": {"type": "string", "enum": [
                                "decision_maker", "influencer", "gatekeeper"]},
                            "receives_updates": {"type": "boolean"},
                        }, "required": ["name", "role"]}},
                    "confidence": {"type": "number"},
                },
                "required": ["intent", "sentiment", "summary", "extracted_points", "confidence"],
            }
            result = await get_model_layer().generate_json(
                purpose="inbound.classify",
                org_id=org_id,
                system=(
                    "You read messages clients send to a services company. "
                    "Classify intent, sentiment and change_type, and break "
                    "every concrete ask into extracted_points (one object per "
                    "ask) using the type vocabulary exactly: "
                    "discount_request/price_question carry from/to amounts in "
                    "plain numbers; date_change carries dates as YYYY-MM-DD; "
                    "scope_change carries direction (grow/shrink) and "
                    "quantity_delta — the count the client asks to add or "
                    "remove, in whatever they are counting (people, seats, "
                    "licences, units, sites); content_change is any change to "
                    "the content of what we deliver. Any message about money "
                    "moving (cheque ready, paid, transfer done, collect the "
                    "payment) is intent payment_info even when it also "
                    "proposes a time. When the message introduces or names a "
                    "client-side person ('our finance head Meena will handle "
                    "this'), report them in stakeholders[] — role as a short "
                    "snake_case label in the client's own vocabulary, "
                    "influence judged from the message, receives_updates=true "
                    "for a day-to-day contact; never invent people. Be honest "
                    "about confidence."
                ),
                messages=[{"role": "user", "content": f"Context:\n{context}\n\nSubject: {subject}\n\n{body}"}],
                json_schema=schema,
            )
            if isinstance(result, dict) and result.get("intent"):
                result.setdefault("change_type", None)
                if result.get("change_type") == "":
                    result["change_type"] = None
                return result
        except Exception:  # noqa: BLE001 — never fail inbound ingestion
            logger.exception("LLM inbound classification failed")
        # The model was expected but unusable. Never guess with keyword
        # heuristics in production — report honest ignorance so the Inbound
        # Engine routes the message to a human (design rule 3).
        return {
            "intent": "unknown",
            "change_type": None,
            "sentiment": "neutral",
            "summary": first_sentence(body),
            "extracted_points": [],
            "confidence": 0.2,
        }
    return classify_inbound_heuristic(subject, body)


# ─────────────────────────────────────────────────────────────────────────────
# Meeting understanding (transcript / typed notes → structured facts)
# ─────────────────────────────────────────────────────────────────────────────

_TASK_CUES = [
    (r"(?:must|should|need to|has to|will)\s+(?:share|send)\s+(?:a\s+|the\s+)?([\w\- ]*syllabus[\w\- ]*)", "curriculum_design", True),
    (r"syllabus\s+within\s+(?:a\s+week|\d+\s+days?)", "curriculum_design", True),
    (r"demo(?:\s+session)?\s+for\s+(?:the\s+)?teachers?|teacher demo", "scheduling", True),
    (r"parents'?\s+demo", "teaching", True),
    (r"check\s+trainer\s+availability|trainer availability", "scheduling", False),
    (r"batch(?:es| schedule)", "scheduling", False),
    (r"proposal", "proposals", False),
    (r"invoice|advance payment|50%\s*advance", "invoicing", False),
    (r"workbooks?|kits?|materials?", "logistics", False),
    (r"thank[- ]you.*email|summary email", "english_writing", True),
]

_COMMITMENT_CUES = [
    r"(?:we(?:'ll| will)?|yuvipep)\s+(?:must\s+)?share\s+.{0,60}?within\s+(a\s+week|\d+\s+days?)",
    r"syllabus\s+within\s+(a\s+week|\d+\s+days?)",
    r"demo\s+(?:session\s+)?(?:for teachers\s+)?(?:first|before)",
]


def extract_meeting_heuristic(text: str, *, base: datetime | None = None) -> dict[str, Any]:
    """Deterministic extraction of the facts a Planner merge needs."""
    base = base or utcnow()
    t = text.lower()
    facts: dict[str, Any] = {
        "summary": first_sentence(text, 240),
        "duration_days": None,
        "classes": None,
        "students": None,
        "budget": None,
        "dates": [d.strftime("%Y-%m-%d") for d in parse_dates(text, base=base)],
        "computers": None,
        "wants_month": None,
        "concrete": False,
        "commitments": [],
        "new_facts": [],
    }
    m = re.search(r"(\d+)[- ]day", t)
    if m:
        facts["duration_days"] = int(m.group(1))
    m = re.search(r"class(?:es)?\s+(\d+)\s*(?:to|–|-|and)\s*(\d+)", t)
    if m:
        facts["classes"] = [int(m.group(1)), int(m.group(2))]
    m = re.search(r"(\d{2,4})\s+students", t)
    if m:
        facts["students"] = int(m.group(1))
    amounts = parse_amounts(text)
    if amounts:
        facts["budget"] = max(amounts)
    m = re.search(r"(?:only\s+)?(\d+)\s+computers", t)
    if m:
        facts["computers"] = int(m.group(1))
    for name, num in _MONTHS.items():
        if len(name) > 3 and re.search(rf"\bin {name}\b", t):
            facts["wants_month"] = num
    # Commitments ("share syllabus within a week", "demo before the bootcamp")
    if re.search(r"within a week|within \d+ days?", t) and "syllabus" in t:
        facts["commitments"].append(
            {"text": "Share syllabus within a week", "days": 7, "skill": "curriculum_design"}
        )
    if "teacher" in t and "demo" in t:
        facts["commitments"].append(
            {"text": "Teacher demo before the program", "days": 10, "skill": "scheduling"}
        )
    if "parents" in t and "demo" in t:
        facts["commitments"].append(
            {"text": "Parents' demo on the last day", "days": 21, "skill": "teaching"}
        )
    # Logistics facts worth remembering
    for sent in re.split(r"(?<=[.!?])\s+", text):
        st = sent.lower()
        if any(cue in st for cue in ("computer lab", "computers", "gate opens", "prefers", "hindi", "batches")):
            facts["new_facts"].append(sent.strip()[:200])
    # A meeting is 'concrete' (project-worthy) when there is a real ask:
    facts["concrete"] = bool(
        facts["duration_days"] or facts["students"] or facts["budget"] or "bootcamp" in t
        or "program" in t or "lab" in t
    ) and not re.search(r"\bjust (?:a )?(?:chat|hello)|nothing specific|no concrete", t)
    return facts


# NOTE: meeting understanding in production is app/ai/planning.py
# (generate_initial_plan / generate_plan_merge — generic, any topic).
# extract_meeting_heuristic above serves ONLY the stub provider, which keeps
# tests and dry runs deterministic.
