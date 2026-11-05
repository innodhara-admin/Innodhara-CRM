"""Shared entity resolvers used by agent tools.

Fuzzy, org-scoped lookups so a salesperson can say "Green Valley" instead of
pasting ids. **Ambiguity is asked about, never guessed** (finding F28).

The matching ladder
-------------------
Everything a person might type is tried in order of strength, and the FIRST
stage that matches anything decides the outcome — so an exact hit is never
diluted by a fuzzy one, and a loose stage only ever runs when nothing stronger
worked:

    exact id → exact name/code → exact email/phone → email/phone found INSIDE
    the hint → hint inside the stored name (what this file always did) →
    stored name inside the hint → significant-token overlap

The fifth and sixth stages are the point. Before F28 only "hint inside the
stored name" existed, so `Nair` found `Mrs. Nair` but
`EKAGHNI MUKHERJEE at Orchid International School` found nothing — the hint was
longer than the name and the reverse was never tried.

One match resolves. Several, or none, raise `NeedsConfirmationError`, which the
agent loop turns into a question the user is asked rather than a red failure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from sqlalchemy import func, or_, select

from app.ai.agents.base import AgentRuntime
from app.core.constants import ORG_ROLES
from app.core.exceptions import NeedsConfirmationError, NotFoundError
from app.models.demo import DemoTeam
from app.models.lead import Contact, Lead
from app.models.program import Program
from app.models.user import User

# How many rows a fuzzy stage may consider, and how many we name back to the
# user when we have to ask. Small on purpose: a question listing thirty people
# is not a question.
_CANDIDATE_LIMIT = 40
_ASK_LIMIT = 6

# Words that carry no identity. Dropping them is what lets "NAME at CLIENT"
# reduce to "NAME" generically, with no pattern-matching on the word "at" and
# no domain vocabulary anywhere.
_CONNECTOR_WORDS = frozenset({
    "a", "an", "the", "at", "in", "on", "of", "for", "from", "to", "and",
    "with", "our", "your", "their", "my", "his", "her", "its", "please",
    "about", "regarding", "re", "is", "are", "who", "mr", "mrs", "ms", "dr",
})

_WORD_RE = re.compile(r"[0-9a-z]+")
_EMAIL_RE = re.compile(r"[0-9a-z._%+-]+@[0-9a-z.-]+\.[a-z]{2,}")


def _words(text: str | None) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


def _significant(words: Sequence[str]) -> set[str]:
    """Words worth matching on: long enough to mean something, and not glue."""
    return {w for w in words if len(w) >= 3 and w not in _CONNECTOR_WORDS}


def _digits(text: str | None) -> str:
    return re.sub(r"\D", "", text or "")


def _run_of_words(haystack: list[str], needle: list[str]) -> bool:
    """True when `needle`'s words appear consecutively inside `haystack`.

    Word-bounded on purpose: a plain substring test would find the stored name
    "Ann" inside the word "announcement", and this stage is the one that reads
    a name out of a whole typed sentence."""
    if not needle or len(needle) > len(haystack):
        return False
    span = len(needle)
    return any(
        haystack[i : i + span] == needle
        for i in range(len(haystack) - span + 1)
    )


@dataclass(frozen=True)
class _Row:
    """One database row reduced to the things a person might type at it.

    `names` are full-strength identifiers (a person's name, a program code).
    `weak` are secondary ones (a job title) — matched, but kept out of the
    loosest stage, where a word like "operations" would over-reach.
    """

    row: Any
    names: tuple[str, ...]
    weak: tuple[str, ...] = ()
    addresses: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return self.names[0] if self.names else str(getattr(self.row, "id", ""))


def _stages(hint: str) -> list[Callable[[_Row], bool]]:
    """The ladder, strongest first, closed over one hint."""
    hint_l = hint.strip().lower()
    hint_words = _words(hint_l)
    hint_sig = _significant(hint_words)
    hint_digits = _digits(hint_l)
    hint_emails = set(_EMAIL_RE.findall(hint_l))

    def exact_id(c: _Row) -> bool:
        return bool(hint_l) and str(getattr(c.row, "id", "")).lower() == hint_l

    def exact_name(c: _Row) -> bool:
        return bool(hint_l) and any(
            (n or "").lower() == hint_l for n in c.names + c.weak
        )

    def exact_address(c: _Row) -> bool:
        for address in c.addresses:
            if not address:
                continue
            if address.lower() == hint_l:
                return True
            digits = _digits(address)
            if digits and len(digits) >= 7 and digits == hint_digits:
                return True
        return False

    def address_in_hint(c: _Row) -> bool:
        """The address is somewhere inside a longer phrase — "reply to
        priya@x.com about the quote". Before F28 email was compared with `==`,
        so it had to BE the whole hint."""
        for address in c.addresses:
            if not address:
                continue
            lowered = address.lower()
            if "@" in lowered:
                if lowered in hint_emails:
                    return True
            else:
                digits = _digits(lowered)
                if digits and len(digits) >= 7 and digits in hint_digits:
                    return True
        return False

    def hint_in_name(c: _Row) -> bool:
        """What this file has always done — kept verbatim, substring and all,
        so every lookup that worked before still works."""
        return bool(hint_l) and any(
            hint_l in (n or "").lower() for n in c.names + c.weak
        )

    def name_in_hint(c: _Row) -> bool:
        """The F28 case: the hint is a phrase and the name sits inside it."""
        return any(
            _run_of_words(hint_words, _words(n)) for n in c.names + c.weak
        )

    def token_overlap(c: _Row) -> bool:
        """Last resort — half of a stored name's meaningful words were typed.
        Names only: a job title here would match far too much."""
        for name in c.names:
            sig = _significant(_words(name))
            if sig and len(sig & hint_sig) / len(sig) >= 0.5:
                return True
        return False

    return [
        exact_id,
        exact_name,
        exact_address,
        address_in_hint,
        hint_in_name,
        name_in_hint,
        token_overlap,
    ]


def _match(hint: str, candidates: Sequence[_Row]) -> list[_Row]:
    """Walk the ladder; return everything the first productive stage found."""
    if not (hint or "").strip():
        return []
    for stage in _stages(hint):
        hits = [c for c in candidates if stage(c)]
        if hits:
            return hits
    return []


def _without(hint: str, *owned: str | None) -> str:
    """The hint with another entity's own words removed (F28 fix 2).

    "EKAGHNI MUKHERJEE at Orchid International School" minus the client's words
    is "ekaghni mukherjee". This runs as a **fallback stage, never as a
    pre-step**: a contact called "Mrs. Nair" at a client called "Nair
    Industries" would otherwise have their name deleted before matching. The
    raw hint always gets the full ladder first, so this can only ever find
    something extra — never take something away.
    """
    owned_words = set()
    for text in owned:
        owned_words |= set(_words(text))
    kept = [
        w for w in _words(hint)
        if w not in owned_words and w not in _CONNECTOR_WORDS
    ]
    return " ".join(kept) if _significant(kept) else ""


def _ask(question: str, candidates: Sequence[_Row]) -> NeedsConfirmationError:
    """Build the question. The candidates are named in the text *and* carried
    as data, so the model can ask in prose and the app can offer one tap."""
    labels = [c.label for c in candidates][:_ASK_LIMIT]
    return NeedsConfirmationError(question, candidates=labels)


def _resolve_one(
    hint: str,
    candidates: Sequence[_Row],
    *,
    empty_question: str,
    several_question: Callable[[str], str],
    none_question: Callable[[str], str],
    fallback: Sequence[_Row] = (),
) -> Any:
    """Shared outcome handling: one match wins, anything else is a question.

    `fallback` is what we offer when nothing matched at all — the rows worth
    naming so the user can pick instead of rephrasing blind. F28's own evidence
    was an error message that *listed the right person*; this makes that list
    the answer rather than the consolation."""
    term = (hint or "").strip()
    if not term:
        raise _ask(empty_question, fallback)
    matches = _match(term, candidates)
    if len(matches) == 1:
        return matches[0].row
    if matches:
        raise _ask(several_question(_names(matches)), matches)
    offered = list(fallback) or list(candidates)
    if not offered:
        raise NotFoundError(none_question(""))
    raise _ask(none_question(_names(offered)), offered)


def _names(rows: Sequence[_Row]) -> str:
    return ", ".join(r.label for r in rows[:_ASK_LIMIT])


def _name_conditions(column, hint: str) -> list[Any]:
    """Bounded fuzzy prefilter: the whole hint, or any meaningful word in it.

    A stored name that sits inside a typed phrase necessarily shares a word
    with it, so the word conditions are what make the new `name_in_hint` and
    `token_overlap` stages reachable from SQL without loading the table."""
    term = (hint or "").strip().lower()
    conditions = [func.lower(column).like(f"%{term}%")] if term else []
    conditions += [
        func.lower(column).like(f"%{word}%") for word in sorted(_significant(_words(term)))
    ]
    return conditions


async def resolve_lead(runtime: AgentRuntime, name_or_id: str) -> Lead:
    db, ctx = runtime.db, runtime.ctx
    term = (name_or_id or "").strip()
    recent = (
        await db.execute(
            select(Lead)
            .where(Lead.org_id == ctx.org_id)
            .order_by(Lead.last_activity_at.desc())
            .limit(_ASK_LIMIT)
        )
    ).scalars().all()
    fallback = [_Row(row=lead, names=(lead.name,)) for lead in recent]
    candidates: list[_Row] = []
    if term:
        conditions = _name_conditions(Lead.name, term)
        rows = (
            await db.execute(
                select(Lead)
                .where(Lead.org_id == ctx.org_id, or_(Lead.id == term, *conditions))
                .order_by(Lead.last_activity_at.desc())
                .limit(_CANDIDATE_LIMIT)
            )
        ).scalars().all()
        candidates = [_Row(row=lead, names=(lead.name,)) for lead in rows]
    return _resolve_one(
        term,
        candidates,
        empty_question=(
            "Which client do you mean?"
            + (f" Recently active: {_names(fallback)}." if fallback else "")
        ),
        several_question=lambda names: f"Several clients match '{term}': {names}. Which one?",
        none_question=lambda names: (
            f"No client matching '{term}' found."
            + (f" The ones I hold are: {names}. Which did you mean?" if names else "")
        ),
        fallback=fallback,
    )


async def resolve_user(runtime: AgentRuntime, name_or_email: str) -> User:
    db, ctx = runtime.db, runtime.ctx
    term = (name_or_email or "").strip()
    base = select(User).where(
        User.org_id == ctx.org_id,
        User.is_active.is_(True),
        User.role.in_([r.value for r in ORG_ROLES]),
    )
    fallback_rows = (await db.execute(base.limit(_ASK_LIMIT))).scalars().all()
    fallback = [_Row(row=u, names=(u.name,), addresses=(u.email,)) for u in fallback_rows]
    candidates: list[_Row] = []
    if term:
        conditions = _name_conditions(User.name, term)
        conditions += [
            func.lower(User.email).like(f"%{word}%")
            for word in sorted(_significant(_words(term)) | set(_EMAIL_RE.findall(term.lower())))
        ]
        rows = (
            await db.execute(base.where(or_(User.id == term, *conditions)).limit(_CANDIDATE_LIMIT))
        ).scalars().all()
        candidates = [_Row(row=u, names=(u.name,), addresses=(u.email,)) for u in rows]
    return _resolve_one(
        term,
        candidates,
        empty_question="Which person do you mean?",
        several_question=lambda names: f"Several people match '{term}': {names}. Which one?",
        none_question=lambda names: (
            f"No staff member matching '{term}'."
            + (f" The team here is: {names}. Who did you mean?" if names else "")
        ),
        fallback=fallback,
    )


async def resolve_program(runtime: AgentRuntime, code_or_name: str) -> Program:
    db, ctx = runtime.db, runtime.ctx
    term = (code_or_name or "").strip()
    base = select(Program).where(
        Program.org_id == ctx.org_id, Program.is_active.is_(True)
    )
    fallback_rows = (await db.execute(base.limit(_ASK_LIMIT))).scalars().all()
    fallback = [_Row(row=p, names=(p.code, p.name)) for p in fallback_rows]
    candidates: list[_Row] = []
    if term:
        conditions = _name_conditions(Program.name, term) + _name_conditions(Program.code, term)
        rows = (
            await db.execute(base.where(or_(*conditions)).limit(_CANDIDATE_LIMIT))
        ).scalars().all()
        # Code first: it is the identifier people quote, so it labels the ask.
        candidates = [_Row(row=p, names=(p.code, p.name)) for p in rows]
    return _resolve_one(
        term,
        candidates,
        empty_question="Which program do you mean?",
        several_question=lambda names: f"Several programs match '{term}': {names}. Which one?",
        none_question=lambda names: (
            f"No program matching '{term}'."
            + (f" We run: {names}. Which one did you mean?" if names else "")
        ),
        fallback=fallback,
    )


async def resolve_team(runtime: AgentRuntime, name: str) -> DemoTeam:
    db, ctx = runtime.db, runtime.ctx
    term = (name or "").strip()
    base = select(DemoTeam).where(DemoTeam.org_id == ctx.org_id)
    fallback_rows = (await db.execute(base.limit(_ASK_LIMIT))).scalars().all()
    fallback = [_Row(row=t, names=(t.name,)) for t in fallback_rows]
    candidates: list[_Row] = []
    if term:
        rows = (
            await db.execute(
                base.where(or_(DemoTeam.id == term, *_name_conditions(DemoTeam.name, term)))
                .limit(_CANDIDATE_LIMIT)
            )
        ).scalars().all()
        candidates = [_Row(row=t, names=(t.name,)) for t in rows]
    return _resolve_one(
        term,
        candidates,
        empty_question="Which demo team do you mean?",
        several_question=lambda names: f"Several demo teams match '{term}': {names}. Which one?",
        none_question=lambda names: (
            f"No demo team matching '{term}'."
            + (f" The teams are: {names}. Which one?" if names else "")
        ),
        fallback=fallback,
    )


async def resolve_contact(
    runtime: AgentRuntime, lead: Lead, contact_hint: str | None
) -> Contact:
    db, ctx = runtime.db, runtime.ctx
    q = select(Contact).where(Contact.org_id == ctx.org_id, Contact.lead_id == lead.id)
    contacts = (await db.execute(q)).scalars().all()
    if not contacts:
        raise NotFoundError(f"No contacts saved for {lead.name} yet")
    candidates = [
        _Row(
            row=c,
            names=(c.name,),
            weak=((c.title,) if c.title else ()),
            addresses=tuple(a for a in (c.email, c.phone) if a),
        )
        for c in contacts
    ]

    hint = (contact_hint or "").strip()
    if not hint:
        # No name given. A designated primary is a decision somebody made, so
        # honouring it is not a guess — but picking row zero out of several
        # unmarked contacts is, and F28's rule is ask, never guess: sending a
        # client email to the wrong person is worse than one more tap.
        primary = [c for c in contacts if c.is_primary]
        if primary:
            return primary[0]
        if len(contacts) == 1:
            return contacts[0]
        raise _ask(
            f"Who at {lead.name} should this go to? I have "
            f"{_names(candidates)} — and nobody is marked as the main contact.",
            candidates,
        )

    matches = _match(hint, candidates)
    # Fix 2: the hint with the client's own words taken out — "NAME at CLIENT"
    # becomes "NAME". It runs as a fallback, never as a pre-step, so it can
    # only ever find something extra or narrow something vague; it can never
    # take away a match the raw hint already made.
    reduced = _without(hint, lead.name)
    if reduced and reduced != " ".join(_words(hint)):
        if not matches:
            matches = _match(reduced, candidates)
        elif len(matches) > 1:
            # Ambiguous *because of* the client's words — e.g. "Ravi at Green
            # Valley School" also half-matching a contact called "Valley
            # Team". Narrowing only: the stripped hint may pick one OF the
            # candidates, never redirect us to somebody else entirely.
            narrowed = _match(reduced, candidates)
            if len(narrowed) == 1 and narrowed[0] in matches:
                matches = narrowed
    if len(matches) == 1:
        return matches[0].row
    if matches:
        raise _ask(
            f"Several people at {lead.name} match '{contact_hint}': "
            f"{_names(matches)}. Which one?",
            matches,
        )
    raise _ask(
        f"I could not match '{contact_hint}' to anyone at {lead.name}. "
        f"I have {_names(candidates)}. Who did you mean?",
        candidates,
    )
