"""A demo organisation for the sales head's screens (23 Oct 2026).

    python scripts/seed_sales_head_demo.py --org-name "Northwind Learning (demo)"
    python scripts/seed_sales_head_demo.py --org-name "..." --dry-run
    python scripts/seed_sales_head_demo.py --org-name "..." --again

Design: YuvipepSalesforceAI/docs/superpowers/specs/2026-10-23-sales-head-design.md
section 11. Creates ONE new organisation, through the ORM, with seven people
(a sales head, two sales leads, three sales agents, a relationship manager)
and about six months of invented history: ~120 clients moving through the
stages, meetings with summaries, tasks done on time, late and not at all,
follow-ups, messages both ways, the people at each client and the promises
made, field readings around one city, and AI usage. It deliberately includes
one deal or person for every alert on Pulse, and one agent whose report card
shows every consistency flag, so every screen can be shown.

* It refuses to run when an organisation with that name exists; with
  --again it adds nothing and prints the summary (passwords cannot be shown
  again, they are stored hashed).
* It never reads or writes another organisation's rows.
* Data is drawn from a fixed random seed; dates are relative to the run.
* Passwords are random and printed once. Everyone changes theirs on first
  sign-in, as with any staff member the org admin adds.
"""
from __future__ import annotations

import argparse
import asyncio
import random
import re
import secrets
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.core import clock  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.action_item import ActionItem  # noqa: E402
from app.models.assistant import AssistantTurn  # noqa: E402
from app.models.audit import AuditLog, LlmUsage  # noqa: E402
from app.models.base import new_id, utcnow  # noqa: E402
from app.models.comms import Approval, InboundMessage, Thread  # noqa: E402
from app.models.demo import Demo  # noqa: E402
from app.models.followup import FollowUp  # noqa: E402
from app.models.lead import ClientIntelligence, Contact, Lead, LeadStateHistory  # noqa: E402
from app.models.location import LocationPing  # noqa: E402
from app.models.meeting import Meeting, Transcript  # noqa: E402
from app.models.messaging import OutboundMessage  # noqa: E402
from app.models.organisation import Organisation, OrgSettings  # noqa: E402
from app.models.project import ClientCommitment, Project, Stakeholder  # noqa: E402
from app.models.proposal import Proposal  # noqa: E402
from app.models.relationship import RelationshipEngagement  # noqa: E402
from app.models.scheduled_meeting import ScheduledMeeting  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.work import AIDecision, Assignment  # noqa: E402

TIMEZONE = "Asia/Kolkata"
CITY = (12.9716, 77.5946)
BUDGET_USD = 50.0
PEOPLE = (
    ("Hema Rao", "sales_head", "sales"),
    ("Lata Menon", "sales_lead", "sales"),
    ("Kiran Shah", "sales_lead", "sales"),
    ("Asha Iyer", "sales_agent", "sales"),
    ("Bala Krishnan", "sales_agent", "sales"),
    ("Ravi Das", "sales_agent", "sales"),
    ("Meena Joseph", "relationship_manager", "relationship"),
)
POOR_PERFORMER = "Ravi Das"
SHOWCASE = "Juniper Collective"
SPECIAL = {"Granite Holdings", "Harbor Associates", "Lotus Network", "Saffron Labs", SHOWCASE,
           "Ember Works", "Cedar Partners", "Banyan Group", "Pinnacle Enterprises"}
FIRST = ("Amber", "Banyan", "Cedar", "Delta", "Ember", "Falcon", "Granite", "Harbor", "Indigo",
         "Juniper", "Kestrel", "Lotus", "Maple", "Nimbus", "Orchid", "Pinnacle", "Quartz",
         "Ridge", "Saffron", "Tidal", "Umber", "Vertex", "Willow", "Zenith", "Aspen", "Brook",
         "Coral", "Dune", "Fern", "Garnet")
SECOND = ("Group", "Partners", "Works", "Holdings", "Collective", "Associates", "Enterprises",
          "Labs", "Network", "Foundation", "Ventures", "Trust")
OUTCOMES = (("calling", 12), ("lost_early", 6), ("open", 22), ("active", 16), ("cold", 8),
            ("lost", 12), ("won", 8), ("delivering", 6), ("closed", 10))
