#!/usr/bin/env python3
r"""meeting2.py -- SECOND meeting for the DATACENTRE demo (Workflow2).

Three weeks on. The scope grows, a date moves, one item is dropped, and a new
decision maker appears. This is the MERGE test: the plan must UPDATE, not be
rewritten, and every task from meeting 1 must survive with its status.

USE
  Same as meeting1: open the SAME lead -> Meetings -> Record meeting ->
  consent -> then  python meeting2.py

WHAT THIS MEETING CHANGES  (against meeting1)
  * Racks     120 -> 160        (hall three is being brought forward)
  * Start     1 Sep -> 15 Sep   (a UPS module slipped at the supplier)
  * DEMO      the readiness walkthrough moves 9 Sep -> 18 Sep, 14:30
  * DROPPED   the separate hot-spot mapping exercise (folded into commissioning)
  * ADDED     formal operator certification for 20 staff
  * NEW PERSON  Mr. Anand Krishnan, Group C T O -> approves the final budget
  * NEW PROMISES
      ours   - revised commissioning schedule by the fifteenth
      theirs - the list of operator names before the first session

PREREQUISITE - do this BEFORE recording
  A demo must already be booked on 9 September, or the walkthrough ask has
  nothing to move. Book it from the lead: Book demo -> 9 Sep -> 10:30.
  See DEMO_WALKTHROUGH.md part 6.1.

WHAT TO WATCH ON SCREEN
  * A NEW plan version, held behind an approval - the old one stays active
  * Meeting-1 tasks still there, with their status
  * The dropped item cancelled only when the new plan is ACTIVATED
  * Anand Krishnan created as a contact AND a stakeholder, from speech alone
  * New commitments appear (the register is not write-once)
  * F63: on ACTIVATION the demo row itself moves to 18 Sep 14:30 and an
    UPDATED CLIENT INVITE is drafted. The failure this tests for is the AI
    re-dating some unrelated task whose title mentions "demo" and leaving the
    client's calendar entry untouched.

Flags: --regen  --no-play  --no-wait
"""
from __future__ import annotations

from pathlib import Path

from _speak import run

HERE = Path(__file__).resolve().parent
OUT_WAV = HERE / "meeting2.wav"
TITLE = "MEETING 2  --  Scope review: Meridian Data Centres (the plan learns)"

LINES: list[tuple[str, str, str]] = [
    ("Siva (YuviPep)", "David",
     "Thanks for the update call. I have the commissioning plan open in front "
     "of me."),
    ("Kavitha Rao", "Zira",
     "Good. A few things have changed since we last met, Siva. I have also "
     "asked our Group C T O to join us."),
    ("Anand Krishnan", "David",
     "Hello. I am Anand Krishnan, Group C T O. I approve the final budget for "
     "all capacity work across our sites."),
    ("Siva (YuviPep)", "David",
     "Good to meet you Anand. Kavitha, what has changed?"),
    ("Kavitha Rao", "Zira",
     "We are bringing hall three forward. So instead of one hundred and twenty "
     "racks it is now one hundred and sixty racks across three halls."),
    ("Siva (YuviPep)", "David",
     "Understood. One hundred and sixty racks, three halls. That changes the "
     "acceptance effort and the commercials."),
    ("Devendra Shah", "David",
     "There is a second change. One of our U P S modules slipped at the "
     "supplier. We cannot energise on the first of September. Please move the "
     "start to the fifteenth of September."),
    ("Siva (YuviPep)", "David",
     "Start moves from the first to the fifteenth of September. Does the "
     "December freeze still hold?"),
    ("Kavitha Rao", "Zira",
     "The December freeze holds. That has not moved."),
    ("Devendra Shah", "David",
     "There is one more date. You have a readiness walkthrough booked with us "
     "on the ninth of September. That is now too early, because the halls will "
     "not be powered. Please move the walkthrough to the eighteenth of "
     "September."),
    ("Siva (YuviPep)", "David",
     "So the site walkthrough moves from the ninth of September to the "
     "eighteenth of September. Shall we keep the same time?"),
    ("Devendra Shah", "David",
     "Make it half past two in the afternoon on the eighteenth. The morning is "
     "taken up by the supplier."),
    ("Siva (YuviPep)", "David",
     "Noted. The walkthrough moves to the eighteenth of September at half past "
     "two. I will make sure the updated invitation reaches you."),
    ("Devendra Shah", "David",
     "Also, we no longer need the separate hot spot mapping exercise. Your "
     "commissioning already measures the thermal behaviour rack by rack, so "
     "doing it twice is a waste of everyone's time. Please drop it."),
    ("Siva (YuviPep)", "David",
     "Agreed, we will drop the separate hot spot mapping and keep the thermal "
     "readings inside the commissioning itself."),
    ("Anand Krishnan", "David",
     "One addition from my side. I want your team to formally certify our "
     "operators, not just train them. Twenty staff. I want a certificate we "
     "can show in an audit."),
    ("Siva (YuviPep)", "David",
     "We can turn the enablement into a formal certification for twenty "
     "operators, with an assessment at the end and a certificate each."),
    ("Anand Krishnan", "David",
     "Good. That is what I will be approving the budget against."),
    ("Siva (YuviPep)", "David",
     "Understood. I will send you a revised commissioning schedule by the "
     "fifteenth, reflecting three halls and the new start date."),
    ("Devendra Shah", "David",
     "And we will give you the list of operator names before the first "
     "session, so you can prepare the assessment."),
    ("Kavitha Rao", "Zira",
     "Fatima will need the updated engineer list too, since you will now have "
     "more people on site."),
    ("Siva (YuviPep)", "David",
     "We will send the updated engineer list to Fatima as soon as the revised "
     "schedule is fixed."),
    ("Siva (YuviPep)", "David",
     "So to confirm. One hundred and sixty racks over three halls. Start the "
     "fifteenth of September. The readiness walkthrough moves from the ninth "
     "to the eighteenth of September at half past two. December freeze "
     "unchanged. Hot spot mapping dropped. Formal certification added for "
     "twenty operators. I send the revised schedule by the fifteenth, you send "
     "the operator names before the first session."),
    ("Kavitha Rao", "Zira",
     "Correct on all points."),
    ("Anand Krishnan", "David",
     "Send me the revised commercials as well. I will approve from my side."),
]

if __name__ == "__main__":
    run(TITLE, LINES, OUT_WAV)
