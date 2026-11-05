"""A new client, built up by conversation — the flow behind "create a lead".

The person names the client. The flow then settles the six things the app's
New Lead form holds — name, owner, city, source, website, notes — in a fixed
order, and creates nothing until the person says to:

  name      "What is the client called?"                  (only if not given)
  owner     "Who should own it? Priya Nair, Rahul Reddy, or you?"
            A skip gets one push back with a suggestion ("the owner makes the
            cold calls, so it needs one. Shall I give it to Priya Nair?"); a
            second skip, "you decide" or "whatever you want" takes the
            suggestion. Never left empty: the owner is the only person who can
            take a lead out of cold calling.
  optional  "Do you want to add a city, source, website or notes? They're
            optional."                                   (asked once)
  confirm   "So: <everything>. Anything else, or shall I create it?"
            Only a clear yes creates. New details are read back again first.

The suggested owner is the sales agent holding the fewest leads in cold
calling (ties by name), and the owner question lists agents in that order.

THE SERVER DECIDES WHAT TO ASK NEXT. A model only reads the person's words into
values (`_interpret`), and only when a short fixed phrase has not already
answered: "skip this", "do whatever you want", "me", "create it" cost no model
call. That split is measured, not taste — given a prompt listing the fields,
the fast model asked for all of them instead of calling its tool; given a
read-back as prose, it re-split "Harbour Foods in Kochi" into a name.

At any step the person may ask for a value to be spelled ("spell the
organisation name") and correct it — in words ("it's Bhawan with a W"), or
letter by letter ("the second word is B H A W A N"). Letters are assembled by
the server, never guessed by a model; a complaint it cannot place ("the second
word is wrong") is answered "spell the second word for me, letter by letter".

A name, city or contact heard BY VOICE below
VOICE_SPELL_CHECK_BELOW_CONFIDENCE is spelled back once before "create it" is
accepted ("Before I create it, let me check the spelling … Is that right?").
Measured 2026-09-15: large-v3 heard "Bhavan" as "Bavin" and "Pune" as "Puna",
and a plain read-back was agreed to anyway. Typed input, and speech heard
confidently, go straight through as specified.

A question about something else is answered normally and the draft waits:
"…and shall I continue with X?".

Creation is `lead_service.create_lead` + `add_contact`, the code behind
POST /leads and POST /leads/{id}/contacts.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import confirmations
# The resolvers' matching ladder, reused so "Priya" or "is it already on
# file?" mean exactly what "which one do you mean?" means everywhere else.
from app.ai.agents.resolvers import _CONNECTOR_WORDS, _match, _name_conditions, _Row, _words
from app.ai.llm import TIER_FAST, get_model_layer
from app.config import get_settings
from app.core.constants import LeadState, Role
from app.core.context import OrgContext
from app.core.exceptions import (
    AppError,
    NeedsConfirmationError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.core.permissions import has_permission
from app.models.assistant import AssistantPendingAction
from app.models.lead import Lead
from app.models.user import User
from app.services import lead_service

logger = logging.getLogger(__name__)

KIND = "create_client"
AGENT = "client"
# Only holders of this permission may own a lead: the owner is the only one who
# can take it out of cold calling, and that move itself needs the permission.
WORKS_LEADS = "manage_leads"
NAME_MIN, NAME_MAX = 2, 300
OPTIONAL = ("city", "source", "website", "notes")
OWNER_CHOICES_SPOKEN = 3
SIMILAR_LIMIT = 3
#: How close (difflib ratio) a name that matches nobody must be to someone's
#: to be offered back as "Did you mean …?" ("Rahool" → "Rahul" is 0.73).
NEAR_NAME_SIMILARITY = 0.7
#: How alike a client already on file must be to stop the flow and ask before
#: a second one is built up. High on purpose: "Aditya School Kolkata" beside
#: "Aditya School" is usually a different school and is only MENTIONED, at the
#: read-back; the same name twice is what people do not mean to do.
DUPLICATE_SIMILARITY = 0.88
# The voice hint (vocabulary_hint): how many recent clients, how much room the
# people may take, and the whole hint's size (Whisper's limit is ~223 tokens,
# about 650-700 characters of names; stt._fit_prompt enforces it exactly).
HINT_CLIENTS = 20
HINT_PEOPLE_CHARS = 400
HINT_CHARS = 800
# Cities every hint carries after the org's own client cities. A fixed list,
# the one measured on 2026-09-17 (not built from the test sentences).
HINT_CITIES = ("Bengaluru", "Mysuru", "Mangaluru", "Hubballi", "Belagavi", "Kalaburagi",
               "Chennai", "Coimbatore", "Hyderabad", "Vijayawada", "Visakhapatnam",
               "Thiruvananthapuram", "Kochi", "Mumbai", "Pune", "Nashik", "Nagpur",
               "Ahmedabad", "Indore", "Bhopal")
# Said around a name but not part of it: "Rahul ji", "Priya madam".
_HONORIFICS = frozenset({"ji", "sir", "madam", "maam", "bhai", "anna", "akka", "didi",
                         "sahab", "saheb", "garu"})

STAGE_NAME = "name"
STAGE_DUPLICATE = "duplicate"
STAGE_OWNER = "owner"
STAGE_SUGGESTED = "owner_suggested"
STAGE_OPTIONAL = "optional"
STAGE_CONFIRM = "confirm"
STAGE_SPELLCHECK = "spell_check"
# Open straight away: a sales lead only (7 Oct 2026).
STAGE_OPEN_CHOICE = "open_choice"
STAGE_OPEN_CONTACT = "open_contact"
STAGE_EMAIL_CHECK = "email_check"

CHIPS_DUPLICATE = ["Add it anyway", "Cancel"]
CHIPS_SUGGESTED = ["Yes", "Someone else"]
CHIPS_OPTIONAL = ["No thanks"]
CHIPS_CONFIRM = ["Create it", "Cancel"]
CHIPS_SPELLCHECK = ["Yes", "No"]
CHIPS_OPEN_CHOICE = ["Open it now", "Cold calling"]

# Values whose spelling can be corrected letter by letter, and the ones worth
# spelling back when they were heard by voice with doubt (a source or a
# website is a phrase, not a name to mishear).
_CORRECTABLE = ("name", "city", "contact_name", "source", "website")
_SPELLABLE = ("name", "city", "contact_name")
_FIELD_WORDS = (("contact", "contact_name"), ("city", "city"), ("town", "city"),
                ("website", "website"), ("source", "source"),
                ("name", "name"), ("organisation", "name"),
                ("organization", "name"), ("company", "name"),
                ("client", "name"), ("lead", "name"))
_ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2,
             "fourth": 3, "4th": 3, "fifth": 4, "5th": 4, "last": -1,
             "pehla": 0, "pehle": 0, "doosra": 1, "dusra": 1, "teesra": 2,
             "tisra": 2, "modala": 0, "eradane": 1, "mooraneya": 2}
_ORDINAL_NAMES = {0: "first", 1: "second", 2: "third", 3: "fourth",
                  4: "fifth", -1: "last"}
_SPELL_CUES = frozenset({"spell", "spelled", "spelling", "spelt", "letter",
                         "letters", "word", "wrong", "mistake", "correct",
                         "with", "should"})
# Narrower: what makes "the second …" a request to fix a WORD's spelling rather
# than, say, "what's my second task".
_SPELL_REQUEST_CUES = frozenset({"word", "letter", "letters", "spell", "spelled",
                                 "spelling", "spelt"})
_LETTER_SPLIT = re.compile(r"[\s.,;:/\-–—]+")

_TEXT_FIELDS = ("name", "city", "source", "website", "notes", "address", "region")
_CONTACT_KEYS = ("title", "phone", "email")
_READ_FIELDS = ("name", "owner", "city", "source", "website", "notes",
                "contact_name", "contact_title", "contact_phone", "contact_email")
_ANSWERS = frozenset({"values", "yes", "no", "skip", "delegate", "cancel",
                      "spell", "other_request", "unclear"})

# ── fixed phrases (read without a model) ─────────────────────────────────────
# Each is (core, allowed): the reply must contain a core word and consist only
# of allowed words, so "skip the website but add Pune" is never mistaken for a
# skip — anything outside the vocabulary goes to the model.
_CANCEL = ({"cancel", "drop", "forget", "discard", "abort", "scrap"},
           {"it", "this", "that", "the", "lead", "client", "please", "whole",
            "thing", "about", "all", "just", "ok", "okay", "everything"})
_SELF = ({"me", "myself", "mine", "ill", "i"},
         {"will", "own", "it", "make", "give", "to", "please", "assign", "take",
          "the", "owner", "can", "let", "keep", "just", "ok", "okay"})
_DELEGATE = ({"whatever", "decide", "choose", "pick", "choice", "matter",
              "anyone", "anybody", "care", "whoever", "whichever", "any"},
             {"do", "you", "want", "like", "think", "your", "call", "up", "to",
              "its", "it", "doesnt", "does", "not", "is", "fine", "i", "dont",
              "just", "please", "ok", "okay", "go", "ahead", "yourself",
              "works", "can", "one", "give", "assign", "them", "will", "be",
              "wish", "feel", "all", "good", "best", "suits", "feels"})
_SKIP = ({"skip", "pass", "later", "leave", "skipping"},
         {"this", "it", "that", "for", "now", "one", "please", "the",
          "question", "just", "i", "will", "ill", "decide", "next", "out",
          "lets", "let", "us", "move", "on", "ok", "okay", "can", "we", "do",
          "blank", "empty", "maybe"})
_SOMEONE_ELSE = ({"someone", "somebody", "else", "other", "another",
                  "different"},
                 {"no", "not", "them", "her", "him", "person", "give", "it",
                  "to", "please", "pick", "choose", "one"})
_CREATE = ({"create", "add", "save", "go"},
           {"it", "the", "lead", "client", "now", "please", "ahead", "yes",
            "yeah", "ok", "okay", "sure", "do", "that", "this", "and", "just",
            "right", "away", "record", "one", "then", "anyway", "another",
            "second", "separate", "still", "new"})
_NOTHING = ({"nothing", "none", "no", "nope", "nah", "thats"},
            {"thanks", "thank", "you", "else", "more", "for", "now", "its",
             "fine", "ok", "okay", "all", "it", "need", "not", "required",
             "just", "please"})
_OPEN_NOW = ({"open"},
             {"it", "now", "straight", "away", "right", "directly", "please", "yes",
              "make", "the", "lead", "client", "immediately", "just", "ok", "okay",
              "lets", "go", "ahead", "and", "actually", "instead", "rather"})
# Changing one's mind later in the conversation (not at the open question):
# "later" is left out here, because "later" to "what is her email?" means the
# email, not cold calling.
_COLD_SWITCH = ({"cold", "calling"},
                {"start", "it", "in", "with", "please", "no", "keep", "leave", "put",
                 "the", "lead", "client", "just", "ok", "okay", "lets", "go", "for",
                 "now", "call", "actually", "instead", "rather", "make", "do", "as",
                 "a", "lead"})
_COLD_START = ({"cold", "calling", "later"},
               {"start", "it", "in", "with", "please", "no", "keep", "leave", "put",
                "the", "lead", "client", "just", "ok", "okay", "lets", "go", "for",
                "now", "call"})
_MAX_PHRASE_WORDS = 8
# Open now or cold calling is taken only from words the person said, the last
# one winning ("start in cold calling ... no, sorry, open it" is open). The
# model's own open_now is not trusted: replaying Siva's chat (7 Oct 2026) it
# read "She is Principal." as open now.
_OPEN_WORDS = frozenset({"open", "opened", "khol", "kholo", "kholdo", "khole",
                         "खोल", "खोलो", "खोल दो", "ತೆರೆ", "ತೆರೆಯಿರಿ"})
_COLD_WORDS = frozenset({"cold"})


def _choice_in_words(found: list[str]) -> bool | None:
    """True for open, False for cold calling, from the last of those words
    said; None when the person said neither."""
    choice = None
    for word in found:
        if word in _OPEN_WORDS:
            choice = True
        elif word in _COLD_WORDS:
            choice = False
    return choice


def _is(found: list[str], phrase: tuple[set[str], set[str]]) -> bool:
    core, allowed = phrase
    return (0 < len(found) <= _MAX_PHRASE_WORDS
            and any(w in core for w in found)
            and all(w in core or w in allowed for w in found))


# ── small helpers ────────────────────────────────────────────────────────────

#: Words that ASK for a client to be created rather than name one. Removed
#: only from the END of a name, and only a run of two or more: Kannada and
#: Hindi put the verb last ("TPU shaale emba hesarinalli ondu lead rachisi"),
#: while a real name may still end in one of them ("Global Lead").
_REQUEST_TAIL = frozenset({
    # English
    "a", "an", "one", "new", "lead", "leads", "client", "clients", "create",
    "add", "register", "record", "please", "named", "name", "called",
    # Kannada
    "ondu", "hosa", "hosadu", "maadi", "madi", "maado", "rachisi", "rachiso",
    "serisi", "sersi", "emba", "hesarinalli", "hesaru", "hesarina", "annu",
    "ge", "alli", "ಒಂದು", "ಹೊಸ", "ಮಾಡಿ", "ರಚಿಸಿ", "ಹೆಸರಿನಲ್ಲಿ",
    # Hindi
    "ek", "naya", "nayi", "naye", "banao", "banaiye", "bana", "banado",
    "kijiye", "karo", "kar", "ke", "ki", "ka", "ko", "liye", "naam", "se",
    "me", "mein", "एक", "नया", "बनाओ", "नाम", "के", "लिए",
})
_REQUEST_TAIL_MIN = 2


def _client_name_only(name: str) -> str:
    """The organisation's own name, without the request wrapped around it.

    "TPU shaale emba hesarinalli ondu lead rachisi" is Kannada for "create a
    lead by the name TPU school", and the model handed the whole sentence over
    as the NAME — twice, on two different phrasings, after being told not to
    (21 Sep 2026). Asking the model more nicely is not a guarantee; this is.
    Only a run of at least two request words at the END goes, so "Global Lead"
    and "Lead India School" are left exactly as they are.
    """
    parts = name.split()
    cut = len(parts)
    while cut > 1 and re.sub(r"\W", "", parts[cut - 1].lower()) in _REQUEST_TAIL:
        cut -= 1
    if len(parts) - cut < _REQUEST_TAIL_MIN:
        return name
    return " ".join(parts[:cut])


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _role_label(role: str) -> str:
    return role.replace("_", " ")


def _sentence(text: str) -> str:
    return text if text[-1:] in ".!?" else text + "."


def _join_or(parts: list[str]) -> str:
    if len(parts) <= 2:
        return " or ".join(parts)
    return ", ".join(parts[:-1]) + ", or " + parts[-1]


def _join_and(parts: list[str]) -> str:
    if len(parts) <= 2:
        return " and ".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def spell_out(value: str) -> str:
    """"Bal Bhavan" -> "B-A-L, B-H-A-V-A-N" — for the screen."""
    return ", ".join(
        "-".join(ch.upper() for ch in word if ch.isalnum()) or word
        for word in value.split()
    )


_EMAIL_SYMBOLS = {"-": "dash", "_": "underscore", "+": "plus"}


def _spell_part(part: str) -> str:
    out: list[str] = []
    run: list[str] = []
    for ch in part:
        if ch.isalnum():
            run.append(ch.upper())
            continue
        if run:
            out.append("-".join(run))
            run = []
        out.append(_EMAIL_SYMBOLS.get(ch, ch))
    if run:
        out.append("-".join(run))
    return " ".join(out)


def spell_email(address: str) -> str:
    """"anita@acme-example.com" -> "A-N-I-T-A at A-C-M-E dash E-X-A-M-P-L-E
    dot C-O-M": one text for the screen and for voice."""
    local, _, domain = address.partition("@")

    def dotted(text: str) -> str:
        return " dot ".join(_spell_part(piece) for piece in text.split("."))

    return f"{dotted(local)} at {dotted(domain)}"


