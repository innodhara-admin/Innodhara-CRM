"""Load the 11 tagged Word email templates into one organisation (28 Oct 2026).

    DATABASE_URL=... python scripts/load_email_templates.py --org-name YuviPep --dir <folder> --dry-run
    DATABASE_URL=... python scripts/load_email_templates.py --org-name YuviPep --dir <folder>

Design: YuvipepSalesforceAI/docs/superpowers/specs/2026-10-28-email-templates-design.md
sections 3 and 5. Creates the two products the developer asked for
("Kaushal Bodh and Kaushal Vikaas", "Innovation Fest") when missing, then
publishes every file in MANIFEST through the same service the dashboard's
upload uses, acting as the organisation's earliest active org admin.

* DATABASE_URL must be set explicitly, so the database is never a guess, and
  it is printed before anything else.
* A file whose bytes equal the current version of its name is skipped, so a
  second run publishes nothing.
* --dry-run does everything, prints it, then rolls it all back.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.core.context import OrgContext  # noqa: E402
from app.models.email_template import EmailTemplate  # noqa: E402
from app.models.organisation import Organisation  # noqa: E402
from app.models.program import Program  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import audit_service, email_template_service  # noqa: E402

#: Where each file goes. Kept equal to tests/email/test_word_files.py by
#: tests/email/test_loader.py.
MANIFEST: dict[str, dict] = {
    "Intro and appointment seeking.docx": {
        "type": "common", "category": "intro", "program_code": None,
        "name": "Intro and appointment seeking", "built_document": "none",
        "when_to_use": "First email to a new client contact: introduces the "
                       "organisation and asks for a 20-minute meeting with two "
                       "time options."},
    "Meeting confirmation.docx": {
        "type": "common", "category": "meeting_confirmation", "program_code": None,
        "name": "Meeting confirmation", "built_document": "none",
        "when_to_use": "After the client agrees to meet: confirms the date, "
                       "time and venue or video link."},
    "After the meeting.docx": {
        "type": "common", "category": "after_meeting", "program_code": None,
        "name": "After the meeting", "built_document": "none",
        "when_to_use": "Right after a meeting: thanks them and sums up what was "
                       "discussed and the agreed action plan."},
    "No reply follow-up.docx": {
        "type": "common", "category": "follow_up", "program_code": None,
        "name": "No reply follow-up", "built_document": "none",
        "when_to_use": "The client has not replied: a follow-up with two impact "
                       "video links, asking again for a 20-minute meeting."},
    "Final follow-up.docx": {
        "type": "common", "category": "final_follow_up", "program_code": None,
        "name": "Final follow-up", "built_document": "none",
        "when_to_use": "No response after several follow-ups: a polite last "
                       "note that leaves the next move to the client."},
    "Onboarding.docx": {
        "type": "common", "category": "onboarding", "program_code": None,
        "name": "Onboarding", "built_document": "none",
        "when_to_use": "After the client signs up: contacts, the onboarding "
                       "roadmap and what is needed from them."},
    "IBC proposal email.docx": {
        "type": "product", "category": None, "program_code": "IBC",
        "name": "IBC proposal email", "built_document": "proposal",
        "when_to_use": "Sends the client's IBC proposal."},
    "Kaushal Bodh and Kaushal Vikaas proposal email.docx": {
        "type": "product", "category": None, "program_code": "KBKV",
        "name": "Kaushal Bodh and Kaushal Vikaas proposal email",
        "built_document": "proposal",
        "when_to_use": "Sends the client's Kaushal Bodh and Kaushal Vikaas "
                       "proposal."},
    "Innovation Lab proposal email.docx": {
        "type": "product", "category": None, "program_code": "YFIL",
        "name": "Innovation Lab proposal email", "built_document": "proposal",
        "when_to_use": "Sends the client's Innovation Lab proposal."},
    "Innovation Fest proposal email.docx": {
        "type": "product", "category": None, "program_code": "IFEST",
        "name": "Innovation Fest proposal email", "built_document": "proposal",
        "when_to_use": "Sends the client's Innovation Fest proposal."},
    "IBC MoU cover letter.docx": {
        "type": "product", "category": None, "program_code": "IBC",
        "name": "IBC MoU cover letter", "built_document": "mou",
        "when_to_use": "Sends the client's IBC MoU with a cover letter."},
}

#: The products the developer asked to add (28 Oct 2026), with descriptions
#: taken from their own proposal emails.
NEW_PRODUCTS: dict[str, tuple[str, str]] = {
    "KBKV": ("Kaushal Bodh and Kaushal Vikaas",
             "Kaushal Bodh supports the implementation of CBSE's skill education "
             "curriculum; Kaushal Vikaas strengthens practical and vocational "
             "competencies, through guided sessions, expert mentorship and "
             "hands-on project-based learning."),
    "IFEST": ("Innovation Fest",
              "A platform to showcase ideas, present innovative projects and "
              "demonstrate problem-solving, with collaboration, healthy "
              "competition and real-world application of knowledge."),
}


async def _org(db, name: str) -> Organisation | None:
    rows = (await db.execute(select(Organisation).where(
        func.lower(Organisation.name) == name.strip().lower()))).scalars().all()
    return rows[0] if len(rows) == 1 else None


async def _actor(db, org_id: str) -> OrgContext:
    user = (await db.execute(select(User).where(
        User.org_id == org_id, User.role == "org_admin",
        User.is_active.is_(True)).order_by(User.created_at))).scalars().first()
    if user is None:
        raise SystemExit("That organisation has no active org admin to act as.")
    return OrgContext(org_id=org_id, user_id=user.id, role=user.role,
                      email=user.email, name=user.name)


async def _products(db, ctx: OrgContext) -> dict[str, Program]:
    rows = (await db.execute(select(Program).where(
        Program.org_id == ctx.org_id))).scalars().all()
    by_code = {p.code.upper(): p for p in rows}
    for code, (name, description) in NEW_PRODUCTS.items():
        if code in by_code:
            continue
        program = Program(org_id=ctx.org_id, name=name, code=code,
                          description=description)
        db.add(program)
        await audit_service.record(
            db, org_id=ctx.org_id, user_id=ctx.user_id,
            action="admin.program_added", entity_type="program",
            detail={"code": code, "by": "load_email_templates"})
        await db.flush()
        by_code[code] = program
    return by_code


async def load(db, *, org_name: str, folder: Path) -> list[dict[str, Any]]:
    org = await _org(db, org_name)
    if org is None:
        raise LookupError(f"No single organisation is named '{org_name}'.")
    ctx = await _actor(db, org.id)
    products = await _products(db, ctx)
    out = []
    for filename, entry in MANIFEST.items():
        data = (folder / filename).read_bytes()
        current = (await db.execute(select(EmailTemplate).where(
            EmailTemplate.org_id == ctx.org_id, EmailTemplate.name == entry["name"],
            EmailTemplate.is_current.is_(True)))).scalars().first()
        if current is not None and current.sha256 == hashlib.sha256(data).hexdigest():
            out.append({"name": entry["name"], "status": "unchanged",
                        "version": current.version})
            continue
        program = products.get(entry["program_code"] or "")
        if entry["program_code"] and program is None:
            raise LookupError(f"{org.name} has no product with code "
                              f"{entry['program_code']}.")
        template = await email_template_service.create_template(
            db, ctx, template_type=entry["type"], category=entry["category"],
            program_id=program.id if program else None, name=entry["name"],
            when_to_use=entry["when_to_use"],
            built_document=entry["built_document"], filename=filename, data=data)
        tags = template.tags_json or []
        out.append({"name": entry["name"], "status": "published",
                    "version": template.version, "tags": len(tags),
                    "always_asked": sum(1 for t in tags if t.get("kind") == "ask")})
    return out


async def run(org_name: str, folder: Path, *, dry_run: bool) -> list[dict[str, Any]]:
    from app.database import SessionLocal, init_db  # noqa: PLC0415

    await init_db()
    async with SessionLocal() as db:
        lines = await load(db, org_name=org_name, folder=folder)
        if dry_run:
            await db.rollback()
        else:
            await db.commit()
    return lines


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--org-name", required=True)
    parser.add_argument("--dir", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true",
                        help="do everything, print it, then roll it back")
    args = parser.parse_args(argv)
    if not os.environ.get("DATABASE_URL"):
        print("Set DATABASE_URL explicitly: this script writes to the database "
              "it names, and it must never be a guess.")
        return 2
    from app.config import get_settings  # noqa: PLC0415

    print(f"Database: {get_settings().resolved_database_url}")
    try:
        lines = await run(args.org_name, args.dir, dry_run=args.dry_run)
    except LookupError as exc:
        print(f"{exc} Nothing was changed.")
        return 1
    print("DRY RUN, nothing kept:" if args.dry_run else "Loaded:")
    for line in lines:
        extra = (f"  tags {line['tags']}, always asked {line['always_asked']}"
                 if line["status"] == "published" else "")
        print(f"  {line['status']:<10} v{line['version']}  {line['name']}{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
