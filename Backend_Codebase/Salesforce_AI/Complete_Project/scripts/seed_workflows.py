"""Seed the exact cast and configuration of the 30-Workflows specification.

    python scripts/seed_workflows.py

Creates (idempotent — safe to run twice):
  • Organisation YuviPep (@yuvipep.com) with the workflow behaviour dials
  • The full cast: Ananya (org admin), Akash (sales lead), Rahul & Priya
    (sales agents), Mithun (ops lead), Meera, Sourav, Baski, Shyam, Vikram
    (ops agents) — with designations, departments, capacities and skills
  • Programs: Android Bootcamp (pricing v4: ₹300/student + ₹6,000 materials)
    and STEM Lab
  • Proposal + message templates
  • Playbooks: preparation / delivery / payment / closure waves
  • The approval rule set of the Roles doc §7
  • Schools: SVS (Harish, Kavita, Ramesh), DPS, Sunrise Group, Green Valley,
    Little Flowers, Modern Public School
  • Vendor: PrintCraft

All passwords: Password@123
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.core.constants import LeadState, Role  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database import SessionLocal, engine, init_db  # noqa: E402
from app.models.comms import ApprovalRule  # noqa: E402
from app.models.finance import Vendor  # noqa: E402
from app.models.lead import Contact, Lead  # noqa: E402
from app.models.organisation import Organisation, OrgSettings  # noqa: E402
from app.models.program import (  # noqa: E402
    MessageTemplate,
    PricingTable,
    Program,
    ProposalTemplate,
)
from app.models.project import Playbook  # noqa: E402
from app.models.user import User, UserSkill  # noqa: E402

PASSWORD = hash_password("Password@123")

# name, email, role, designation, department, max_open_tasks, skills{name: level}
STAFF = [
    ("Ananya Iyer", "ananya@yuvipep.com", Role.ORG_ADMIN, "Org Admin", None, 8, {}),
    ("Akash Rathore", "akash@yuvipep.com", Role.SALES_LEAD, "Sales Lead", "sales", 8,
     {"negotiation": "expert", "proposals": "good"}),
    ("Rahul Verma", "rahul@yuvipep.com", Role.SALES_AGENT, "Sales Executive", "sales", 8,
     {"field_sales": "expert", "hindi": "expert"}),
    ("Priya Nair", "priya@yuvipep.com", Role.SALES_AGENT, "Sales Executive", "sales", 8,
     {"field_sales": "good", "english_writing": "expert", "proposals": "good"}),
    ("Meera Joshi", "meera@yuvipep.com", Role.OPERATIONS_AGENT, "Content Specialist",
     "operations", 8, {"curriculum_design": "expert", "android": "good"}),
    ("Sourav Das", "sourav@yuvipep.com", Role.OPERATIONS_AGENT, "Trainer",
     "operations", 8, {"android": "expert", "teaching": "expert", "robotics": "basic"}),
    ("Baski Murmu", "baski@yuvipep.com", Role.OPERATIONS_AGENT, "Trainer",
     "operations", 8, {"robotics": "expert", "teaching": "good", "android": "good"}),
    ("Mithun Sharma", "mithun@yuvipep.com", Role.OPERATIONS_LEAD, "Operations Lead",
     "operations", 10, {"scheduling": "expert", "logistics": "expert"}),
    ("Shyam Prasad", "shyam@yuvipep.com", Role.OPERATIONS_AGENT, "Media Rep",
     "operations", 8, {"photography": "expert", "social_media": "expert"}),
    ("Vikram Rao", "vikram@yuvipep.com", Role.OPERATIONS_AGENT, "Accounts Executive",
     "accounts", 8, {"invoicing": "expert", "payments": "expert"}),
]

SCHOOLS = [
    ("Swami Vivekananda School", "Salt Lake", "Kolkata", [
        ("Harish Singhania", "Principal", "principal@svs.edu.in", "+91 9800000055", True),
        ("Kavita Menon", "Academic Coordinator", "kavita@svs.edu.in", "+91 9800000056", False),
        ("Ramesh Gupta", "Accountant", "accounts@svs.edu.in", "+91 9800000057", False),
    ]),
    ("Delhi Public School", "Park Street", "Kolkata", [
        ("Mrs. Sharma", "Principal", "principal@dpskol.edu.in", "+91 9800000060", True),
        ("Mr. Verma", "Owner", "owner@dpskol.edu.in", "+91 9800000061", False),
    ]),
    ("Sunrise Group of Schools", "Ballygunge", "Kolkata", [
        ("Dr. Anita Bose", "Group Director", "director@sunrisegroup.edu.in", "+91 9800000070", True),
    ]),
    ("Green Valley School", "New Town", "Kolkata", [
        ("Mr. Iyer", "Principal", "principal@greenvalley.edu.in", "+91 9800000080", True),
    ]),
    ("Little Flowers School", "Howrah", "Kolkata", [
        ("Mr. D'Souza", "Director", "director@littleflowers.edu.in", "+91 9800000090", True),
    ]),
    ("Modern Public School", "Dum Dum", "Kolkata", [
        ("Mrs. Banerjee", "Principal", "principal@modernpublic.edu.in", "+91 9800000095", True),
    ]),
]

PROPOSAL_TEMPLATE = """# {program_name} Proposal for {school_name}