def _email_form(value: str) -> str:
    """An address as written, from how it may have been said:
    "anita at acme dot com" -> "anita@acme.com"."""
    text = " ".join(value.split())
    if "@" not in text:
        # "at the rate (of)" is "@" too; read before "at" alone, or "the rate"
        # became part of the domain (live, 7 Oct 2026: ...@therategmail.com).
        text = re.sub(r"\s*\bat\s+the\s+rate(?:\s+of)?\b\s*", "@", text,
                      flags=re.IGNORECASE)
    if "@" not in text:
        text = re.sub(r"\s+at\s+", "@", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+dot\s+", ".", text, flags=re.IGNORECASE)
    return text.replace(" ", "").lower()


# Found with the real model (7 Oct 2026): "anita dot sharma at gmail dot com"
# came back as anita.dots.sharma, anita.dout.sharma and anita.dots.harma on
# three runs. An address in the person's own words is read here, in code, and
# that reading wins over the model's.
_EMAIL_CONNECTORS = {"dot": ".", "underscore": "_", "dash": "-", "hyphen": "-",
                     "plus": "+"}
_WRITTEN_EMAIL = re.compile(r"[^\s@<>()\[\],;:\"']+@[^\s@<>()\[\],;:\"']+\.[^\s@<>()\[\],;:\"']+")
# A word of an address as said or typed: "anita", "x-corp", and also written
# dots and underscores inside it ("ekaghni.mukherjee", "gmail.com").
_EMAIL_TOKEN = re.compile(r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$")
# A domain on its own ("gmail.com"), for a correction that names only it.
_DOMAIN = re.compile(r"^(?=[^.]*[a-z])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}$")
# A reply at the email check that says the address is wrong.
_NEGATIONS = frozenset({"no", "not", "wrong", "incorrect", "nope", "nahi", "nahin",
                        "galat", "नहीं", "नही", "गलत", "ಇಲ್ಲ", "ತಪ್ಪು"})
_SPELLED_HYPHENS = re.compile(r"^(?:[a-z]-)+[a-z]$")
_EMAIL_CUES = frozenset({"email", "e-mail", "mail", "emailid", "id", "is", "its",
                         "it's", "on", "to", "address"})


def _email_parts(text: str | None) -> tuple[str | None, bool]:
    """(the address the words hold, whether the words are nothing else)."""
    text = text or ""
    written = _WRITTEN_EMAIL.search(text)
    if written:
        address = written.group(0).rstrip(".!?").lower()
        if not lead_service.looks_like_email(address):
            return None, False
        return address, len(text.split()) == 1
    # Words, and whether each was followed by a pause (a comma or a stop).
    words: list[str] = []
    pause: list[bool] = []
    for raw in text.split():
        word = raw.strip(".,!?;:\"'()").lower()
        if word:
            words.append(word)
            pause.append(raw.rstrip()[-1:] in ",.;:")
    # "at the rate (of)" is how many people in India say "@".
    i = 0
    while i < len(words):
        if words[i] == "at" and words[i + 1:i + 3] == ["the", "rate"]:
            cut = 4 if words[i + 3:i + 4] == ["of"] else 3
            del words[i + 1:i + cut], pause[i + 1:i + cut]
        i += 1

    def is_word(w: str) -> bool:
        return bool(_EMAIL_TOKEN.match(w)) and w not in _EMAIL_CONNECTORS and w != "at"

    def is_letter(k: int) -> bool:
        return len(words[k]) == 1 and words[k].isalpha()

    best: tuple[int, str, bool] | None = None   # (strength, address, alone)
    for i, w in enumerate(words):
        if w != "at" or i == 0 or i + 1 >= len(words) or not is_word(words[i + 1]):
            continue
        domain, end = [words[i + 1]], i + 2
        while end + 1 < len(words) and words[end] == "dot" and is_word(words[end + 1]):
            domain += [".", words[end + 1]]
            end += 2
        if "." not in "".join(domain):
            continue
        j = i - 1
        if is_letter(j) and j >= 1 and is_letter(j - 1) and not pause[j - 1]:
            # Spelled out: "A N I T A at ..." is anita, not a.
            start = j
            while start - 1 >= 0 and is_letter(start - 1) and not pause[start - 1]:
                start -= 1
            local = ["".join(words[start:j + 1])]
        elif _SPELLED_HYPHENS.match(words[j]):
            start, local = j, [words[j].replace("-", "")]
        elif is_word(words[j]):
            local, start = [words[j]], j
            while (start - 2 >= 0 and words[start - 1] in _EMAIL_CONNECTORS
                   and is_word(words[start - 2])):
                local = [words[start - 2], _EMAIL_CONNECTORS[words[start - 1]]] + local
                start -= 2
        else:
            continue
        # Only where the words clearly start an address: at the beginning,
        # after a cue ("email", "is", "on"), or after a pause. "She works at
        # tata dot com" and "anita sharma at gmail dot com" are not read here
        # -- the model reads them -- and a cue beats a pause.
        if start == 0 or words[start - 1] in _EMAIL_CUES:
            strength = 2
        elif pause[start - 1]:
            strength = 1
        else:
            continue
        address = "".join(local) + "@" + "".join(domain)
        if lead_service.looks_like_email(address) and (best is None or strength >= best[0]):
            best = (strength, address, start == 0 and end == len(words))
    return (best[1], best[2]) if best else (None, False)


def _domain_in(text: str | None) -> str | None:
    """The last domain the words name ("gmail.com", "gmail dot com"), or None.
    For a correction at the email check that names only the domain."""
    words = [w.strip(".,!?;:\"'()").lower() for w in (text or "").split()]
    found: str | None = None
    i = 0
    while i < len(words):
        w = words[i]
        if "@" not in w and _DOMAIN.match(w):
            found = w
        if w == "dot" and 0 < i < len(words) - 1:
            parts, j = [words[i - 1]], i
            while j + 1 < len(words) and words[j] == "dot" and words[j + 1].isalnum():
                parts.append(words[j + 1])
                j += 2
            spoken = ".".join(parts)
            if _DOMAIN.match(spoken):
                found = spoken
            # Each "dot" is read once: "acme dot co dot in" is acme.co.in.
            i = max(j, i + 1)
            continue
        i += 1
    return found


def email_in(text: str | None) -> str | None:
    """The email address the person's words hold, written ("anita@acme.com")
    or spoken ("anita dot sharma at acme dot com"), or None."""
    return _email_parts(text)[0]


def _a(label: str) -> str:
    return ("an " if label[:1] in "aeiou" else "a ") + label


def _new_draft() -> dict[str, Any]:
    return {
        "name": None, "city": None, "source": None, "website": None,
        "notes": None, "address": None, "region": None,
        "owner_id": None, "owner_name": None, "contact": None,
        "stage": STAGE_OWNER, "question": "", "candidates": [],
        "pushed_back": False, "suggestion_id": None, "suggestion_name": None,
        "declined": [], "asked_optional": False, "sure_asked": False,
        "paused": False, "spelled": None, "duplicate_checked_for": None,
        # Spelling state: fields heard by voice with doubt, the ones being
        # checked now, and a correction waiting for its letters or its word.
        "unsure": [], "checking": [], "spell_word": None, "spell_letters": None,
        "spell_rejected": False,
        # Open straight away (sales lead, 7 Oct 2026): None = not decided.
        "open_now": None, "owner_forced": False, "email_confirmed": False,
        "recheck_email": False,
    }


def _load(row: AssistantPendingAction) -> dict[str, Any]:
    draft = _new_draft()
    try:
        stored = json.loads(row.payload)
    except ValueError:
        stored = {}
    if isinstance(stored, dict):
        draft.update(stored)
    return draft


def _title(draft: dict[str, Any]) -> str:
    return draft["name"] or "the new client"


def _public(draft: dict[str, Any], ctx: OrgContext) -> dict[str, Any]:
    """What the app (and the reading model) may see: values, never ids."""
    owner = None
    if draft["owner_id"]:
        owner = "you" if draft["owner_id"] == ctx.user_id else draft["owner_name"]
    return {
        "stage": draft["stage"], "name": draft["name"], "owner": owner,
        "city": draft["city"], "source": draft["source"],
        "website": draft["website"], "notes": draft["notes"],
        "address": draft["address"], "region": draft["region"],
        "contact": draft["contact"],
        "open_now": draft.get("open_now"),
    }


# ── the organisation's people and clients ────────────────────────────────────

async def people_who_work_leads(db: AsyncSession, org_id: str) -> list[User]:
    roles = [r.value for r in Role if has_permission(r.value, WORKS_LEADS)]
    users = (
        await db.execute(
            select(User)
            .where(User.org_id == org_id, User.is_active.is_(True),
                   User.role.in_(roles))
            .order_by(User.name)
        )
    ).scalars().all()
    return sorted(users, key=lambda u: u.role != Role.SALES_AGENT.value)


async def _owner_options(db: AsyncSession, ctx: OrgContext) -> list[User]:
    """The other sales agents, fewest leads in cold calling first, then by name
    — the order they are offered in, so the first is also the suggestion."""
    agents = (
        await db.execute(
            select(User).where(
                User.org_id == ctx.org_id, User.is_active.is_(True),
                User.role == Role.SALES_AGENT.value, User.id != ctx.user_id,
            )
        )
    ).scalars().all()
    if not agents:
        return []
    counts = dict(
        (
            await db.execute(
                select(Lead.owner_id, func.count(Lead.id))
                .where(Lead.org_id == ctx.org_id,
                       Lead.state == LeadState.COLD_CALLING.value,
                       Lead.owner_id.in_([u.id for u in agents]))
                .group_by(Lead.owner_id)
            )
        ).all()
    )
    return sorted(agents, key=lambda u: (counts.get(u.id, 0),
                                         (u.name or u.email).lower()))


async def names_by_id(db: AsyncSession, org_id: str, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = (
        await db.execute(select(User).where(User.org_id == org_id, User.id.in_(ids)))
    ).scalars().all()
    return {u.id: u.name or u.email for u in rows}


async def matching_clients(db: AsyncSession, org_id: str, name: str) -> list[Lead]:
    rows = (
        await db.execute(
            select(Lead)
            .where(Lead.org_id == org_id, or_(*_name_conditions(Lead.name, name)))
            .order_by(Lead.last_activity_at.desc())
            .limit(40)
        )
    ).scalars().all()
    return [c.row for c in _match(name, [_Row(row=l, names=(l.name,)) for l in rows])]


def _name_words(hint: str) -> list[str]:
    """The words of a spoken or typed name, without glue ("to", "please") or
    a form of address ("ji", "sir")."""
    return [w for w in _words(hint) if w not in _CONNECTOR_WORDS and w not in _HONORIFICS]


def _said_in_full(hint: str, user: User) -> bool:
    """Whether the person was named, not merely resembled: every word said is
    a whole word of their name ("Rahul", "priya nair", "Nair"), or the hint
    is their email. "Ria Nair" is not Priya Nair, although the matching
    ladder finds "ria nair" inside "priya nair"."""
    if hint.strip().lower() == (user.email or "").lower():
        return True
    said = _name_words(hint)
    return bool(said) and set(said) <= set(_words(user.name or user.email))


def _sounding_like(hint: str, users: list[User]) -> list[User]:
    """People whose name is spelled close to what was heard ("Rahool" → Rahul
    Reddy), closest first. Only ever offered as a question."""
    said = " ".join(_name_words(hint))
    if not said:
        return []
    scored = []
    for user in users:
        name = " ".join(_words(user.name or ""))
        options = [name] + (_words(name) if " " not in said else [])
        best = max((_similar(said, option) for option in options if option), default=0.0)
        if best >= NEAR_NAME_SIMILARITY:
            scored.append((best, user))
    scored.sort(key=lambda pair: -pair[0])
    return [user for _score, user in scored]


def _did_you_mean(hint: str, user: User, ctx: OrgContext) -> dict[str, Any]:
    name = "you" if user.id == ctx.user_id else user.name or user.email
    return {"text": f"I couldn't find anyone called {hint}. Did you mean {name}?",
            "candidates": [], "suggest": (user.id, user.name or user.email)}


async def _resolve_owner(
    db: AsyncSession, ctx: OrgContext, hint: str
) -> tuple[tuple[str, str] | None, dict[str, Any] | None]:
    """(owner_id, name), or a problem to put to the person. Asks, never guesses.

    A problem with "suggest" (id, name) is a single person the words only
    resemble: the flow asks "Did you mean …?" and uses them only on a yes."""
    own = ctx.name or ctx.email
    if _is(confirmations.words(hint), _SELF) or hint.lower() in {
        (ctx.name or "").lower(), ctx.email.lower()
    }:
        return (ctx.user_id, own), None
    workers = await people_who_work_leads(db, ctx.org_id)
    hits = _match(hint, [_Row(row=u, names=(u.name or u.email,), addresses=(u.email,))
                         for u in workers])
    if len(hits) == 1:
        user = hits[0].row
        if not _said_in_full(hint, user):
            return None, _did_you_mean(hint, user, ctx)
        return ((ctx.user_id, own) if user.id == ctx.user_id
                else (user.id, user.name or user.email)), None
    if hits:
        names = [h.label for h in hits][:4]
        return None, {"text": f"Did you mean {_join_or(names)}?", "candidates": names}
    others = (
        await db.execute(select(User).where(User.org_id == ctx.org_id,
                                            User.is_active.is_(True)))
    ).scalars().all()
    others = [u for u in others if not has_permission(u.role, WORKS_LEADS)]
    near = _match(hint, [_Row(row=u, names=(u.name or u.email,), addresses=(u.email,))
                         for u in others])
    if len(near) == 1:
        user = near[0].row
        return None, {"text": f"{user.name or user.email} is "
                              f"{_a(_role_label(user.role))} and can't own a client.",
                      "candidates": []}
    close = _sounding_like(hint, workers)
    if len(close) == 1:
        return None, _did_you_mean(hint, close[0], ctx)
    if close:
        names = [u.name or u.email for u in close][:4]
        return None, {"text": f"I couldn't find anyone called {hint}. "
                              f"Did you mean {_join_or(names)}?", "candidates": names}
    return None, {"text": f"I couldn't find anyone called {hint} who can own a client.",
                  "candidates": []}


# ── spelling, read without a model ───────────────────────────────────────────

def _field_value(draft: dict[str, Any], field_name: str) -> str | None:
    if field_name == "contact_name":
        return (draft["contact"] or {}).get("name")
    return draft.get(field_name)


def _spelled_letters(text: str) -> str | None:
    """The longest run of three or more single letters in the reply —
    "S H R E E", "B-H-A-W-A-N", "P, U, N, E" — joined into a word."""
    best: list[str] = []
    run: list[str] = []
    for token in _LETTER_SPLIT.split(text or ""):
        if len(token) == 1 and token.isalpha():
            run.append(token)
            continue
        if len(run) > len(best):
            best = run
        run = [] if token else run
    if len(run) > len(best):
        best = run
    return "".join(best) if len(best) >= 3 else None


def _ordinal(found: list[str]) -> int | None:
    return next((_ORDINALS[w] for w in found if w in _ORDINALS), None)


def _mentioned_field(found: list[str]) -> str | None:
    return next((field for word, field in _FIELD_WORDS if word in found), None)


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _letters_reading(draft: dict[str, Any], text: str,
                     found: list[str]) -> dict[str, Any] | None:
    """A correction spelled letter by letter, applied to the right word."""
    index = _ordinal(found)
    letters = _spelled_letters(text)
    if letters is None and draft["spell_letters"] and index is not None:
        letters = draft["spell_letters"]  # "the second one", after "which word?"
    if letters is None:
        return None
    explicit = _mentioned_field(found)
    spelling_now = bool(draft["spelled"] or draft["checking"] or draft["spell_letters"]
                        or draft["spell_word"] is not None)
    if not (spelling_now or explicit or any(w in _SPELL_CUES for w in found)):
        return None  # a stray run of letters is not a correction
    if explicit:
        fields = [explicit]
    elif draft["checking"]:
        fields = list(draft["checking"])
    elif draft["spelled"] in _CORRECTABLE:
        fields = [draft["spelled"]]
    else:
        fields = ["name"]
    if index is None and draft["spell_word"] is not None:
        index = draft["spell_word"]

    def which_word() -> dict[str, Any]:
        return {"answer": "which_word", "updates": {}, "letters": letters,
                "field": fields[0], "spell_field": None}

    options: list[tuple[float, str, int]] = []
    for field_name in fields:
        value = _field_value(draft, field_name)
        if not value:
            continue
        parts = value.split()
        if index is not None:
            if -len(parts) <= index < len(parts):
                options.append((_similar(parts[index], letters), field_name, index))
        else:
            options += [(_similar(word, letters), field_name, i)
                        for i, word in enumerate(parts)]
    if not options:
        if index is None and not _field_value(draft, fields[0]):
            word = letters[:1].upper() + letters[1:].lower()
            return {"answer": "values", "updates": {fields[0]: word},
                    "spelled_field": fields[0], "spell_field": None}
        return which_word()
    options.sort(key=lambda option: option[0], reverse=True)
    best = options[0]
    decided = (index is not None or len(options) == 1
               or (best[0] >= 0.5 and best[0] - options[1][0] >= 0.1))
    if not decided:
        return which_word()
    _score, field_name, position = best
    parts = _field_value(draft, field_name).split()
    old = parts[position]
    parts[position] = (letters.upper() if old.isupper() and len(old) > 1
                       else letters[:1].upper() + letters[1:].lower())
    return {"answer": "values", "updates": {field_name: " ".join(parts)},
            "spelled_field": field_name, "spell_field": None}


def _spelling_request(draft: dict[str, Any], found: list[str]) -> dict[str, Any] | None:
    """"The second word is wrong" with no letters the model could use: ask
    for the letters rather than guess or say "didn't catch that"."""
    index = _ordinal(found)
    if index is None or not any(w in _SPELL_REQUEST_CUES for w in found):
        return None
    field_name = (_mentioned_field(found)
                  or (draft["checking"][0] if draft["checking"] else None)
                  or (draft["spelled"] if draft["spelled"] in _CORRECTABLE else None)
                  or "name")
    return {"answer": "spell_word", "updates": {}, "index": index,
            "field": field_name, "spell_field": None}


def _mark_unsure(draft: dict[str, Any], changes: list[tuple[str, str]],
                 confidence: float | None, *, spelled: str | None = None) -> None:
    """Remember which names were heard by voice with doubt. Typed values, and
    values spelled out letter by letter, are not in doubt."""
    threshold = get_settings().voice_spell_check_below_confidence
    for key, _value in changes:
        field_name = "contact_name" if key == "contact" else key
        if field_name not in _SPELLABLE:
            continue
        doubtful = (confidence is not None and confidence < threshold
                    and field_name != spelled)
        if doubtful and field_name not in draft["unsure"]:
            draft["unsure"].append(field_name)
        elif not doubtful and field_name in draft["unsure"]:
            draft["unsure"].remove(field_name)


def _spell_check(draft: dict[str, Any]) -> list[str] | None:
    fields = [f for f in _SPELLABLE if f in draft["unsure"] and _field_value(draft, f)]
    draft["unsure"] = []
    if not fields:
        return None
    draft["checking"] = fields
    draft["spell_rejected"] = False
    spelled = [f"{_field_value(draft, f)} is spelled {spell_out(_field_value(draft, f))}."
               for f in fields]
    return ["Before I create it, let me check the spelling.", *spelled,
            _ask(draft, STAGE_SPELLCHECK, "Is that right?", CHIPS_SPELLCHECK)]


async def vocabulary_hint(db: AsyncSession, ctx: OrgContext,
                          session_id: str | None) -> str | None:
    """Names Whisper should expect in this organisation's voice turns, most
    important first: "<people>. Clients: <…>. Cities: <…>."

    - The people who can own a lead: without them "Asha Rao" was heard as "a
      show-row" (measured).
    - The clients most recently worked on, and cities: measured 2026-09-17 on
      63 real recordings, adding them took names heard exactly right from 66%
      to 74% on turbo and to 82% on large-v3, with no extra delay.

    Deliberately NOT the unfinished client's own name — a misheard "Bal Bavin"
    in the prompt would pull a spoken correction back towards the mistake.
    Whisper keeps only the end of an over-long prompt; stt._fit_prompt cuts
    from the end instead, so cities are dropped first and people last."""
    people = [u.name for u in await people_who_work_leads(db, ctx.org_id) if u.name]
    recent = (
        await db.execute(
            select(Lead.name, Lead.city)
            .where(Lead.org_id == ctx.org_id)
            .order_by(Lead.last_activity_at.desc())
            .limit(HINT_CLIENTS * 2)
        )
    ).all()
    clients = list(dict.fromkeys(name.strip() for name, _city in recent
                                 if name and name.strip()))[:HINT_CLIENTS]
    cities = list(dict.fromkeys([city.strip() for _name, city in recent
                                 if city and city.strip()] + list(HINT_CITIES)))

    parts = []
    if people:
        parts.append(_hint_list(list(dict.fromkeys(people)), HINT_PEOPLE_CHARS) + ".")
    if clients:
        parts.append("Clients: " + _hint_list(clients, HINT_CHARS) + ".")
    parts.append("Cities: " + _hint_list(cities, HINT_CHARS) + ".")
    hint = " ".join(parts)
    if len(hint) > HINT_CHARS:
        hint = hint[:HINT_CHARS].rsplit(",", 1)[0].rstrip(" .") + "."
    return hint


def _hint_list(items: list[str], limit: int) -> str:
    """Comma-joined, cut before the first item that would pass `limit`."""
    kept: list[str] = []
    size = 0
    for item in items:
        size += len(item) + 2
        if kept and size > limit:
            break
        kept.append(item)
    return ", ".join(kept)


# ── reading the person's reply ───────────────────────────────────────────────

_INTERPRET_PROMPT = """You help a salesperson add a new client record by talking. Read their latest reply and return JSON.

What the record holds so far: {draft}
The question they were just asked: "{question}"
Their reply: "{text}"

Include a field ONLY if this reply gives or corrects it. Never guess, never repeat a value that is not changing, never invent one.
Fields: name (the client organisation), owner (the colleague who should own it: copy the name exactly as the user said it, even when it is not one of the names offered — never swap in a similar name), city, source (where the lead came from), website, notes, contact_name, contact_title, contact_phone, contact_email.
open_now: true if they want the client opened straight away instead of starting in cold calling, false if they want it to start in cold calling; leave it out otherwise.
Write an email address the way it is written (anita@acme.com), even when it was said as "anita at acme dot com".
Write names and places in English letters. If they were said in another language or script, transliterate them; never translate a proper name.
If the user spells a value letter by letter or corrects its spelling ("Bhawan with a W, not a V"), apply that to the current value and return the whole corrected value.

"answer" says what the reply does:
- "yes": agrees with the question asked, e.g. accepts a suggested owner, or says to create the record now
- "no": declines the question without giving details, e.g. "no", "nothing else", "no thanks"
- "skip": refuses or postpones answering, e.g. "skip this", "later"
- "delegate": leaves the choice to the assistant, e.g. "you decide", "whatever you want"
- "cancel": abandons this new client altogether
- "spell": asks the assistant to spell a value; also set "spell_field" to one of name, owner, city, source, website, notes, contact_name
- "values": only gives or corrects details
- "other_request": asks about or for something else, including adding a different client
- "unclear": none of these

The user may speak English, Hindi or Kannada, or mix them."""

_INTERPRET_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "enum": sorted(_ANSWERS)},
        "spell_field": {"type": "string"},
        "open_now": {"type": "boolean"},
        **{name: {"type": "string"} for name in _READ_FIELDS},
    },
    "required": ["answer"],
}