SUMMARIES = (
    "Walked through the plan and agreed to start with a pilot. They want dates by next week.",
    "Discussed the second phase and who signs off. The owner wants a short call first.",
    "They liked the proposal but asked for a smaller first order. A revised quote is due.",
    "Reviewed progress so far. Two open questions on timing, both owned by us.",
    "First visit. They are comparing two options and decide at the end of the month.",
    "Agreed the scope and the start date. Paperwork goes out this week.",
)
PURPOSES = (("orchestrator.route", 30), ("agent.query", 12), ("agent.client", 8),
            ("agent.scheduling", 6), ("agent.proposal", 10), ("proposal.docx_tagfill", 4),
            ("proposal.docx_tagfill_answer", 6), ("conversation.analyse_meeting", 5),
            ("planner.generate_initial_plan", 3), ("communication.meeting_invite", 4),
            ("inbound.classify", 2), ("email.draft_custom", 2), ("client_draft.interpret", 4),
            ("vision.business_card", 2), ("assistant.day_reading", 2))
FAST, STRONG = "openai/gpt-5.4-nano", "google/gemini-2.5-flash"


class AlreadySeeded(Exception):
    """An organisation with this name exists and --again was not given."""


def _slug(name: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")[:60] or "demo"


def _pick(rng: random.Random, weighted):
    total = sum(w for _, w in weighted)
    x = rng.uniform(0, total)
    for value, w in weighted:
        x -= w
        if x <= 0:
            return value
    return weighted[-1][0]


class _Seeder:
    def __init__(self, db, org: Organisation, now: datetime, today: date, rng: random.Random):
        self.db, self.org, self.now, self.today, self.rng = db, org, now, today, rng
        self.tz = clock.zone(TIMEZONE)
        self.added: Counter = Counter()
        self.users: dict[str, User] = {}
        # The poor performer's empty working day: 4 to 6 days back.
        self.silent_day = next(
            self.today - timedelta(days=n) for n in (4, 5, 6)
            if (self.today - timedelta(days=n)).weekday() != 6)

    # ── plumbing ────────────────────────────────────────────────────────────
    def add(self, row):
        if getattr(row, "id", None) is None and hasattr(type(row), "id"):
            row.id = new_id()
        self.db.add(row)
        self.added[row.__tablename__] += 1
        return row

    def local(self, days_ago: float, hour: float = 11.0) -> datetime:
        day = self.today - timedelta(days=int(days_ago))
        at = clock.start_of_day_utc(day, self.tz) + timedelta(hours=hour)
        return min(at, self.now - timedelta(minutes=5))

    def when(self, at: datetime, user: User | None = None) -> datetime:
        """Keep every instant in the past, and the poor performer's empty
        working day empty."""
        at = min(at, self.now - timedelta(minutes=3))
        if user is not None and user.name == POOR_PERFORMER and \
                clock.local_date(at, self.tz) == self.silent_day:
            at -= timedelta(days=1)
        return at

    def u(self, name: str) -> User:
        return self.users[name]

    @property
    def agents(self):
        return [self.u(n) for n in ("Asha Iyer", "Bala Krishnan", "Ravi Das")]

    @property
    def leads_people(self):
        return [self.u("Lata Menon"), self.u("Kiran Shah")]

    # ── people ──────────────────────────────────────────────────────────────
    def people(self) -> list[dict]:
        logins = []
        for name, role, department in PEOPLE:
            password = secrets.token_urlsafe(9)
            first = name.split()[0].lower()
            user = self.add(User(
                org_id=self.org.id, email=f"{first}@{self.org.email_domain}", name=name,
                role=role, department=department, password_hash=hash_password(password),
                must_change_password=True,
                max_open_tasks=6 if name == POOR_PERFORMER else 8,
            ))
            user.created_at = self.now - timedelta(days=200)
            self.users[name] = user
            logins.append({"name": name, "role": role, "email": user.email,
                           "temp_password": password})
        return logins

    # ── one client ──────────────────────────────────────────────────────────
    def lead(self, name: str, *, owner: User, creator: User, created: datetime) -> Lead:
        lead = self.add(Lead(org_id=self.org.id, name=name, state="cold_calling",
                             owner_id=owner.id, created_at=created, last_activity_at=created,
                             city="Bengaluru", source="referral"))
        self.add(LeadStateHistory(org_id=self.org.id, lead_id=lead.id, from_state=None,
                                  to_state="cold_calling", changed_by=creator.id,
                                  changed_at=created,
                                  reason=f"Assigned to {owner.name} by {creator.name}"))
        self.add(AuditLog(org_id=self.org.id, user_id=creator.id, action="lead.created",
                          entity_type="lead", entity_id=lead.id,
                          detail={"name": name, "owner_id": owner.id}, at=created))
        return lead

    def move(self, lead: Lead, to_state: str, by, at: datetime, reason: str = "") -> None:
        by_id = by if isinstance(by, str) else by.id
        self.add(LeadStateHistory(org_id=self.org.id, lead_id=lead.id, from_state=lead.state,
                                  to_state=to_state, changed_by=by_id, changed_at=at,
                                  reason=reason or None))
        lead.state = to_state
        lead.last_activity_at = max(lead.last_activity_at or at, at)

    def contact(self, lead, by: User, at: datetime, name: str = "Front Office") -> Contact:
        c = self.add(Contact(org_id=self.org.id, lead_id=lead.id, name=name,
                             phone="+91 90000 00000", created_by=by.id, source="manual"))
        c.created_at = self.when(at, by)
        return c

    def note(self, lead, by: User, at: datetime) -> None:
        n = self.add(ClientIntelligence(org_id=self.org.id, lead_id=lead.id, added_by=by.id,
                                        note="Prefers short calls in the morning.",
                                        source="typed"))
        n.created_at = self.when(at, by)

    def email(self, lead, by: User, at: datetime, kind: str = "follow_up",
              status: str = "sent") -> OutboundMessage:
        at = self.when(at, by)
        m = self.add(OutboundMessage(
            org_id=self.org.id, kind=kind, channel="email", status=status, lead_id=lead.id,
            sender_user_id=by.id, to_address="contact@client.example.com",
            subject="Next steps", body="Thank you for your time today.",
            idempotency_key=new_id(), sent_at=at if status == "sent" else None,
            approved_by=by.id if status == "sent" else None,
        ))
        m.created_at = at - timedelta(minutes=20)
        if status in ("sent", "rejected"):
            self.add(Approval(org_id=self.org.id, entity_type="outbound_message",
                              entity_id=m.id, requested_from_user_id=by.id,
                              status="approved" if status == "sent" else "rejected",
                              requested_at=m.created_at, decided_at=at - timedelta(minutes=5)))
        return m

    def reply(self, lead, at: datetime, sentiment: str) -> None:
        if at >= self.now:
            return
        r = self.add(InboundMessage(org_id=self.org.id, channel="email",
                                    from_address="contact@client.example.com",
                                    body="Thanks, noted.", received_at=at,
                                    matched_lead_id=lead.id, sentiment=sentiment,
                                    intent="acknowledgement", status="processed"))
        r.created_at = at

    def meeting(self, lead, by: User, at: datetime, *, minutes=None, kind="negotiation",
                plan_state=None, attendees=()) -> Meeting:
        at = self.when(at, by)
        m = self.add(Meeting(org_id=self.org.id, lead_id=lead.id, agent_id=by.id,
                             status="completed", started_at=at, created_at=at,
                             duration_seconds=None if minutes is None else minutes * 60,
                             meeting_type=kind, plan_state=plan_state,
                             attendee_stakeholder_ids=list(attendees),
                             title=f"{lead.name} meeting"))
        if minutes is not None:
            self.add(Transcript(org_id=self.org.id, meeting_id=m.id, text="(recording)",
                                summary=self.rng.choice(SUMMARIES), language="english",
                                word_count=minutes * 120))
        return m

    def task(self, assignee: User, *, due: datetime, done: datetime | None, lead=None,
             meeting=None, note: str | None = "Done and confirmed with the client.",
             method: str = "in_app", status: str | None = None) -> ActionItem:
        t = self.add(ActionItem(
            org_id=self.org.id, title=self.rng.choice((
                "Send the revised quote", "Confirm the start date", "Share the plan",
                "Call the owner", "Book the next visit", "Collect the sign-off")),
            assignee_id=assignee.id, due_date=due,
            completed_at=None if done is None else self.when(done, assignee),
            status=status or ("done" if done else "open"), lead_id=getattr(lead, "id", None),
            meeting_id=getattr(meeting, "id", None),
            result_note=note if done else None, completion_method=method if done else None,
            source="meeting" if meeting else "manual", assigned_by="ai"))
        t.created_at = min(due - timedelta(days=4), self.now - timedelta(hours=1))
        if meeting is not None:
            overridden = self.rng.random() < 0.15
            self.add(AIDecision(org_id=self.org.id, decision_type="assignment",
                                engine="assignment", entity_type="action_item",
                                entity_id=t.id, reason="Best match on skills and load",
                                human_override="Changed by the sales lead" if overridden
                                else None, created_at=t.created_at))
            self.add(Assignment(org_id=self.org.id, action_item_id=t.id,
                                to_user_id=assignee.id, assigned_by="ai",
                                status="overridden" if overridden else "accepted",
                                decided_at=t.created_at))
        return t

    def followup(self, lead, owner: User, due: date, done: datetime | None,
                 message_id: str | None = None) -> None:
        self.add(FollowUp(org_id=self.org.id, lead_id=lead.id, owner_id=owner.id,
                          due_date=due, status="done" if done else "pending",
                          completed_at=None if done is None else self.when(done, owner),
                          message_id=message_id, created_by=owner.id))

    def project(self, lead, closer: User) -> tuple[Project, list[Stakeholder]]:
        p = self.add(Project(org_id=self.org.id, lead_id=lead.id, name=f"{lead.name} rollout",
                             sales_owner_id=closer.id, status="negotiation"))
        people = []
        for person, influence, role in (("Ms Kapoor", "decision_maker", "owner"),
                                        ("Mr Nair", "influencer", "operations_head"),
                                        ("Ms Pillai", "gatekeeper", "office_manager")):
            c = self.add(Contact(org_id=self.org.id, lead_id=lead.id, name=person,
                                 email=f"{person.split()[1].lower()}@client.example.com",
                                 source="meeting"))
            people.append(self.add(Stakeholder(org_id=self.org.id, project_id=p.id,
                                               contact_id=c.id, influence=influence,
                                               role_at_client=role)))
        return p, people

    def promise(self, project, direction: str, status: str, due: datetime) -> None:
        self.add(ClientCommitment(org_id=self.org.id, project_id=project.id,
                                  text="Share the revised schedule", direction=direction,
                                  status=status, due_date=due))

    # ── the bulk ────────────────────────────────────────────────────────────
    def bulk(self, names: list[str]) -> None:
        rng, now = self.rng, self.now
        for name in names:
            created = now - timedelta(days=rng.uniform(2, 180))
            creator = rng.choice(self.leads_people)
            owner = rng.choice(self.agents) if rng.random() < 0.8 else creator
            closer = creator if owner in self.agents else owner
            lead = self.lead(name, owner=owner, creator=creator, created=created)
            outcome = _pick(rng, OUTCOMES)
            t = created
            limit = now - timedelta(hours=2)

            def step(days_lo, days_hi):
                return t + timedelta(days=rng.uniform(days_lo, days_hi))

            if outcome == "calling":
                continue
            nxt = step(1, 15)
            if nxt >= limit:
                continue
            if outcome == "lost_early":
                self.move(lead, "lost_for_now", owner, self.when(nxt, owner), "No interest")
                continue
            self.contact(lead, owner, nxt - timedelta(days=rng.uniform(0.1, 1.5)))
            t = self.when(nxt, owner)
            self.move(lead, "open", owner, t, "Positive response on the cold call")
            self.email(lead, owner, t + timedelta(hours=2), kind="intro")
            if rng.random() < 0.6:
                due = clock.local_date(t + timedelta(days=4), self.tz)
                done = t + timedelta(days=rng.choice((3, 4, 6))) if rng.random() < 0.75 else None
                if done is not None and done >= limit:
                    done = None
                self.followup(lead, owner, due, done)
            if outcome == "open":
                self.touch(lead, owner, t)
                continue
            if outcome == "cold":
                nxt = step(15, 40)
                if nxt < limit:
                    self.move(lead, "cold", "system", nxt, "Quiet for 30 days")
                continue
            nxt = step(4, 25)
            if nxt >= limit:
                self.touch(lead, owner, t)
                continue
            t = nxt
            self.move(lead, "active", closer, t)
            project, people = self.project(lead, closer)
            for i in range(rng.randint(1, 3)):
                at = t + timedelta(days=rng.uniform(0.5, 12))
                if at >= limit:
                    break
                m = self.meeting(lead, closer, at, minutes=rng.randint(20, 70),
                                 kind=rng.choice(("first_visit", "negotiation", "review")),
                                 plan_state=_pick(rng, (("approved", 5), ("discarded", 1),
                                                        ("ready", 1), (None, 3))),
                                 attendees=[s.id for s in people[:rng.randint(1, 3)]])
                for _ in range(rng.randint(1, 3)):
                    assignee = rng.choice([owner, closer])
                    due = m.started_at + timedelta(days=rng.randint(2, 7))
                    roll = rng.random()
                    if roll < 0.7:
                        done = due - timedelta(hours=rng.randint(2, 30))
                    elif roll < 0.9:
                        done = due + timedelta(days=rng.randint(1, 4))
                    else:
                        done = None
                    if done is not None and done >= limit:
                        done = None
                    self.task(assignee, due=due, done=done, lead=lead, meeting=m)
                if rng.random() < 0.6:
                    self.reply(lead, m.started_at + timedelta(days=1),
                               _pick(rng, (("positive", 6), ("neutral", 3), ("negative", 1)))
                               if m.started_at < now - timedelta(days=12) else "positive")
            self.promise(project, "ours", "kept" if rng.random() < 0.8 else "broken",
                         t + timedelta(days=10))
            self.promise(project, "theirs", "kept" if rng.random() < 0.7 else "open",
                         t + timedelta(days=12))
            if outcome == "active":
                self.touch(lead, closer, t)
                continue
            sent_at = step(3, 15)
            if sent_at < limit:
                self.add(Proposal(org_id=self.org.id, lead_id=lead.id, program_id="demo",
                                  title=f"Proposal for {name}", status="sent",
                                  template_id="demo", template_version=1,
                                  content_md="(proposal)", created_by=closer.id,
                                  sent_at=sent_at,
                                  total_amount=rng.choice((0.0, 0.0, 450000.0, 1200000.0))))
                self.reply(lead, sent_at + timedelta(days=rng.uniform(1, 4)), "positive")
            nxt = step(7, 35)
            if nxt >= limit:
                self.touch(lead, closer, t)
                continue
            if outcome == "lost":
                self.move(lead, "lost_for_now", closer, nxt, "Chose another supplier")
                continue
            t = nxt
            self.move(lead, "execution_in_progress", closer, t, "Agreed")
            if rng.random() < 0.5:
                self.add(Demo(org_id=self.org.id, lead_id=lead.id,
                              scheduled_date=clock.local_date(t - timedelta(days=3), self.tz),
                              status="completed", completed_at=t - timedelta(days=3)))
            if outcome == "won":
                continue
            nxt = step(5, 20)
            if nxt >= limit:
                continue
            t = nxt
            self.move(lead, "client_execution_in_progress", closer, t)
            if outcome == "delivering":
                continue
            nxt = step(10, 40)
            if nxt < limit:
                self.move(lead, "closed", closer, nxt, "Delivered")

    def touch(self, lead, by: User, since: datetime) -> None:
        """Recent life on a deal still in play, at a spread of ages -- or, for
        a deal that has not moved in fifty days, what the real system does:
        it is marked cold a month or so after it stopped moving."""
        rng = self.rng
        if self.now - since > timedelta(days=50):
            self.move(lead, "cold", "system", since + timedelta(days=rng.uniform(30, 45)),
                      "Quiet for 30 days")
            return
        days = rng.choice((0.3, 1, 2, 4, 6, 9, 12, 16, 22, 30))
        at = self.now - timedelta(days=days)
        if at > since:
            if rng.random() < 0.5:
                self.note(lead, by, at)
            else:
                self.email(lead, by, at)

    # ── the deliberate cases ────────────────────────────────────────────────
    def cases(self) -> dict:
        lata, kiran = self.u("Lata Menon"), self.u("Kiran Shah")
        asha, bala, ravi = self.u("Asha Iyer"), self.u("Bala Krishnan"), self.u("Ravi Das")
        meena = self.u("Meena Joseph")
        out = {}

        # Critical: a deal gone quiet with a low score.
        quiet = self.lead("Granite Holdings", owner=asha, creator=lata,
                          created=self.local(70))
        self.contact(quiet, asha, self.local(61))
        self.move(quiet, "open", asha, self.local(60))
        self.move(quiet, "cold", "system", self.local(26), "Quiet for 30 days")

        # Critical: a proposal with no reply for twelve days.
        waiting = self.lead("Harbor Associates", owner=bala, creator=kiran,
                            created=self.local(80))
        self.contact(waiting, bala, self.local(71))
        self.move(waiting, "open", bala, self.local(70))
        self.move(waiting, "active", kiran, self.local(40))
        self.meeting(waiting, kiran, self.local(30), minutes=45, kind="negotiation",
                     plan_state="approved")
        self.add(Proposal(org_id=self.org.id, lead_id=waiting.id, program_id="demo",
                          title="Proposal for Harbor Associates", status="sent",
                          template_id="demo", template_version=1, content_md="(proposal)",
                          created_by=kiran.id, sent_at=self.local(12), total_amount=0.0))
        self.add(Thread(org_id=self.org.id, lead_id=waiting.id, contact_id="demo",
                        channel="email", last_direction="outbound",
                        last_message_at=self.local(12), owner_user_id=kiran.id))
        self.meeting(waiting, kiran, self.local(6, 15), minutes=25, kind="review")

        # Serious: an unhappy reply two days ago.
        unhappy = self.lead("Lotus Network", owner=asha, creator=lata, created=self.local(50))
        self.contact(unhappy, asha, self.local(41))
        self.move(unhappy, "open", asha, self.local(40))
        self.move(unhappy, "active", lata, self.local(20))
        self.reply(unhappy, self.local(2, 10), "negative")

        # Serious: a promise of ours broken.
        broken = self.lead("Saffron Labs", owner=bala, creator=lata, created=self.local(60))
        self.contact(broken, bala, self.local(51))
        self.move(broken, "open", bala, self.local(50))
        self.move(broken, "active", lata, self.local(25))
        project, _ = self.project(broken, lata)
        self.promise(project, "ours", "broken", self.local(4))
        self.note(broken, lata, self.local(1))

        # The deal page worth opening: everything on one client.
        show = self.lead(SHOWCASE, owner=asha, creator=kiran, created=self.local(55))
        self.contact(show, asha, self.local(46))
        self.move(show, "open", asha, self.local(45))
        self.email(show, asha, self.local(44), kind="intro")
        self.move(show, "active", kiran, self.local(30))
        project, people = self.project(show, kiran)
        boss = people[0]
        for days, minutes, kind, plan in ((28, 50, "first_visit", "approved"),
                                          (14, 40, "negotiation", "discarded"),
                                          (5, 35, "negotiation", "approved"),
                                          (2, 30, "review", "ready")):
            m = self.meeting(show, kiran, self.local(days, 15), minutes=minutes, kind=kind,
                             plan_state=plan, attendees=[boss.id, people[1].id])
            self.task(asha, due=m.started_at + timedelta(days=3),
                      done=m.started_at + timedelta(days=2), lead=show, meeting=m)
        self.add(Demo(org_id=self.org.id, lead_id=show.id,
                      scheduled_date=self.today - timedelta(days=20), status="completed",
                      completed_at=self.local(20)))
        self.add(Proposal(org_id=self.org.id, lead_id=show.id, program_id="demo",
                          title="Proposal for Juniper Collective", status="sent",
                          template_id="demo", template_version=1, content_md="(proposal)",
                          created_by=kiran.id, sent_at=self.local(9), total_amount=850000.0))
        self.reply(show, self.local(7), "positive")
        self.email(show, kiran, self.local(1, 16))
        self.followup(show, asha, self.today - timedelta(days=3), self.local(3, 12))
        self.promise(project, "ours", "kept", self.local(15))
        self.promise(project, "theirs", "kept", self.local(10))
        self.add(ScheduledMeeting(org_id=self.org.id, lead_id=show.id,
                                  meeting_date=self.today + timedelta(days=3),
                                  start_time="11:00", organizer_id=kiran.id,
                                  purpose="Sign-off meeting"))
        out["showcase_lead_id"] = show.id

        # Ready to buy again: two delivered clients with a relationship manager.
        for name, open_hint in (("Banyan Group", True), ("Pinnacle Enterprises", False)):
            done = self.lead(name, owner=bala, creator=lata, created=self.local(170))
            self.contact(done, bala, self.local(161))
            self.move(done, "open", bala, self.local(160))
            self.move(done, "active", lata, self.local(140))
            self.move(done, "execution_in_progress", lata, self.local(110))
            self.move(done, "client_execution_in_progress", lata, self.local(90))
            self.move(done, "closed", lata, self.local(60))
            self.add(RelationshipEngagement(
                org_id=self.org.id, lead_id=done.id, manager_id=meena.id,
                assigned_by=lata.id, started_at=self.local(59),
                opportunity_status="open" if open_hint else "none",
                opportunity_reason="Asked about adding a second site next year"
                if open_hint else None,
                opportunity_at=self.local(3) if open_hint else None))
            self.meeting(done, meena, self.local(3 if open_hint else 20, 12), minutes=25,
                         kind="relationship")

        # The poor performer: every flag, and two warnings on Pulse.
        silent = self.lead("Ember Works", owner=ravi, creator=lata, created=self.local(30))
        self.move(silent, "open", ravi, self.local(3, 11))           # nothing behind it
        chased = self.lead("Cedar Partners", owner=ravi, creator=lata, created=self.local(40))
        self.contact(chased, ravi, self.local(36))
        self.move(chased, "open", ravi, self.local(35))
        self.followup(chased, ravi, self.today - timedelta(days=1), self.local(1, 12))
        burst_at = self.local(2, 16)
        for i in range(6):                                            # closed in a burst
            self.task(ravi, due=self.local(2, 18), done=burst_at + timedelta(minutes=i * 1.5),
                      note=None)
        for days in (3, 5, 8, 10):                                    # overdue
            self.task(ravi, due=self.local(days, 18), done=None)
        for days in (2, 4, 6, 9, 12):                                 # coming up
            self.task(ravi, due=self.now + timedelta(days=days), done=None)
        self.ping(ravi, self.local(3, 10), mock=True)
        for days in (0, 1, 2):
            self.ping(ravi, self.local(days, 9.5) if days else self.now - timedelta(hours=1),
                      status="permission_denied")
        self.note(chased, ravi, self.local(6, 12))
        out["poor_performer"] = ravi.name
        return out

    # ── the background hum: readings, sign-ins, Jarvis, AI calls ────────────
    def ping(self, user: User, at: datetime, *, status="ok", mock=False, approximate=False):
        at = self.when(at, user)
        lat = lng = None
        if status == "ok":
            lat = CITY[0] + self.rng.uniform(-0.06, 0.06)
            lng = CITY[1] + self.rng.uniform(-0.06, 0.06)
        self.add(LocationPing(org_id=self.org.id, user_id=user.id, client_ref=new_id(),
                              status=status, lat=lat, lng=lng,
                              accuracy_m=None if lat is None else self.rng.uniform(8, 40),
                              is_mock=mock, approximate=approximate,
                              trigger=self.rng.choice(("open", "resume")),
                              captured_at=at, received_at=at))

    def hum(self) -> None:
        rng = self.rng
        tracked = self.agents + self.leads_people
        team = tracked + [self.u("Meena Joseph")]
        for back in range(30, -1, -1):
            day = self.today - timedelta(days=back)
            if day.weekday() == 6:
                continue
            for person in team + [self.u("Hema Rao")]:
                if person.name == POOR_PERFORMER and (day == self.silent_day or back <= 2):
                    continue
                login = clock.start_of_day_utc(day, self.tz) + timedelta(
                    hours=rng.uniform(8.8, 9.6))
                if login < self.now:
                    self.add(AuditLog(org_id=self.org.id, user_id=person.id,
                                      action="auth.login", at=self.when(login, person)))
            for person in tracked:
                if person.name == POOR_PERFORMER and (day == self.silent_day or back <= 2):
                    continue
                hours = sorted(rng.uniform(9.3, 18.2) for _ in range(rng.randint(2, 4)))
                for h in hours:
                    at = clock.start_of_day_utc(day, self.tz) + timedelta(hours=h)
                    if back == 0:
                        continue
                    roll = rng.random()
                    status = "gps_off" if roll < 0.04 else "timeout" if roll < 0.07 else "ok"
                    self.ping(person, at, status=status,
                              approximate=person.name == "Bala Krishnan" and rng.random() < 0.3)
            for person in team:
                if person.name == POOR_PERFORMER and day == self.silent_day:
                    continue
                if rng.random() < 0.45:
                    start = clock.start_of_day_utc(day, self.tz) + timedelta(
                        hours=rng.uniform(10, 17))
                    session = new_id()
                    for i in range(rng.randint(2, 6)):
                        turn = self.add(AssistantTurn(
                            org_id=self.org.id, user_id=person.id, session_id=session,
                            seq=i, role="user" if i % 2 == 0 else "assistant",
                            content="(asked about a client)" if i % 2 == 0 else "(answered)",
                            agent="query" if i % 2 else None))
                        turn.created_at = self.when(start + timedelta(minutes=i), person)
        # Today: everyone who sends readings opened the app this morning.
        for person in tracked:
            if person.name == POOR_PERFORMER:
                continue
            for minutes in (100, 40):
                self.ping(person, self.now - timedelta(minutes=minutes))
        # Meetings, emails and follow-ups this week, for the Pulse week view.
        monday = self.today - timedelta(days=self.today.weekday())
        open_leads = [lead for lead in self._leads
                      if lead.state in ("open", "active") and lead.name not in SPECIAL]
        for i in range((self.today - monday).days + 1):
            day = monday + timedelta(days=i)
            if not open_leads:
                break
            lead = rng.choice(open_leads)
            start = clock.start_of_day_utc(day, self.tz)
            at = min(start + timedelta(hours=10), self.now - timedelta(hours=3))
            if at > start:
                closer = rng.choice(self.leads_people)
                self.meeting(lead, closer, at, minutes=rng.randint(20, 50), kind="review",
                             plan_state="approved")
                self.email(lead, closer, at + timedelta(hours=1))
                self.followup(lead, self.u("Asha Iyer"), day, at + timedelta(hours=2))
        # AI calls over the last sixty days.
        for back in range(60, -1, -1):
            for _ in range(rng.randint(6, 12)):
                at = self.now - timedelta(days=back, hours=rng.uniform(0.2, 9))
                strong = rng.random() < 0.15
                user = rng.choice(team) if rng.random() < 0.7 else None
                self.add(LlmUsage(
                    org_id=self.org.id, user_id=getattr(user, "id", None),
                    provider="openrouter", model=STRONG if strong else FAST,
                    purpose=_pick(rng, PURPOSES), input_tokens=rng.randint(400, 4000),
                    output_tokens=rng.randint(50, 900),
                    cost_usd=round(rng.uniform(0.003, 0.02) if strong
                                   else rng.uniform(0.0003, 0.002), 6),
                    duration_ms=rng.randint(600, 6000),
                    error="timeout" if rng.random() < 0.01 else None, at=at))

    @property
    def _leads(self) -> list[Lead]:
        return [row for row in self.db.new if isinstance(row, Lead)]


async def _existing(db, name: str) -> Organisation | None:
    return (await db.execute(select(Organisation).where(Organisation.name == name))
            ).scalar_one_or_none()


async def seed(db, *, org_name: str, today: date, rng_seed: int = 23,
               now: datetime | None = None, again: bool = False) -> dict:
    """Create the demo organisation in `db` (the caller commits). Returns the
    org id, the seven logins, and what was added."""
    found = await _existing(db, org_name)
    if found is not None:
        if not again:
            raise AlreadySeeded(f"An organisation called {org_name!r} already exists.")
        users = (await db.execute(select(User).where(User.org_id == found.id)
                                  .order_by(User.created_at))).scalars().all()
        show = (await db.execute(select(Lead.id).where(Lead.org_id == found.id,
                                                       Lead.name == SHOWCASE))).scalar()
        return {"org_id": found.id, "org_name": found.name, "added": {},
                "logins": [{"name": u.name, "role": u.role, "email": u.email,
                            "temp_password": None} for u in users],
                "poor_performer": POOR_PERFORMER, "showcase_lead_id": show}

    now = now or utcnow()
    slug = _slug(org_name)
    if (await db.execute(select(func.count()).select_from(Organisation)
                         .where(Organisation.slug == slug))).scalar_one():
        slug = f"{slug}-{new_id()[:6]}"
    org = Organisation(id=new_id(), name=org_name, slug=slug,
                       email_domain=f"{slug}.example.com")
    db.add(org)
    db.add(OrgSettings(org_id=org.id, timezone=TIMEZONE, llm_monthly_budget_usd=BUDGET_USD))
    rng = random.Random(rng_seed)
    s = _Seeder(db, org, now, today, rng)
    logins = s.people()
    pool = [f"{a} {b}" for a in FIRST for b in SECOND if f"{a} {b}" not in SPECIAL]
    rng.shuffle(pool)
    s.bulk(pool[:120])
    cases = s.cases()
    s.hum()
    await db.flush()
    return {"org_id": org.id, "org_name": org_name, "logins": logins,
            "added": dict(sorted(s.added.items())), **cases}


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--org-name", required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="build everything, print the summary, then roll back")
    parser.add_argument("--again", action="store_true",
                        help="the org exists: add nothing, print the summary")
    args = parser.parse_args(argv)

    from app.config import get_settings
    from app.database import SessionLocal, engine, init_db

    print(f"Database: {get_settings().resolved_database_url}")
    await init_db()
    async with SessionLocal() as db:
        try:
            now = utcnow()
            summary = await seed(db, org_name=args.org_name,
                                 today=clock.local_date(now, clock.zone(TIMEZONE)),
                                 now=now, again=args.again)
        except AlreadySeeded as exc:
            print(f"{exc} Nothing was changed. Use --again to see its summary.")
            await engine.dispose()
            return 1
        if args.dry_run:
            await db.rollback()
        else:
            await db.commit()
    await engine.dispose()
    print(f"{'DRY RUN, nothing kept: ' if args.dry_run else ''}"
          f"{summary['org_name']} ({summary['org_id']})")
    for login in summary["logins"]:
        print(f"  {login['role']:<22} {login['name']:<15} {login['email']:<45} "
              f"{login['temp_password'] or '(unchanged)'}")
    for table, n in summary["added"].items():
        print(f"  + {n:>5} {table}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