**Prepared by:** {sender_name}, {org_name}

Dear {contact_name},

Thank you for the discussion about bringing {program_name} to {school_name}.
{context_summary}

## About the Program

{program_description}

## Commercials

{pricing_table}

All prices are inclusive of materials and facilitation. Taxes as applicable.

Warm regards,
**{sender_name}**
{org_name} · {sender_email}
"""

# The Roles-doc §7 rule set, expressed as data.
APPROVAL_RULES = [
    # entity_type, condition, rank, approver, fallback, recommender, joint, joint_cond, expires, description
    ("price_change", {"discount_pct_gt": 10}, 10, "org_admin", None, "sales_lead",
     None, None, 48.0, "Discount above 10% — sales lead recommends, org admin decides"),
    ("price_change", {}, 90, "sales_lead", "org_admin", None, None, None, 48.0,
     "Smaller price matters — sales lead decides"),
    ("proposal", {"amount_gt": 100000}, 10, "sales_lead", "org_admin", None,
     None, None, 48.0, "Proposal above ₹1,00,000 — sales lead approves"),
    ("plan_change", {"urgent": True}, 5, "sales_lead", "org_admin", None,
     "operations_lead", None, 0.5, "Urgent client promise — joint sales+ops, 30 minutes"),
    ("plan_change", {"new_project": True}, 10, "sales_lead", "org_admin", None,
     None, None, 24.0, "New project + plan v1 — sales lead confirms team and dates"),
    ("plan_change", {"scope_change": True}, 15, "sales_lead", "org_admin", None,
     None, None, 24.0, "Scope change — sales lead approves the expansion wave"),
    ("plan_change", {"delivery_dates_moved": True}, 19, "sales_lead", "org_admin", None,
     "operations_lead", None, 24.0,
     "Delivery window moved — sales owns the promise, ops owns the delivery: both say yes"),
    ("plan_change", {"date_shift_days_gt": 2}, 20, "sales_lead", "org_admin", None,
     "operations_lead", {"delivery_dates_moved": True}, 24.0,
     "Plan change shifting dates >2 days — joint with ops when delivery moves"),
    ("plan_change", {"conflict_resolved": True}, 25, "sales_lead", "org_admin",
     None, None, None, 24.0, "Held plan released after conflict resolution"),
    ("plan_change", {"resubmission": True}, 26, "sales_lead", "org_admin",
     None, None, None, 24.0, "Plan resubmitted after a rejection note"),
    ("plan_change", {"tasks_added_gte": 2}, 30, "sales_lead", "org_admin",
     None, None, None, 24.0, "Plan growth of 2+ tasks — lead confirms the wave"),
    # Everything else in plan_change matches NO rule → activates as "system".
    ("outbound_message", {"kind": "intro"}, 10, "thread_owner", "sales_lead", None,
     None, None, 24.0, "Template intro — the sender approves their own"),
    ("outbound_message", {"kind": "reply", "channel": "whatsapp",
                          "sender_is_thread_owner": True}, 15, "thread_owner",
     "sales_lead", None, None, None, 24.0,
     "WhatsApp replies on your own thread — you approve"),
    ("outbound_message", {"urgent": True}, 18, "sales_lead", "org_admin", None,
     None, None, 0.5, "Urgent client message — 30-minute window"),
    ("outbound_message", {}, 50, "sales_lead", "org_admin", None, None, None,
     24.0, "Every other client message — sales lead approves"),
    ("invoice", {}, 50, "sales_lead", "org_admin", None, None, None, 48.0,
     "Invoices — sales lead approves the send"),
]

PLAYBOOKS = {
    "preparation": [
        {"title": "Confirm trainer allocation", "required_skill": "scheduling",
         "offset_days": -14, "priority": "P2", "visible_to_client": False},
        {"title": "Order student kits and workbooks", "required_skill": "logistics",
         "offset_days": -10, "priority": "P2", "visible_to_client": False},
        {"title": "Prepare batch schedule", "required_skill": "scheduling",
         "offset_days": -8, "priority": "P2", "visible_to_client": True},
        {"title": "Run teacher demo session", "required_skill": "teaching",
         "offset_days": -7, "priority": "P2", "visible_to_client": True},
        {"title": "Raise 50% advance invoice", "required_skill": "invoicing",
         "offset_days": -12, "priority": "P1", "visible_to_client": False},
        {"title": "Prepare Day-1 and Day-2 lab exercises", "required_skill": "android",
         "offset_days": -5, "priority": "P2", "visible_to_client": False},
    ],
    "delivery": [
        {"title": "Assemble day-of runsheets for delivery days",
         "required_skill": "scheduling", "offset_days": -1, "priority": "P1",
         "visible_to_client": False},
        {"title": "Cover delivery days with photos", "required_skill": "photography",
         "offset_days": 0, "priority": "P3", "visible_to_client": False},
    ],
    "payment": [
        {"title": "Raise balance invoice", "required_skill": "invoicing",
         "offset_days": 1, "priority": "P1", "visible_to_client": False},
    ],
    "closure": [
        {"title": "Collect feedback from teachers and students",
         "required_skill": "teaching", "offset_days": 2, "priority": "P2",
         "visible_to_client": True},
        {"title": "Issue participation certificates", "required_skill": "curriculum_design",
         "offset_days": 4, "priority": "P2", "visible_to_client": True},
        {"title": "Prepare closure report", "required_skill": "photography",
         "offset_days": 5, "priority": "P2", "visible_to_client": True},
        {"title": "Ask for a testimonial", "required_skill": "field_sales",
         "offset_days": 7, "priority": "P3", "visible_to_client": True},
        {"title": "Write internal retrospective", "required_skill": "scheduling",
         "offset_days": 7, "priority": "P3", "visible_to_client": False},
    ],
}


async def seed() -> None:
    await init_db()
    async with SessionLocal() as db:
        org = (
            await db.execute(select(Organisation).where(Organisation.slug == "yuvipep"))
        ).scalar_one_or_none()
        if org is None:
            org = Organisation(
                # FINDING F34: stored WITHOUT the leading "@". `admin.py:84`
                # tests `email.endswith("@" + org.email_domain)`, so "@yuvipep.com"
                # built "@@yuvipep.com" and no address could ever match — adding
                # a staff member was impossible in any org this script created.
                # `organisations.py:65` lstrips "@" for the same reason.
                name="YuviPep", slug="yuvipep", email_domain="yuvipep.com",
            )
            db.add(org)
            await db.flush()
            db.add(OrgSettings(org_id=org.id))
        org_id = org.id

        users: dict[str, User] = {}
        for name, email, role, designation, department, cap, skills in STAFF:
            user = (
                await db.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if user is None:
                user = User(
                    org_id=org_id, email=email, name=name, role=role.value,
                    password_hash=PASSWORD, designation=designation,
                    department=department, max_open_tasks=cap,
                    whatsapp_number="+91 98" + email[:2].ljust(8, "0"),
                )
                db.add(user)
                await db.flush()
            users[name.split()[0]] = user
            for skill, level in skills.items():
                existing = (
                    await db.execute(
                        select(UserSkill).where(
                            UserSkill.user_id == user.id, UserSkill.skill == skill
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    db.add(UserSkill(org_id=org_id, user_id=user.id, skill=skill, level=level))

        # Programs + pricing + templates.
        android = (
            await db.execute(
                select(Program).where(Program.org_id == org_id, Program.code == "ANDROID_BC")
            )
        ).scalar_one_or_none()
        if android is None:
            android = Program(
                org_id=org_id, name="Bootcamp — Learning About Android",
                code="ANDROID_BC",
                description=(
                    "Hands-on app-building bootcamp for classes 5–9; block-based "
                    "apps for juniors, Kotlin introduction for seniors on days 5-7"
                ),
            )
            db.add(android)
            await db.flush()
            for v in range(1, 5):  # history: v4 is current
                db.add(
                    PricingTable(
                        org_id=org_id, program_id=android.id, version=v,
                        currency="INR",
                        items=[
                            {"code": "per_student", "label": "Bootcamp fee",
                             "unit": "per student", "unit_price": 250 + v * 12},
                            {"code": "materials", "label": "Materials & workbooks",
                             "unit": "flat per bootcamp", "unit_price": 6000},
                        ] if v < 4 else [
                            {"code": "per_student", "label": "Bootcamp fee",
                             "unit": "per student", "unit_price": 300},
                            {"code": "materials", "label": "Materials & workbooks",
                             "unit": "flat per bootcamp", "unit_price": 6000},
                        ],
                        is_current=(v == 4),
                        created_by=users["Ananya"].id,
                    )
                )
            db.add(
                ProposalTemplate(
                    org_id=org_id, program_id=android.id, name="Bootcamp — detailed",
                    version=2, body_md=PROPOSAL_TEMPLATE, is_current=True,
                    created_by=users["Ananya"].id,
                )
            )
        stem = (
            await db.execute(
                select(Program).where(Program.org_id == org_id, Program.code == "STEM_LAB")
            )
        ).scalar_one_or_none()
        if stem is None:
            stem = Program(
                org_id=org_id, name="STEM Lab — Permanent Installation",
                code="STEM_LAB",
                description="A permanent STEM laboratory: robotics kits, tools, "
                "teacher training and a year of curriculum support",
            )
            db.add(stem)
            await db.flush()
            db.add(
                PricingTable(
                    org_id=org_id, program_id=stem.id, version=1, currency="INR",
                    items=[
                        {"code": "lab_setup", "label": "Lab setup",
                         "unit": "flat per lab", "unit_price": 450000},
                        {"code": "annual_support", "label": "Annual support",
                         "unit": "flat per year", "unit_price": 90000},
                    ],
                    is_current=True, created_by=users["Ananya"].id,
                )
            )
            db.add(
                ProposalTemplate(
                    org_id=org_id, program_id=stem.id, name="STEM Lab — standard",
                    version=1, body_md=PROPOSAL_TEMPLATE, is_current=True,
                    created_by=users["Ananya"].id,
                )
            )

        for kind, channel, subject, body in [
            ("intro", "email", "Great meeting you, {contact_name}",
             "Dear {contact_name},\n\nIt was a pleasure meeting you at "
             "{school_name}. {context}\n\nWarm regards,\n{sender_name}, {org_name}"),
            ("intro", "whatsapp", None,
             "Hello {contact_name}, lovely meeting you at {school_name}! "
             "— {sender_name}, {org_name}"),
            ("follow_up", "email", "Checking in — {school_name}",
             "Dear {contact_name},\n\nJust checking in on our conversation. "
             "Happy to answer any questions.\n\nWarm regards,\n{sender_name}"),
            ("follow_up", "whatsapp", None,
             "Hi {contact_name}, just checking you received our note — happy "
             "to help with any questions. — {sender_name}"),
        ]:
            existing = (
                await db.execute(
                    select(MessageTemplate).where(
                        MessageTemplate.org_id == org_id,
                        MessageTemplate.kind == kind,
                        MessageTemplate.channel == channel,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                db.add(
                    MessageTemplate(
                        org_id=org_id, kind=kind, channel=channel,
                        name=f"{kind} {channel}", version=1, subject=subject,
                        body=body, is_current=True, created_by=users["Ananya"].id,
                    )
                )

        # Playbooks (Android program).
        for phase, entries in PLAYBOOKS.items():
            existing = (
                await db.execute(
                    select(Playbook).where(
                        Playbook.org_id == org_id,
                        Playbook.program_id == android.id,
                        Playbook.phase == phase,
                        Playbook.is_current.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                db.add(
                    Playbook(
                        org_id=org_id, program_id=android.id, phase=phase,
                        entries=entries, version=1, is_current=True,
                        updated_by=users["Ananya"].id,
                    )
                )

        # Approval rules.
        have_rules = (
            await db.execute(
                select(ApprovalRule).where(ApprovalRule.org_id == org_id)
            )
        ).scalars().first()
        if have_rules is None:
            for (entity_type, condition, rank, approver, fallback, recommender,
                 joint, joint_cond, expires, description) in APPROVAL_RULES:
                db.add(
                    ApprovalRule(
                        org_id=org_id, entity_type=entity_type, condition=condition,
                        rank=rank, approver_role=approver, fallback_role=fallback,
                        recommender_role=recommender, joint_with_role=joint,
                        joint_condition=joint_cond, expires_hours=expires,
                        description=description,
                    )
                )

        # Schools + contacts.
        for school_name, address, city, contacts in SCHOOLS:
            lead = (
                await db.execute(
                    select(Lead).where(Lead.org_id == org_id, Lead.name == school_name)
                )
            ).scalar_one_or_none()
            if lead is None:
                lead = Lead(
                    org_id=org_id, name=school_name, address=address, city=city,
                    state=LeadState.OPEN.value, owner_id=users["Rahul"].id,
                    source="seed",
                )
                db.add(lead)
                await db.flush()
                for cname, title, email, phone, primary in contacts:
                    db.add(
                        Contact(
                            org_id=org_id, lead_id=lead.id, name=cname, title=title,
                            email=email, phone=phone, is_primary=primary,
                            source="manual",
                        )
                    )

        # Vendor.
        vendor = (
            await db.execute(
                select(Vendor).where(Vendor.org_id == org_id, Vendor.name == "PrintCraft")
            )
        ).scalar_one_or_none()
        if vendor is None:
            db.add(
                Vendor(
                    org_id=org_id, name="PrintCraft", contact_name="Mr. Jain",
                    phone="+91 9800000099", category="printing",
                    notes="Reliable but pad lead time by 2 days; 50% advance",
                )
            )

        await db.commit()
        print(f"Seeded YuviPep workflow org: org_id={org_id}")
        print("Staff:", ", ".join(users))


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