async def _interpret(db: AsyncSession, ctx: OrgContext, draft: dict[str, Any],
                     text: str) -> dict[str, Any]:
    prompt = _INTERPRET_PROMPT.format(
        draft=json.dumps(_public(draft, ctx), ensure_ascii=False),
        question=draft["question"][:600], text=text[:1500],
    )
    try:
        data = await get_model_layer().generate_json(
            purpose="client_draft.interpret", tier=TIER_FAST,
            org_id=ctx.org_id, user_id=ctx.user_id,
            messages=[{"role": "user", "content": prompt}],
            json_schema=_INTERPRET_SCHEMA, temperature=0.0, max_tokens=400,
        )
    except AppError:
        raise  # a spent budget must say so, not read as "unclear"
    except Exception:  # noqa: BLE001 — an unreadable reply is asked again
        logger.exception("Could not read the reply to the client draft")
        data = {}
    if not isinstance(data, dict):
        data = {}
    answer = str(data.get("answer") or "").strip().lower()
    updates = {f: _clean(data.get(f)) for f in _READ_FIELDS if _clean(data.get(f))}
    if answer not in _ANSWERS:
        answer = "values" if updates else "unclear"
    open_now = data.get("open_now") if isinstance(data.get("open_now"), bool) else None
    return {"answer": answer, "updates": updates,
            "spell_field": _clean(data.get("spell_field")), "open_now": open_now}


