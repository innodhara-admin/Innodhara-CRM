"""Seed the platform with the YuviPep demo organisation from the design doc.

    python scripts/seed_demo.py

Creates (idempotent — safe to run twice):
  • Organisation YuviPep (@yuvipep.com)
  • Staff: admin, Rahul (sales agent), Siva (sales lead), Mithun (ops lead),
    Sourav & Baski (ops agents), Shyam Prasad (media rep), Rahul Reddy (sales rep)
  • Program IBC with pricing v1, one proposal template, intro + follow-up
    message templates (email & WhatsApp)
  • Demo Team Alpha
  • Leads: Delhi Public School, Green Valley School, Sunrise School (+contacts)
  • A couple of demos and follow-ups

All demo passwords: Password@123  (super admin comes from .env)
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.constants import LeadState, Role  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database import SessionLocal, engine, init_db  # noqa: E402
from app.models.demo import Demo, DemoTeam, DemoTeamMember  # noqa: E402
from app.models.followup import FollowUp  # noqa: E402
from app.models.lead import Contact, Lead  # noqa: E402
from app.models.organisation import Organisation, OrgSettings  # noqa: E402
from app.models.program import (  # noqa: E402
    MessageTemplate,
    PricingTable,
    Program,
    ProposalTemplate,
)
from app.models.user import User, UserSkill  # noqa: E402

PASSWORD = hash_password("Password@123")

PROPOSAL_TEMPLATE = """# {program_name} Proposal for {client_name}

**Date:** {date}
**Prepared by:** {sender_name}, {org_name}

Dear {contact_name},

Thank you for the warm discussion about bringing the {program_name} program
to {client_name}. {context_summary}

## About the Program

{program_description}

Our facilitators run hands-on sessions on site, scheduled around your
calendar, with all materials included.

## Commercials

{pricing_table}

All prices are inclusive of materials and facilitation. Taxes as applicable.

## Next Steps

- Confirm the program plan and schedule
- Sign the engagement letter
- Our operations team schedules the kick-off demo

We look forward to partnering with {client_name}.

Warm regards,
**{sender_name}**
{org_name} · {sender_email}
"""

INTRO_EMAIL = """Dear {contact_name},

It was a pleasure meeting you at {client_name} today. Thank you for taking
the time to discuss how {org_name} can support your team.

I will share the detailed proposal shortly. Meanwhile, please feel free to
reach out to me directly for anything at all.

Warm regards,
{sender_name}
{org_name} · {sender_email}
"""

INTRO_WHATSAPP = (
    "Hello {contact_name}, this is {sender_name} from {org_name}. "
    "Lovely meeting you at {client_name} today! I'll send across the proposal "
    "shortly. Please save my number — happy to help anytime."
)

FOLLOWUP_EMAIL = """Dear {contact_name},

Just checking in following our recent conversation about {client_name}.
Please let me know if you had a chance to review the proposal, or if a quick
call would help.

