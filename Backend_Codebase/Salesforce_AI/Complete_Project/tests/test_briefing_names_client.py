"""The Home briefing names each task's client (customer ask, 21 Sep 2026).

"A task about ABC School should say so, and tapping it should reach that
school's lead screen." The dashboard the customer means is the briefing on
Home (a Sales Lead has no Tasks tab at all). Each task line now ends with the
client as a link the app opens as that lead: `yuvipep://lead/<id>`. The client
is the task's own lead, else its project's lead; a task with neither is left
as it was. The "title (due …)" text stays contiguous, as before.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.engines import assistant_engine
from app.models.action_item import ActionItem
from app.models.lead import Lead
from app.models.project import Project
from app.models.user import User
from tests.conftest import auth, create_org


async def test_each_task_line_names_and_links_its_client(client, super_token):
    org = await create_org(client, super_token, name="Brief Co", slug="brief-co",
                           domain="brief-example.com")
    me = (await client.get("/api/v1/auth/me", headers=auth(org["admin_token"]))).json()
    past = datetime.utcnow() - timedelta(days=3)
    async with SessionLocal() as db:
        abc = Lead(org_id=org["id"], name="ABC School")
        odd = Lead(org_id=org["id"], name="Sri [Main] Campus")
        ibc = Lead(org_id=org["id"], name="IBC Academy")
        db.add_all([abc, odd, ibc])
        await db.flush()
        project = Project(org_id=org["id"], lead_id=ibc.id, name="IBC rollout")
        db.add(project)
        await db.flush()
        db.add_all([
            ActionItem(org_id=org["id"], assignee_id=me["user_id"], lead_id=abc.id,
                       title="Send the fee sheet", priority="P1", due_date=past),
            ActionItem(org_id=org["id"], assignee_id=me["user_id"], project_id=project.id,
                       title="Review the proposal", priority="P2", due_date=past),
            ActionItem(org_id=org["id"], assignee_id=me["user_id"], lead_id=odd.id,
                       title="Book the hall", priority="P2"),
            ActionItem(org_id=org["id"], assignee_id=me["user_id"],
                       title="Internal housekeeping", priority="P3"),
        ])
        await db.commit()
        user = (await db.execute(select(User).where(User.id == me["user_id"]))).scalar_one()
        body = (await assistant_engine.build_daily_digest(db, org_id=org["id"], user=user)).content_md
        ids = {lead.name: lead.id for lead in (abc, odd, ibc)}

    due = f"{past:%d %b}"
    assert (f"- [P1] Send the fee sheet (due {due}) · "
            f"[ABC School](yuvipep://lead/{ids['ABC School']})") in body
    # Through the project when the task has no lead of its own.
    assert (f"- [P2] Review the proposal (due {due}) · "
            f"[IBC Academy](yuvipep://lead/{ids['IBC Academy']})") in body
    # Brackets in a name cannot break the link.
    assert f"[Sri \\[Main\\] Campus](yuvipep://lead/{ids['Sri [Main] Campus']})" in body
    # No client: the line is exactly what it always was.
    assert "- [P3] Internal housekeeping\n" in body + "\n"