async def _read_reply(db: AsyncSession, ctx: OrgContext, draft: dict[str, Any],
                      text: str) -> dict[str, Any]:
    found = confirmations.words(text)
    stage = draft["stage"]

    def reading(answer: str, **updates: str) -> dict[str, Any]:
        return {"answer": answer, "updates": updates, "spell_field": None}

    if _is(found, _CANCEL) or " ".join(found) in ("never mind", "nevermind"):
        return reading("cancel")
    spelled = _letters_reading(draft, text, found)
    if spelled is not None:
        return spelled
    if stage == STAGE_OPEN_CHOICE and _is(found, _COLD_START):
        return {**reading("no"), "open_now": False}
    if stage == STAGE_OPEN_CHOICE and _is(found, _OPEN_NOW):
        return {**reading("yes"), "open_now": True}
    if ctx.role == Role.SALES_LEAD.value and draft.get("open_now") is not None:
        # A sales lead changing their mind at any later step.
        if _is(found, _COLD_SWITCH):
            return {**reading("no"), "open_now": False}
        if _is(found, _OPEN_NOW):
            return {**reading("yes"), "open_now": True}
    said_email, email_alone = (
        _email_parts(text)
        if draft.get("open_now") or stage == STAGE_OPEN_CHOICE else (None, False))
    if said_email and email_alone and stage in (STAGE_OPEN_CONTACT, STAGE_EMAIL_CHECK):
        return reading("values", contact_email=said_email)
    if stage == STAGE_EMAIL_CHECK and not said_email:
        # Only the domain corrected ("No, it is not right. At the rate
        # gmail.com." -- live, 7 Oct 2026): keep the name part, swap the domain.
        current = (draft["contact"] or {}).get("email") or ""
        domain = _domain_in(text)
        if domain and "@" in current and domain != current.split("@", 1)[1]:
            return reading("values",
                           contact_email=f"{current.split('@', 1)[0]}@{domain}")
    if stage in (STAGE_OWNER, STAGE_SUGGESTED):
        if _is(found, _SELF):
            return reading("values", owner="me")
        if _is(found, _DELEGATE):
            return reading("delegate")
        if _is(found, _SKIP):
            return reading("skip")
        if _is(found, _SOMEONE_ELSE):
            return reading("no")
        if (stage == STAGE_OWNER and 0 < len(found) <= 3
                and confirmations.classify_reply(text) is None):
            # A bare name: "Rahul", "Priya Nair". A plain yes or no is never
            # one: "Houdu maadi" ("yes, do it") used to be looked up as a
            # person and came back "I couldn't find anyone called Houdu
            # Maddi" (21 Sep 2026).
            said = text.strip().strip(".!?,;:")
            match, problem = await _resolve_owner(db, ctx, said)
            if match is not None:
                return reading("values", owner=match[1] if match[0] != ctx.user_id else "me")
            if problem is not None and problem.get("suggest"):
                # Only resembles someone ("Ria Nair"): keep the words as said,
                # so the question is asked — a model would "fix" the name.
                return reading("values", owner=said)
    if stage in (STAGE_CONFIRM, STAGE_SPELLCHECK, STAGE_DUPLICATE,
                 STAGE_EMAIL_CHECK) and _is(found, _CREATE):
        return reading("yes")
    if stage == STAGE_OPTIONAL and (_is(found, _NOTHING) or _is(found, _SKIP)
                                    or " ".join(found) in ("thats all", "thats it")):
        return reading("no")
    verdict = confirmations.classify_reply(text)
    if verdict == confirmations.YES:
        return reading("yes")
    if verdict == confirmations.NO:
        return reading("no")
    result = await _interpret(db, ctx, draft, text)
    # Open or cold calling only as the person said it (last one wins).
    result["open_now"] = _choice_in_words(found)
    if said_email:
        # The address in the person's own words, not the model's copy of it.
        result["updates"]["contact_email"] = said_email
        if result["answer"] in ("other_request", "unclear"):
            result["answer"] = "values"
    # "The second word is wrong" gave the model nothing to change. Whatever
    # label it put on that — measured on the live model: "unclear" once, "no"
    # or "other_request" (which started a new client named "BHAVAN") on other
    # runs — a complaint about a numbered word with no new value is a request
    # for its letters, never a move on and never a different request.
    if not result["updates"] and result["answer"] not in ("spell", "cancel"):
        return _spelling_request(draft, found) or result
    return result