Warm regards,
{sender_name}
{org_name}
"""

FOLLOWUP_WHATSAPP = (
    "Hello {contact_name}, {sender_name} from {org_name} here. Just checking "
    "in on our discussion for {client_name} — happy to answer any questions!"
)


# ── Skills (finding F25) ─────────────────────────────────────────────────────
# The assignment engine matches `action_items.required_skill` against these
# rows; with none seeded, every task fell to the phase-lead fallback flagged
# "no skill match". "general" is the neutral skill everyone holds, so a task the
# planner ties to no specialism still finds a real candidate rather than the
# fallback. The planner is told (app/ai/planning.py) to pick required_skill from
# exactly this vocabulary, so its output and these rows agree by construction.
DEMO_SKILLS: dict[str, dict[str, str]] = {
    "admin@yuvipep.com":        {"general": "good"},
    "siva@yuvipep.com":         {"proposal_preparation": "expert",
                                 "client_relationship": "expert",
                                 "content_development": "good", "general": "good"},
    "rahul@yuvipep.com":        {"proposal_preparation": "good",
                                 "client_relationship": "good", "general": "good"},
    "rahul.reddy@yuvipep.com":  {"client_relationship": "good",
                                 "content_development": "good", "general": "good"},
    "mithun@yuvipep.com":       {"logistics_coordination": "expert",
                                 "training_delivery": "expert",
                                 "quality_assurance": "good", "general": "good"},
    "sourav@yuvipep.com":       {"training_delivery": "good",
                                 "curriculum_design": "good", "general": "good"},
    "baski@yuvipep.com":        {"logistics_coordination": "good",
                                 "curriculum_design": "expert", "general": "good"},
    "shyam@yuvipep.com":        {"training_delivery": "expert",
                                 "content_development": "good", "general": "good"},
}


async def seed_user_skills(db, org_id: str) -> int:
    """Idempotently give the demo org's people `DEMO_SKILLS`. Reusable so an
    already-seeded live DB can be back-filled without re-running the whole
    seed. Returns the number of rows added."""
    added = 0
    for email, skills in DEMO_SKILLS.items():
        user = (
            await db.execute(select(User).where(User.org_id == org_id, User.email == email))
        ).scalar_one_or_none()
        if user is None:
            continue
        for skill, level in skills.items():
            exists = (
                await db.execute(
                    select(UserSkill).where(
                        UserSkill.user_id == user.id, UserSkill.skill == skill
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                db.add(UserSkill(org_id=org_id, user_id=user.id, skill=skill, level=level))
                added += 1
    return added


async def seed() -> None:
    await init_db()
    async with SessionLocal() as db:
        existing = (
            await db.execute(select(Organisation).where(Organisation.slug == "yuvipep"))
        ).scalar_one_or_none()
        if existing:
            # FINDING F33. Everything below this point is created with bare
            # `db.add(...)` and has no per-entity guard, so this script cannot
            # safely layer onto an existing org — it would duplicate all of it.
            # That constraint is real; what was wrong was reporting it as
            # "nothing to do", which reads like success. Running
            # seed_workflows first and this second therefore produced an org
            # with no Siva, no IBC program and none of F25's skill rows, and
            # said so in a reassuring sentence.
            #
            # `seed_user_skills` IS individually guarded, so the F25 rows — the
            # part whose absence silently breaks skill-based assignment — can
            # still be back-filled here. Everything else is named, not guessed
            # at, and the exit code makes the no-op detectable by a caller.
            added = await seed_user_skills(db, existing.id)
            await db.commit()
            print(
                "SKIPPED: an organisation with slug 'yuvipep' already exists.\n"
                "  This script creates its org in one shot and cannot merge into "
                "an existing one.\n"
                f"  NOT created: {', '.join(sorted(DEMO_SKILLS))}, the IBC program "
                "and its pricing table,\n"
                "               the proposal/message templates, Demo Team Alpha, "
                "the sample leads,\n"
                "               demos and follow-ups.\n"
                f"  Back-filled anyway (idempotent): {added} user-skill row(s).\n"
                "  For BOTH casts in one org, seed in this order: "
                "seed_demo.py THEN seed_workflows.py\n"
                "  (seed_workflows guards per entity, so it layers correctly; "
                "this one does not.)"
            )
            raise SystemExit(2)

        org = Organisation(
            name="YuviPep", slug="yuvipep", email_domain="yuvipep.com",
            brand_colors={"primary": "#1a3d7c", "accent": "#f5a623"},
        )
        db.add(org)
        await db.flush()
        db.add(OrgSettings(org_id=org.id, require_action_item_review=True))

        def _user(email: str, name: str, role: Role, phone: str | None = None) -> User:
            user = User(
                org_id=org.id, email=email, name=name, role=role.value,
                phone=phone, password_hash=PASSWORD,
            )
            db.add(user)
            return user

        admin = _user("admin@yuvipep.com", "YuviPep Admin", Role.ORG_ADMIN)
        rahul = _user("rahul@yuvipep.com", "Rahul", Role.SALES_AGENT, "+919800000001")
        siva = _user("siva@yuvipep.com", "Siva", Role.SALES_LEAD, "+919800000002")
        mithun = _user("mithun@yuvipep.com", "Mithun", Role.OPERATIONS_LEAD)
        sourav = _user("sourav@yuvipep.com", "Sourav", Role.OPERATIONS_AGENT)
        baski = _user("baski@yuvipep.com", "Baski", Role.OPERATIONS_AGENT)
        shyam = _user("shyam@yuvipep.com", "Shyam Prasad", Role.OPERATIONS_AGENT)
        rahul_reddy = _user("rahul.reddy@yuvipep.com", "Rahul Reddy", Role.SALES_AGENT)
        await db.flush()
        await seed_user_skills(db, org.id)  # F25: real skills to match against

        # Program + pricing + templates
        ibc = Program(
            org_id=org.id, name="IBC", code="IBC",
            description=(
                "The Innovation & Builder Curriculum (IBC): hands-on STEM "
                "workshops that turn students into young inventors."
            ),
        )
        db.add(ibc)
        await db.flush()
        db.add(
            PricingTable(
                org_id=org.id, program_id=ibc.id, version=1, currency="INR",
                items=[
                    {"code": "workshop", "label": "STEM Workshop",
                     "unit": "per workshop", "unit_price": 2000, "default_quantity": 12},
                    {"code": "kit", "label": "Student Maker Kit",
                     "unit": "per kit", "unit_price": 500, "default_quantity": 40},
                    {"code": "showcase", "label": "Annual Innovation Showcase",
                     "unit": "per event", "unit_price": 15000, "default_quantity": 1},
                ],
                created_by=admin.id,
            )
        )
        db.add(
            ProposalTemplate(
                org_id=org.id, program_id=ibc.id, name="IBC Standard",
                version=1, body_md=PROPOSAL_TEMPLATE, created_by=admin.id,
            )
        )
        for kind, channel, name, subject, body in [
            ("intro", "email", "Intro Email", "Great meeting you — {org_name}", INTRO_EMAIL),
            ("intro", "whatsapp", "Intro WhatsApp", None, INTRO_WHATSAPP),
            ("follow_up", "email", "Follow-up Email",
             "Following up — {client_name} × {org_name}", FOLLOWUP_EMAIL),
            ("follow_up", "whatsapp", "Follow-up WhatsApp", None, FOLLOWUP_WHATSAPP),
        ]:
            db.add(
                MessageTemplate(
                    org_id=org.id, kind=kind, channel=channel, name=name,
                    version=1, subject=subject, body=body, created_by=admin.id,
                )
            )

        # Demo Team Alpha (doc §9.5 example)
        alpha = DemoTeam(
            org_id=org.id, name="Alpha", lead_user_id=mithun.id,
            media_rep_id=shyam.id, sales_rep_id=rahul_reddy.id,
        )
        db.add(alpha)
        await db.flush()
        for member in (sourav, baski):
            db.add(DemoTeamMember(org_id=org.id, team_id=alpha.id, user_id=member.id))

        # Leads + contacts
        dps = Lead(
            org_id=org.id, name="Delhi Public School", state=LeadState.ACTIVE.value,
            owner_id=rahul.id, city="Delhi", source="referral",
        )
        green_valley = Lead(
            org_id=org.id, name="Green Valley School", state=LeadState.OPEN.value,
            owner_id=rahul.id, city="Gurgaon",
        )
        sunrise = Lead(
            org_id=org.id, name="Sunrise School", state=LeadState.ACTIVE.value,
            owner_id=siva.id, city="Noida", is_important=True,
        )
        db.add_all([dps, green_valley, sunrise])
        await db.flush()
        db.add_all(
            [
                Contact(org_id=org.id, lead_id=dps.id, name="Mrs. Sharma",
                        title="Principal", email="principal@dps.example.edu",
                        phone="+919810000001", is_primary=True),
                Contact(org_id=org.id, lead_id=dps.id, name="Mr. Verma",
                        title="Owner", email="owner@dps.example.edu",
                        phone="+919810000002"),
                Contact(org_id=org.id, lead_id=green_valley.id, name="Mr. Rao",
                        title="Principal", email="principal@greenvalley.example.edu",
                        phone="+919810000003", is_primary=True),
                Contact(org_id=org.id, lead_id=sunrise.id, name="Ms. Iyer",
                        title="Director", email="director@sunrise.example.edu",
                        phone="+919810000004", is_primary=True),
            ]
        )

        # Demos + follow-ups
        today = date.today()
        db.add_all(
            [
                Demo(org_id=org.id, lead_id=dps.id, team_id=alpha.id,
                     scheduled_date=today + timedelta(days=10),
                     scheduled_time="10:00", created_by=mithun.id),
                Demo(org_id=org.id, lead_id=sunrise.id, team_id=alpha.id,
                     scheduled_date=today + timedelta(days=16),
                     scheduled_time="11:30", created_by=mithun.id),
            ]
        )
        db.add_all(
            [
                FollowUp(org_id=org.id, lead_id=green_valley.id, owner_id=rahul.id,
                         due_date=today, channel="whatsapp",
                         note="Check interest after first call", created_by=rahul.id),
                FollowUp(org_id=org.id, lead_id=sunrise.id, owner_id=siva.id,
                         due_date=today, channel="email",
                         note="Share demo agenda", created_by=siva.id),
            ]
        )

        await db.commit()
        print("Seeded YuviPep demo organisation.")
        print("Logins (password: Password@123):")
        for email, role in [
            ("admin@yuvipep.com", "Org Admin"),
            ("rahul@yuvipep.com", "Sales Agent"),
            ("siva@yuvipep.com", "Sales Lead"),
            ("mithun@yuvipep.com", "Operations Lead"),
        ]:
            print(f"  {email:28s} {role}")


async def _main() -> None:
    # FINDING F32. `aiosqlite` runs a NON-DAEMON worker thread per connection.
    # Without this dispose the thread outlives `asyncio.run()` and the process
    # hangs forever after committing — holding the SQLite file, so the next
    # writer blocks. It happens on SUCCESS, not only on an exception; handoff
    # §6g/§6i had that cause wrong. Every verify_* script already does this.
    try:
        await seed()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
