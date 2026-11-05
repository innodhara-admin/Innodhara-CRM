"""Relationship Engine — picks the manager who should look after a client.

Modelled on `assignment_engine`, deliberately NOT built on it. That engine
scores a person for one `ActionItem`: its load is a count of open tasks and
its continuity is tasks done on a project. Neither means anything for "who
should keep talking to this client for the next year", and bending an
`ActionItem` into the shape of a client would make both engines harder to
read. What is shared is the part worth sharing — the candidate/score/reason
shape, `SKILL_LEVEL_SCORE`, and `resource_engine.conflicts_for`.

The score has three ingredients and no more, because every one of them has to
survive being read aloud to the person who was not chosen:

  focus       an area of expertise the manager holds that this client's own
              record mentions (see `_focus_tokens`)
  load        how many clients they are already looking after, against the
              size of plate they were given
  experience  how many engagements they have held before

Everything the engine decides is written through `record_decision`, so the
app's "Why this person?" button always has prose behind it. Finding F10 was a
suggestion shown with no decision recorded, and the button could only answer
"no decision recorded".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    DecisionType,
    EngagementStatus,
    Role,
    SKILL_LEVEL_SCORE,
)
from app.engines import resource_engine
from app.engines.common import record_decision
from app.models.base import utcnow
from app.models.lead import Lead
from app.models.relationship import RelationshipEngagement
from app.models.user import User, UserSkill

logger = logging.getLogger(__name__)

ENGINE = "relationship"

# How far ahead to ask "are they even available" — a relationship is a long
# job, but a manager who is on leave for the next fortnight should not be the
# one greeted with a new client today.
_AVAILABILITY_WINDOW = timedelta(days=14)

# Experience stops counting after this many engagements. Somebody who has held
# thirty should not out-rank a good match forever.
_EXPERIENCE_CAP = 5


def _focus_tokens(lead: Lead) -> set[str]:
    """The words this client's own record offers, as skill-shaped tokens.

    A manager's areas of expertise live in `user_skills` exactly like any
    other skill, named by whoever set the organisation up — a region, an
    account size, a segment. Rather than invent a vocabulary here (which would
    be a domain assumption, and this codebase forbids those), the engine takes
    the words already on the lead and looks for a manager who holds one of
    them as a skill.

    That means the match is only as good as what the organisation typed, which
    is the honest trade: an unmatched manager still scores on load and
    experience, and the recorded reason says plainly that there was no focus
    match rather than implying one.
    """
    raw = [lead.city, lead.region, lead.source]
    return {
        part.strip().lower().replace(" ", "_")
        for part in raw
        if part and part.strip()
    }


@dataclass
class Candidate:
    user: User
    focus: str | None                 # which token matched, if any
    focus_level: str | None           # basic | good | expert
    active_clients: int
    engagements_held: int
    conflicts: list[str] = field(default_factory=list)

    def score(self) -> float:
        focus = SKILL_LEVEL_SCORE.get(self.focus_level or "", 0)
        cap = max(self.user.max_open_tasks or 8, 1)
        load_penalty = self.active_clients / cap
        experience = min(self.engagements_held, _EXPERIENCE_CAP)
        return focus * 10 - load_penalty * 6 + experience * 1.5

    def reason(self) -> str:
        cap = self.user.max_open_tasks or 8
        bits = [
            f"{self.user.name}: "
            + (
                f"{self.focus_level} with {self.focus.replace('_', ' ')}"
                if self.focus
                else "no particular focus match"
            ),
            f"looking after {self.active_clients}/{cap} clients",
        ]
        if self.engagements_held:
            bits.append(f"has held {self.engagements_held} engagement(s) before")
        else:
            bits.append("first engagement")
        if self.conflicts:
            bits.append("but: " + "; ".join(self.conflicts))
        return ", ".join(bits)


async def _active_client_count(db: AsyncSession, org_id: str, user_id: str) -> int:
    return (
        await db.execute(
            select(func.count(RelationshipEngagement.id)).where(
                RelationshipEngagement.org_id == org_id,
                RelationshipEngagement.manager_id == user_id,
                RelationshipEngagement.status == EngagementStatus.ACTIVE.value,
            )
        )
    ).scalar_one()


async def _engagements_held(db: AsyncSession, org_id: str, user_id: str) -> int:
    return (
        await db.execute(
            select(func.count(RelationshipEngagement.id)).where(
                RelationshipEngagement.org_id == org_id,
                RelationshipEngagement.manager_id == user_id,
            )
        )
    ).scalar_one()


async def managers(db: AsyncSession, org_id: str) -> list[User]:
    """Every active relationship manager in the organisation."""
    return list(
        (
            await db.execute(
                select(User)
                .where(
                    User.org_id == org_id,
                    User.role == Role.RELATIONSHIP_MANAGER.value,
                    User.is_active.is_(True),
                )
                .order_by(User.name)
            )
        ).scalars().all()
    )


async def build_candidates(
    db: AsyncSession, *, org_id: str, lead: Lead
) -> list[Candidate]:
    """Every available manager, scored. Empty when the org has none."""
    people = await managers(db, org_id)
    if not people:
        return []

    tokens = _focus_tokens(lead)
    skills: dict[str, list[UserSkill]] = {}
    if people:
        rows = (
            await db.execute(
                select(UserSkill).where(
                    UserSkill.org_id == org_id,
                    UserSkill.user_id.in_([p.id for p in people]),
                )
            )
        ).scalars().all()
        for row in rows:
            skills.setdefault(row.user_id, []).append(row)

    window_from = utcnow()
    window_to = window_from + _AVAILABILITY_WINDOW
    out: list[Candidate] = []
    for person in people:
        best: UserSkill | None = None
        for row in skills.get(person.id, []):
            if row.skill.strip().lower().replace(" ", "_") not in tokens:
                continue
            if best is None or SKILL_LEVEL_SCORE.get(
                row.level, 0
            ) > SKILL_LEVEL_SCORE.get(best.level, 0):
                best = row
        out.append(
            Candidate(
                user=person,
                focus=best.skill if best else None,
                focus_level=best.level if best else None,
                active_clients=await _active_client_count(db, org_id, person.id),
                engagements_held=await _engagements_held(db, org_id, person.id),
                conflicts=await resource_engine.conflicts_for(
                    db, org_id=org_id, user=person,
                    date_from=window_from, date_to=window_to,
                ),
            )
        )
    return out


def pick(candidates: list[Candidate]) -> tuple[Candidate | None, str]:
    """The winner and a note about how the choice was made.

    Somebody with a clash is not excluded, only deprioritised: an organisation
    with one manager who happens to be on leave next week still needs the
    client looked after, and hiding that person would leave the button doing
    nothing with no explanation. The clash is carried into the reason instead.
    """
    if not candidates:
        return None, "no relationship managers in this organisation"
    if len(candidates) == 1:
        only = candidates[0]
        return only, (
            "the only relationship manager in this organisation, so there was "
            "no choice to make"
        )
    free = [c for c in candidates if not c.conflicts] or candidates
    ranked = sorted(free, key=lambda c: -c.score())
    if len(ranked) >= 2 and abs(ranked[0].score() - ranked[1].score()) < 0.01:
        ranked.sort(key=lambda c: (c.active_clients, c.user.name))
        return ranked[0], (
            "an even match on focus and experience, so the lighter workload "
            "decided it"
        )
    return ranked[0], ""


async def choose_manager(
    db: AsyncSession, *, org_id: str, lead: Lead, chosen_id: str | None = None
) -> tuple[User | None, str, bool]:
    """Pick the manager for a client and write down why.

    Returns (manager, reason, overridden). A `chosen_id` means a person made
    the call; the engine still scores everybody, so the recorded reason can
    say what the AI would have done and be honest that it was overruled.
    """
    candidates = await build_candidates(db, org_id=org_id, lead=lead)
    if not candidates:
        return None, "no relationship managers in this organisation", False

    winner, note = pick(candidates)
    overridden = False
    if chosen_id is not None:
        picked = next((c for c in candidates if c.user.id == chosen_id), None)
        if picked is None:
            return None, "that person is not a relationship manager here", False
        overridden = winner is not None and picked.user.id != winner.user.id
        winner, note = picked, (
            f"chosen by a person over the engine's pick of {winner.user.name}"
            if overridden else "chosen by a person, matching the engine's pick"
        )

    assert winner is not None
    considered = ", ".join(
        c.reason() for c in sorted(candidates, key=lambda c: -c.score())
    )
    reason = winner.reason() + (f" — {note}" if note else "")
    await record_decision(
        db,
        org_id=org_id,
        decision_type=DecisionType.ASSIGNMENT.value,
        engine=ENGINE,
        input_summary=f"Considered {len(candidates)} manager(s): {considered}",
        decision=(
            f"{winner.user.name} will look after '{lead.name}' "
            f"now that the sales work is finished"
        ),
        reason=reason,
        confidence=0.6 if winner.focus is None else 0.85,
        needs_human=False,   # a person already decided to hand the client over
        entity_type="lead",
        entity_id=lead.id,
    )
    return winner.user, reason, overridden