# ── applying what was said ───────────────────────────────────────────────────

async def _apply(db: AsyncSession, ctx: OrgContext, draft: dict[str, Any],
                 updates: dict[str, Any]) -> tuple[list[tuple[str, str]], dict | None]:
    """Write the new values into the draft. Returns what changed (in order) and
    at most one problem to put to the person."""
    changes: list[tuple[str, str]] = []
    problem: dict[str, Any] | None = None

    for key in _TEXT_FIELDS:
        value = _clean(updates.get(key))
        if key == "name" and value:
            value = _client_name_only(value)
        if value is None or value == draft.get(key):
            continue
        if key == "name" and not NAME_MIN <= len(value) <= NAME_MAX:
            problem = {"about": "other", "candidates": [],
                       "text": f"That name is too long — {NAME_MAX} characters at most."}
            continue
        draft[key] = value
        changes.append((key, value))

    person = {k: _clean(updates.get(f"contact_{k}")) for k in _CONTACT_KEYS}
    if draft.get("open_now") and person.get("email"):
        # An open lead's email is the address it will be written to: checked
        # here, never stored when it is not an address (7 Oct 2026).
        written = _email_form(person["email"])
        if lead_service.looks_like_email(written):
            person["email"] = written
        else:
            problem = {"about": "other", "candidates": [],
                       "text": f"{person['email']} doesn't look like an email address."}
            person["email"] = None
    contact_name = _clean(updates.get("contact_name"))
    if contact_name or any(person.values()):
        current = dict(draft["contact"] or {})
        if contact_name:
            current["name"] = contact_name
        current.update({k: v for k, v in person.items() if v})
        if current.get("name"):
            merged = {"name": current["name"],
                      **{k: current.get(k) for k in _CONTACT_KEYS}}
            if merged != draft["contact"]:
                if merged.get("email") != (draft["contact"] or {}).get("email"):
                    draft["email_confirmed"] = False
                draft["contact"] = merged
                changes.append(("contact", merged["name"]))
        else:
            problem = problem or {"about": "other", "candidates": [],
                                  "text": "What is the contact person's name?"}

    hint = _clean(updates.get("owner"))
    if hint and draft["owner_id"] and hint.strip().lower() == (
            _public(draft, ctx)["owner"] or "").lower():
        # The reading model is shown the record with the owner as "you" (or
        # the owner's name) and sometimes copies it back. That is the value
        # already there, not a change -- and looked up as a person, "you"
        # found nobody and looped the open-contact step (live, 12 Oct 2026).
        hint = None
    if hint:
        found, issue = await _resolve_owner(db, ctx, hint)
        if found is not None and draft.get("open_now") and found[0] != ctx.user_id:
            # An open lead is owned by the sales lead who opens it (7 Oct 2026).
            problem = {"about": "other", "candidates": [],
                       "text": f"An open lead is owned by you. Say cold calling if "
                               f"{found[1]} should own it."}
        elif found is not None and found[0] != draft["owner_id"]:
            draft["owner_id"], draft["owner_name"] = found
            changes.append(("owner", found[1]))
        elif issue is not None:
            problem = {"about": "owner", **issue}
    return changes, problem


def _ack(draft: dict[str, Any], ctx: OrgContext, changes: list[tuple[str, str]],
         *, without_owner: bool = False) -> str:
    items = [(k, v) for k, v in changes if not (without_owner and k == "owner")]
    if not items:
        return ""
    spelled = draft.get("spelled")
    if len(items) == 1 and spelled and items[0][0] == (
        "contact" if spelled == "contact_name" else spelled
    ):
        value = items[0][1]
        # One text for screen and voice: measured 2026-09-15, Kokoro reads
        # "B-A-L, B-H-A-V-A-N" letter by letter with a pause between words.
        return f"Got it — it's now spelled {spell_out(value)}."
    said = []
    for key, value in items:
        if key == "notes":
            said.append("the note")
        elif key == "owner" and draft["owner_id"] == ctx.user_id:
            said.append("you as the owner")
        else:
            said.append(value)
    return f"Got it, {_join_and(said)}."


def _still_owner(draft: dict[str, Any], ctx: OrgContext) -> str:
    if draft["owner_id"] == ctx.user_id:
        return "You still own it."
    return f"{draft['owner_name']} still owns it."


def _owner_ack(draft: dict[str, Any], ctx: OrgContext) -> str:
    if draft["owner_id"] == ctx.user_id:
        return "Okay, you'll own it."
    return f"Okay, {draft['owner_name']} will own it."


def _choose_open(draft: dict[str, Any], ctx: OrgContext, choice: bool) -> str:
    """Record the sales lead's answer. Open: they own it (7 Oct 2026)."""
    draft["open_now"] = choice
    if not choice:
        if draft.get("owner_forced"):
            draft["owner_id"] = draft["owner_name"] = None
            draft["owner_forced"] = False
        return "Okay, it starts in cold calling."
    said = ""
    if draft["owner_id"] and draft["owner_id"] != ctx.user_id:
        said = f"An open lead is owned by you, so {draft['owner_name']} won't own it."
    draft["owner_id"], draft["owner_name"] = ctx.user_id, ctx.name or ctx.email
    draft["owner_forced"] = True
    return said


def _contact_question(draft: dict[str, Any]) -> str | None:
    contact = draft["contact"] or {}
    if not contact.get("name"):
        return (f"Who is the contact at {draft['name']}? Tell me their name, "
                "designation and email address. A phone number is optional.")
    if not contact.get("title"):
        return f"What is {contact['name']}'s designation?"
    if not contact.get("email"):
        return f"What is {contact['name']}'s email address?"
    return None


def _ask_email_check(draft: dict[str, Any]) -> str:
    email = (draft["contact"] or {}).get("email") or ""
    return _ask(draft, STAGE_EMAIL_CHECK,
                f"Before I create it, let me check the email: {email} is spelled "
                f"{spell_email(email)}. Is that right?", CHIPS_SPELLCHECK)


# ── asking ───────────────────────────────────────────────────────────────────

def _ask(draft: dict[str, Any], stage: str, question: str, candidates: list[str]) -> str:
    draft["stage"], draft["question"], draft["candidates"] = stage, question, candidates
    return question


async def _ask_owner(db: AsyncSession, ctx: OrgContext, draft: dict[str, Any],
                     *, then: bool = False) -> str:
    options = [u for u in await _owner_options(db, ctx)
               if u.id not in draft["declined"]]
    self_ok = ctx.user_id not in draft["declined"]
    lead_in = "Who should own it then?" if then else "Who should own it?"
    if not options:
        if not self_ok:
            return _ask(draft, STAGE_OWNER, f"{lead_in} Tell me their name.", [])
        draft["suggestion_id"] = ctx.user_id
        draft["suggestion_name"] = ctx.name or ctx.email
        _ask(draft, STAGE_SUGGESTED, "Shall I make you the owner?", CHIPS_SUGGESTED)
        return f"{lead_in} Shall I make you the owner?"
    shown = [u.name or u.email for u in options[:OWNER_CHOICES_SPOKEN]]
    spoken = shown + (["someone else"] if len(options) > OWNER_CHOICES_SPOKEN else [])
    spoken += ["you"] if self_ok else []
    return _ask(draft, STAGE_OWNER, f"{lead_in} {_join_or(spoken)}?",
                shown + (["Me"] if self_ok else []))


async def _suggest_owner(db: AsyncSession, ctx: OrgContext, draft: dict[str, Any]) -> str | None:
    options = [u for u in await _owner_options(db, ctx)
               if u.id not in draft["declined"]]
    if options:
        user = options[0]
        draft["suggestion_id"], draft["suggestion_name"] = user.id, user.name or user.email
        return _ask(draft, STAGE_SUGGESTED,
                    f"Shall I give it to {draft['suggestion_name']}?", CHIPS_SUGGESTED)
    if ctx.user_id not in draft["declined"]:
        draft["suggestion_id"], draft["suggestion_name"] = ctx.user_id, ctx.name or ctx.email
        return _ask(draft, STAGE_SUGGESTED, "Shall I make you the owner?", CHIPS_SUGGESTED)
    return None


async def _take_suggestion(db: AsyncSession, ctx: OrgContext, draft: dict[str, Any]) -> bool:
    if not draft["suggestion_id"] and await _suggest_owner(db, ctx, draft) is None:
        return False
    draft["owner_id"], draft["owner_name"] = draft["suggestion_id"], draft["suggestion_name"]
    return True


def _optional_question(draft: dict[str, Any]) -> str | None:
    left = [key for key in OPTIONAL if not draft[key]]
    if draft.get("open_now") and not (draft["contact"] or {}).get("phone"):
        left = ["phone number"] + left
    if not left:
        return None
    items = left[0] if len(left) == 1 else ", ".join(left[:-1]) + " or " + left[-1]
    article = "" if left[0] == "notes" else "a "
    plural = len(left) > 1 or left == ["notes"]
    return (f"Do you want to add {article}{items}? "
            f"{'They are' if plural else 'It is'} optional.").replace(
        "They are optional", "They're optional").replace("It is optional", "It's optional")


async def _read_back(db: AsyncSession, ctx: OrgContext, draft: dict[str, Any]) -> str:
    owner = "you" if draft["owner_id"] == ctx.user_id else draft["owner_name"]
    line = f"So: {draft['name']}"
    if draft["city"]:
        line += f" in {draft['city']}"
    line += f", owned by {owner}"
    contact = draft["contact"]
    if contact:
        about = [contact[k] for k in _CONTACT_KEYS if contact.get(k)]
        line += f", with {contact['name']}" + (f" ({', '.join(about)})" if about else "")
        line += " as the main contact"
    line += "."
    if draft.get("open_now"):
        line += " It will be opened straight away."
    for key, label in (("address", "Address"), ("region", "Region"),
                       ("source", "Source"), ("website", "Website"),
                       ("notes", "Note")):
        if draft[key]:
            line += f" {label}: {_sentence(draft[key])}"
    similar = (await matching_clients(db, ctx.org_id, draft["name"]))[:SIMILAR_LIMIT]
    if similar:
        owners = await names_by_id(db, ctx.org_id,
                                   {l.owner_id for l in similar if l.owner_id})
        on_file = "; ".join(
            f"{l.name} ({_role_label(l.state)}"
            + (f", owned by {owners[l.owner_id]}" if l.owner_id in owners else "") + ")"
            for l in similar
        )
        line += f" Already on file with a similar name: {on_file}."
    return f"{line} Anything else, or shall I create it?"


async def _same_client_on_file(db: AsyncSession, ctx: OrgContext,
                               name: str) -> Lead | None:
    """A client already on file under this very name, or None.

    Not merely a similar one: the read-back mentions those. This is the one
    that makes a second record of the same school, which is what people ask
    to be stopped from doing."""
    wanted = " ".join(_words(name))
    for lead in await matching_clients(db, ctx.org_id, name):
        if _similar(" ".join(_words(lead.name)), wanted) >= DUPLICATE_SIMILARITY:
            return lead
    return None


async def _advance(db: AsyncSession, ctx: OrgContext, draft: dict[str, Any]) -> str:
    """Ask the next thing still open, in the fixed order."""
    if not draft["name"]:
        return _ask(draft, STAGE_NAME, "What is the client called?", [])
    if draft.get("duplicate_checked_for") != draft["name"]:
        # Asked once per name, and again if the name changes.
        draft["duplicate_checked_for"] = draft["name"]
        existing = await _same_client_on_file(db, ctx, draft["name"])
        if existing is not None and (lead_service.normalise_name(existing.name)
                                     == lead_service.normalise_name(draft["name"])):
            # Exactly the same name: not allowed any more (26 Sep 2026). The
            # rest of the draft is kept; only a telling-apart name is asked.
            said = await lead_service.duplicate_name_message(db, existing)
            draft["name"] = None
            draft["duplicate_checked_for"] = None
            return _ask(draft, STAGE_NAME,
                        said.replace(" Open that one instead, or use a name",
                                     " If this is a different client, tell me a name"),
                        [])
        if existing is not None:
            owners = await names_by_id(db, ctx.org_id,
                                       {existing.owner_id} if existing.owner_id else set())
            owner = owners.get(existing.owner_id)
            about = f"{existing.name} is already on file ({_role_label(existing.state)}"
            about += f", owned by {owner})." if owner else ")."
            return _ask(draft, STAGE_DUPLICATE,
                        f"{about} Do you want to add another one with this name?",
                        CHIPS_DUPLICATE)
    if ctx.role == Role.SALES_LEAD.value and draft.get("open_now") is None:
        return _ask(draft, STAGE_OPEN_CHOICE,
                    f"Do you want to open {draft['name']} straight away, or start "
                    "it in cold calling? To open it now I'll need a contact there.",
                    CHIPS_OPEN_CHOICE)
    if draft.get("open_now"):
        question = _contact_question(draft)
        if question is not None:
            return _ask(draft, STAGE_OPEN_CONTACT, question, [])
    if not draft["owner_id"]:
        return await _ask_owner(db, ctx, draft)
    optional = _optional_question(draft)
    if not draft["asked_optional"] and optional:
        draft["asked_optional"] = True
        return _ask(draft, STAGE_OPTIONAL, optional, CHIPS_OPTIONAL)
    draft["asked_optional"] = True
    draft["sure_asked"] = False
    return _ask(draft, STAGE_CONFIRM, await _read_back(db, ctx, draft), CHIPS_CONFIRM)


async def _respond(db: AsyncSession, ctx: OrgContext, session_id: str,
                   row: AssistantPendingAction | None, draft: dict[str, Any],
                   parts: list[str]) -> confirmations.Outcome:
    reply = " ".join(part for part in parts if part)
    await confirmations.save(db, ctx, session_id, kind=KIND, agent=AGENT,
                             payload=draft, summary=draft["question"], row=row)
    details = {"kind": "client_draft", **_public(draft, ctx)}
    action = {
        "tool": KIND, "args": {"stage": draft["stage"]}, "ok": False,
        "outcome": "needs_confirmation", "error": reply, "question": reply,
        "candidates": list(draft["candidates"]), "details": details,
    }
    return confirmations.Outcome(reply=reply, actions=[action])


def _dropped(draft: dict[str, Any]) -> confirmations.Outcome:
    return confirmations.Outcome(
        reply=f"Okay, I've dropped {_title(draft)}. Nothing was created.")


# ── the flow ─────────────────────────────────────────────────────────────────

async def start(runtime: Any, values: dict[str, Any]) -> NeedsConfirmationError:
    """Begin (or restart) a client in this conversation from what the person
    first said. Returns the question to raise as the tool's answer."""
    db, ctx = runtime.db, runtime.ctx
    if not has_permission(ctx.role, WORKS_LEADS):
        raise PermissionDeniedError(
            f"{_a(_role_label(ctx.role)).capitalize()} cannot add clients. A sales agent, "
            "sales lead or org admin can."
        )
    session_id = runtime.extra_context.get("session_id")
    if not session_id:
        raise ValidationFailedError(
            "Adding a client is a short conversation, and that only works inside "
            "an assistant chat. Nothing was created."
        )
    name = _clean(values.get("name"))
    if name and len(name) > NAME_MAX:
        raise ValidationFailedError(
            f"That name is too long for a client ({NAME_MAX} characters at most).")

    earlier = await confirmations.load(db, ctx, session_id)
    earlier_name = _load(earlier)["name"] if earlier is not None else None
    draft = _new_draft()
    said = (runtime.extra_context.get("_said_by_user") or [""])[-1]
    # The agent's open_now counts only when the person said "open" (7 Oct 2026).
    wants_open = (values.get("open_now") is True
                  and ctx.role == Role.SALES_LEAD.value
                  and _choice_in_words(confirmations.words(said)) is True)
    if wants_open:
        draft["open_now"] = True
        if email_in(said):
            # The address as the person said it, not the agent model's copy.
            values = {**values, "contact_email": email_in(said)}
    changes, problem = await _apply(db, ctx, draft, values)
    took_over = _choose_open(draft, ctx, True) if wants_open else ""
    if wants_open and problem is not None and problem["about"] == "owner":
        problem = None
    _mark_unsure(draft, changes, runtime.extra_context.get("_voice_confidence"))
    opening = "Sure."
    if earlier_name and earlier_name != draft["name"]:
        opening = f"Sure — that replaces the unfinished {earlier_name}."

    parts: list[str] = [opening]
    if took_over:
        parts.append(took_over)
    if problem is not None and problem["about"] == "owner" and draft["name"]:
        if problem.get("suggest"):
            draft["suggestion_id"], draft["suggestion_name"] = problem["suggest"]
            parts.append(_ask(draft, STAGE_SUGGESTED, problem["text"], CHIPS_SUGGESTED))
        elif problem["candidates"]:
            parts.append(_ask(draft, STAGE_OWNER, problem["text"], problem["candidates"]))
        else:
            parts += [problem["text"], await _ask_owner(db, ctx, draft)]
    else:
        if problem is not None:
            parts.append(problem["text"])
        question = await _advance(db, ctx, draft)
        if draft["owner_id"] and draft["stage"] not in (
                STAGE_CONFIRM, STAGE_OPEN_CHOICE, STAGE_OPEN_CONTACT):
            # The read-back names the owner itself; anywhere else, say it now.
            parts.append("You'll own it." if draft["owner_id"] == ctx.user_id
                         else f"{draft['owner_name']} will own it.")
        parts.append(question)
    outcome = await _respond(db, ctx, session_id, None, draft, parts)
    action = outcome.actions[0]
    return NeedsConfirmationError(outcome.reply, candidates=action["candidates"],
                                  details=action["details"])


async def handle(db: AsyncSession, ctx: OrgContext, row: AssistantPendingAction,
                 text: str, context: dict[str, Any] | None = None
                 ) -> confirmations.Outcome | None:
    draft = _load(row)
    session_id = row.session_id
    # Set by voice mode only (never by the typed endpoint): how sure Whisper was.
    confidence = (context or {}).get("_voice_confidence")
    if not has_permission(ctx.role, WORKS_LEADS):
        await confirmations.drop(db, row)
        return confirmations.Outcome(
            reply="Your role can no longer add clients, so nothing was created.")
    if draft.get("open_now") and ctx.role != Role.SALES_LEAD.value:
        # No longer a sales lead (7 Oct 2026): the client can still be added,
        # in cold calling, rather than refusing every "create it".
        _choose_open(draft, ctx, False)
        draft["paused"] = False
        return await _respond(db, ctx, session_id, row, draft, [
            "Only a sales lead can open a lead straight away, so it will start in "
            "cold calling.", await _advance(db, ctx, draft)])

    if draft["paused"]:
        verdict = confirmations.classify_reply(text)
        if verdict == confirmations.YES:
            draft["paused"] = False
            return await _respond(db, ctx, session_id, row, draft,
                                  [f"Okay, back to {_title(draft)}.", draft["question"]])
        if verdict == confirmations.NO:
            await confirmations.drop(db, row)
            return _dropped(draft)

    reading = await _read_reply(db, ctx, draft, text)
    answer = reading["answer"]
    if answer == "other_request":
        return None
    draft["paused"] = False
    if answer == "cancel":
        await confirmations.drop(db, row)
        return _dropped(draft)
    if answer == "spell":
        return await _spell(db, ctx, row, draft, reading["spell_field"] or "name")
    say = lambda *parts: _respond(db, ctx, session_id, row, draft, list(parts))  # noqa: E731
    if answer == "which_word":
        draft["spell_letters"] = reading["letters"]
        draft["spelled"] = reading["field"]
        count = len((_field_value(draft, reading["field"]) or "").split())
        choices = [_ORDINAL_NAMES[i] for i in range(min(count, 5))]
        tail = f" — the {_join_or(choices)}?" if len(choices) > 1 else "?"
        return await say(f"Which word should be {spell_out(reading['letters'])}{tail}")
    if answer == "spell_word":
        draft["spell_word"] = reading["index"]
        draft["spelled"] = reading["field"]
        which = _ORDINAL_NAMES.get(reading["index"], "wrong")
        return await say(f"Sure — spell the {which} word for me, letter by letter.")

    if reading.get("spelled_field"):
        draft["spelled"] = reading["spelled_field"]
    changes, problem = await _apply(db, ctx, draft, reading["updates"])
    if changes:
        draft["spell_word"] = draft["spell_letters"] = None
    _mark_unsure(draft, changes, confidence, spelled=reading.get("spelled_field"))
    # A spelling stays "open" for correction until some other value changes.
    spelled_key = {"contact_name": "contact"}.get(draft["spelled"], draft["spelled"])
    if changes and any(key != spelled_key for key, _ in changes):
        draft["spelled"] = None

    if problem is not None:
        ack = _ack(draft, ctx, changes)
        if problem["about"] == "owner":
            if problem.get("suggest"):
                draft["suggestion_id"], draft["suggestion_name"] = problem["suggest"]
                return await say(ack, _ask(draft, STAGE_SUGGESTED, problem["text"],
                                           CHIPS_SUGGESTED))
            if problem["candidates"]:
                return await say(ack, _ask(draft, STAGE_OWNER, problem["text"],
                                           problem["candidates"]))
            if draft["owner_id"]:
                # Whatever else this reply gave was kept, so ask what is
                # next rather than the question it has just answered.
                return await say(ack, problem["text"], _still_owner(draft, ctx),
                                 await _advance(db, ctx, draft) if changes
                                 else draft["question"])
            return await say(ack, problem["text"], await _ask_owner(db, ctx, draft))
        return await say(ack, problem["text"], draft["question"])

    stage = draft["stage"]
    owner_changed = any(key == "owner" for key, _ in changes)

    choice = reading.get("open_now")
    if (choice is not None and ctx.role == Role.SALES_LEAD.value
            and stage not in (STAGE_OPEN_CHOICE, STAGE_OPEN_CONTACT)
            and draft.get("open_now") is not None and choice != draft.get("open_now")):
        # Changed their mind at a later step: open now, or cold calling after all.
        return await say(_ack(draft, ctx, changes), _choose_open(draft, ctx, choice),
                         await _advance(db, ctx, draft))

    if stage == STAGE_OPEN_CHOICE:
        ack = _ack(draft, ctx, changes)
        choice = reading.get("open_now")
        if choice is None and answer in ("yes", "no"):
            choice = answer == "yes"
        if choice is None:
            if changes:
                return await say(ack, draft["question"])
            return await say("Sorry, I didn't catch that.", draft["question"])
        return await say(ack, _choose_open(draft, ctx, choice),
                         await _advance(db, ctx, draft))

    if stage == STAGE_OPEN_CONTACT:
        ack = _ack(draft, ctx, changes)
        if reading.get("open_now") is False:
            return await say(_choose_open(draft, ctx, False), await _advance(db, ctx, draft))
        if changes:
            if draft["recheck_email"] and (draft["contact"] or {}).get("email"):
                draft["recheck_email"] = False
                return await say(ack, _ask_email_check(draft))
            return await say(ack, await _advance(db, ctx, draft))
        if _contact_question(draft) is None and not draft["recheck_email"]:
            # Nothing new, but nothing missing either: the person repeated a
            # contact this step already holds. Asking for it again was a loop
            # (live, 12 Oct 2026), so move on.
            return await say(await _advance(db, ctx, draft))
        if answer in ("no", "skip", "delegate", "yes"):
            return await say("To open it now I need the contact's name, designation "
                             "and email. Say cold calling if you'd rather start it "
                             "there.", draft["question"])
        return await say("Sorry, I didn't catch that.", draft["question"])

    if stage == STAGE_EMAIL_CHECK:
        if changes:
            if (draft["contact"] or {}).get("email") and not draft["email_confirmed"]:
                return await say(_ack(draft, ctx, changes), _ask_email_check(draft))
            return await say(_ack(draft, ctx, changes), await _advance(db, ctx, draft))
        if answer == "yes":
            draft["email_confirmed"] = True
            check = _spell_check(draft)
            if check is not None:
                return await say(*check)
            return await _create(db, ctx, row, draft)
        if answer == "no" or set(confirmations.words(text)) & _NEGATIONS:
            # Said it is wrong but no new address could be read: ask for the
            # address itself rather than the same question again (the loop
            # seen live on 7 Oct 2026).
            draft["contact"] = {**(draft["contact"] or {}), "email": None}
            draft["recheck_email"] = True
            return await say(_ask(draft, STAGE_OPEN_CONTACT,
                                  "What is the right email address?", []))
        return await say("Sorry, I didn't catch that.", draft["question"])

    if stage == STAGE_NAME:
        if draft["name"]:
            return await say("Sure.", await _advance(db, ctx, draft))
        lead_in = "" if answer in ("unclear", "values") else "I need the client's name to add it."
        return await say(lead_in, draft["question"])

    if stage == STAGE_DUPLICATE:
        if changes:
            # They gave a different name (or other details) instead of an
            # answer: that is the answer. A new name is checked again.
            return await say(_ack(draft, ctx, changes), await _advance(db, ctx, draft))
        if answer == "yes":
            return await say(await _advance(db, ctx, draft))
        if answer == "no":
            await confirmations.drop(db, row)
            return _dropped(draft)
        return await say("Sorry, I didn't catch that.", draft["question"])

    if stage in (STAGE_OWNER, STAGE_SUGGESTED):
        others = _ack(draft, ctx, changes, without_owner=True)
        if owner_changed:
            return await say(_owner_ack(draft, ctx), others, await _advance(db, ctx, draft))
        takes_suggestion = (
            answer == "delegate"
            or (stage == STAGE_SUGGESTED and answer in ("yes", "skip"))
            or (stage == STAGE_OWNER and answer in ("skip", "no") and draft["pushed_back"])
        )
        if takes_suggestion and await _take_suggestion(db, ctx, draft):
            return await say(_owner_ack(draft, ctx), others, await _advance(db, ctx, draft))
        if stage == STAGE_OWNER and answer in ("skip", "no"):
            draft["pushed_back"] = True
            question = await _suggest_owner(db, ctx, draft)
            if question is not None:
                return await say(others, "The owner is the one who makes the cold calls, "
                                         "so it needs one.", question)
        if stage == STAGE_SUGGESTED and answer == "no":
            if draft["suggestion_id"]:
                draft["declined"].append(draft["suggestion_id"])
            draft["suggestion_id"] = draft["suggestion_name"] = None
            return await say(others, await _ask_owner(db, ctx, draft, then=True))
        lead_in = "" if others else "Sorry, I didn't catch who should own it."
        return await say(others, lead_in, draft["question"])

    if stage == STAGE_OPTIONAL:
        ack = _ack(draft, ctx, changes)
        if any(key in OPTIONAL or key in ("contact", "address", "region")
               for key, _ in changes):
            return await say(ack, await _advance(db, ctx, draft))
        if changes:
            return await say(ack, draft["question"])
        if answer in ("no", "skip", "delegate"):
            return await say("Okay.", await _advance(db, ctx, draft))
        if answer == "yes":
            return await say(_ask(draft, STAGE_OPTIONAL, "Sure — what would you like to add?",
                                  CHIPS_OPTIONAL))
        return await say("Sorry, I didn't catch that.", draft["question"])

    if stage == STAGE_SPELLCHECK:
        if changes:
            return await say(_ack(draft, ctx, changes), await _advance(db, ctx, draft))
        if answer == "yes" and not draft["spell_rejected"]:
            return await _create(db, ctx, row, draft)
        if answer == "no":
            draft["spell_rejected"] = True
            return await say(_ask(draft, STAGE_SPELLCHECK,
                                  "Which word is wrong? Tell me the word and spell it, "
                                  "letter by letter.", []))
        return await say("Sorry, I didn't catch that.", draft["question"])

    # STAGE_CONFIRM
    if changes:
        return await say(_ack(draft, ctx, changes), await _advance(db, ctx, draft))
    if answer == "yes":
        if draft.get("open_now") and not draft.get("email_confirmed"):
            return await say(_ask_email_check(draft))
        check = _spell_check(draft)
        if check is not None:
            return await say(*check)
        return await _create(db, ctx, row, draft)
    if answer == "no":
        if draft["sure_asked"]:
            await confirmations.drop(db, row)
            return _dropped(draft)
        draft["sure_asked"] = True
        return await say(_ask(draft, STAGE_CONFIRM,
                              f"Just to be sure — shall I create {draft['name']} now?",
                              CHIPS_CONFIRM))
    return await say("Sorry, I didn't catch that.",
                     _ask(draft, STAGE_CONFIRM, f"Shall I create {draft['name']} now?",
                          CHIPS_CONFIRM))


async def _spell(db: AsyncSession, ctx: OrgContext, row: AssistantPendingAction,
                 draft: dict[str, Any], field_name: str) -> confirmations.Outcome:
    field_name = field_name.lower().replace(" ", "_")
    if field_name in ("organisation", "organization", "client", "lead", "company"):
        field_name = "name"
    if field_name == "owner":
        value = ("you" if draft["owner_id"] == ctx.user_id else draft["owner_name"])
    elif field_name in ("contact", "contact_name"):
        field_name = "contact_name"
        value = (draft["contact"] or {}).get("name")
    else:
        value = draft.get(field_name) if field_name in _TEXT_FIELDS else None
    label = {"name": "name", "contact_name": "contact"}.get(field_name, field_name)
    if not value or value == "you":
        return await _respond(db, ctx, row.session_id, row, draft,
                              [f"There's no {label} to spell yet.", draft["question"]])
    draft["spelled"] = field_name
    return await _respond(db, ctx, row.session_id, row, draft, [
        f"{value} is spelled {spell_out(value)}.",
        draft["question"],
    ])


async def _create(db: AsyncSession, ctx: OrgContext, row: AssistantPendingAction,
                  draft: dict[str, Any]) -> confirmations.Outcome:
    """The person said to create it: everything is re-checked — a permission
    or an owner may have gone in the minutes since — and only then written."""
    if draft.get("open_now"):
        try:
            lead, saved = await lead_service.create_open_lead(
                db, ctx, name=draft["name"], contact=draft["contact"],
                address=draft["address"], city=draft["city"], region=draft["region"],
                website=draft["website"], source=draft["source"], notes=draft["notes"],
                audit_detail={"via": "assistant"},
            )
        except (ValidationFailedError, PermissionDeniedError) as exc:
            # Refused before anything was written (create_open_lead checks
            # first), so the draft is kept and the reason is the reply.
            return await _respond(db, ctx, row.session_id, row, draft,
                                  [exc.message, draft["question"]])
        await confirmations.drop(db, row)
        result = {"lead_id": lead.id, "name": lead.name, "state": lead.state,
                  "owner_id": ctx.user_id, "owner": ctx.name or ctx.email,
                  "contact_id": saved.id}
        return confirmations.Outcome(
            reply=(f"Done — {lead.name} is added and opened. You own it, and "
                   f"{saved.name} is saved as the main contact."),
            actions=[{"tool": KIND, "args": _public(draft, ctx), "ok": True,
                      "result": result}])
    owner_id = draft["owner_id"] or ctx.user_id
    if owner_id != ctx.user_id:
        owner = (
            await db.execute(select(User).where(User.id == owner_id,
                                                User.org_id == ctx.org_id,
                                                User.is_active.is_(True)))
        ).scalar_one_or_none()
        if owner is None or not has_permission(owner.role, WORKS_LEADS):
            gone = draft["owner_name"] or "The owner you chose"
            draft["owner_id"] = draft["owner_name"] = None
            draft["declined"].append(owner_id)
            return await _respond(db, ctx, row.session_id, row, draft, [
                f"{gone} can no longer own clients, so I haven't created it.",
                await _ask_owner(db, ctx, draft),
            ])
    lead, owner_name = await lead_service.create_lead(
        db, ctx, name=draft["name"], owner_id=owner_id,
        address=draft["address"], city=draft["city"], region=draft["region"],
        website=draft["website"], source=draft["source"], notes=draft["notes"],
        audit_detail={"via": "assistant"},
    )
    saved = None
    if draft["contact"] and draft["contact"].get("name"):
        contact = draft["contact"]
        saved = await lead_service.add_contact(
            db, ctx, lead_id=lead.id, name=contact["name"], title=contact.get("title"),
            email=contact.get("email"), phone=contact.get("phone"), is_primary=True,
        )
    await confirmations.drop(db, row)
    owned = ("you own it" if owner_id == ctx.user_id
             else f"{owner_name} owns it and has been notified")
    reply = f"Done — {lead.name} is added and {owned}. It starts in cold calling."
    if saved is not None:
        reply += f" {saved.name} is saved as the main contact."
    result = {"lead_id": lead.id, "name": lead.name, "state": lead.state,
              "owner_id": owner_id, "owner": owner_name,
              "contact_id": saved.id if saved is not None else None}
    return confirmations.Outcome(reply=reply, actions=[{
        "tool": KIND, "args": _public(draft, ctx), "ok": True, "result": result,
    }])


class _ClientDraftFlow:
    async def handle(self, db, ctx, row, text, context=None):
        return await handle(db, ctx, row, text, context)

    async def pause(self, db, ctx, row):
        draft = _load(row)
        draft["paused"] = True
        await confirmations.save(db, ctx, row.session_id, kind=KIND, agent=AGENT,
                                 payload=draft, summary=draft["question"], row=row)
        return f"…and shall I continue with {_title(draft)}?"


confirmations.register_flow(KIND, _ClientDraftFlow())
