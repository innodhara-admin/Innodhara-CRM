#!/usr/bin/env python3
r"""meeting3.py -- THIRD meeting for the DATACENTRE demo (Workflow2).

Delivery has started and it is going wrong. This is the awkward meeting, and
it is where the app earns its money. Five different machines have to fire from
one recording.

USE
  Same as before: open the SAME lead -> Meetings -> Record meeting ->
  consent -> then  python meeting3.py

WHAT THIS MEETING TRIGGERS
  1. A COMPLAINT              - an engineer arrived late and a window was lost.
                                Must become an INCIDENT, at severity, with both
                                leads paged. (Not just a task.)
  2. A CONTRADICTION          - Kavitha says the December handover holds,
                                Devendra says it must move to January. Two
                                people, two positions, at the same time.
                                The re-plan must be HELD, not silently applied,
                                and BOTH positions named with who said what.
  3. A DIFFERENT SITE         - Chennai is mentioned, with its own head. She is
                                a real person at this client, but she is NOT a
                                stakeholder on THIS project.
  4. A VENDOR SLIP            - the busway is a week late.
  5. A PAYMENT QUERY          - hold the invoice until the reconciliation.

  Plus new promises both ways, from a MERGE rather than a first meeting.

WHAT TO WATCH ON SCREEN
  * Incidents goes 0 -> 1, and both leads get an escalation
  * Conflicts tab shows the December-versus-January disagreement, naming both
  * The new plan sits in DRAFT, held by the conflict - the live plan is untouched
  * No approval is even offered for the held plan
  * Chennai adds a contact but NO stakeholder on this project
  * The commitment register grows again

Flags: --regen  --no-play  --no-wait
"""
from __future__ import annotations

from pathlib import Path

from _speak import run

HERE = Path(__file__).resolve().parent
OUT_WAV = HERE / "meeting3.wav"
TITLE = "MEETING 3  --  Delivery review: Meridian Data Centres (it goes wrong)"

LINES: list[tuple[str, str, str]] = [
    ("Siva (YuviPep)", "David",
     "Thanks for meeting us mid delivery. I know there are some issues. Let us "
     "go through them."),
    ("Devendra Shah", "David",
     "There is one I want on record first. Your engineer arrived forty minutes "
     "late for the Tuesday maintenance window. We lost the window entirely and "
     "the hall could not be energised that day. That is not acceptable."),
    ("Siva (YuviPep)", "David",
     "I am very sorry. That should not have happened. I will look into it "
     "personally and send you a written explanation."),
    ("Devendra Shah", "David",
     "Please do. I need that write up by Thursday so I can show it to my "
     "management."),
    ("Siva (YuviPep)", "David",
     "You will have the incident write up by Thursday. Now, where are we on "
     "the handover date?"),
    ("Kavitha Rao", "Zira",
     "The handover date does not move. We hand over before the December "
     "change freeze, exactly as agreed. My board has already been told "
     "December."),
    ("Devendra Shah", "David",
     "I disagree, and I have to be honest about it. With the lost window and "
     "the busway delay, December is not achievable. We must move the handover "
     "to January."),
    ("Kavitha Rao", "Zira",
     "No. December stands. I am not going back to the board with a new date."),
    ("Devendra Shah", "David",
     "And I am telling you the site will not be ready. January is the "
     "realistic date."),
    ("Siva (YuviPep)", "David",
     "I hear two different positions. I am not going to pick one in this room. "
     "I will record both and come back to you with a plan for each."),
    ("Kavitha Rao", "Zira",
     "That is fair. Take it away and come back to us."),
    ("Siva (YuviPep)", "David",
     "On the vendor side, our supplier RackLine has told us the busway is "
     "running a week late. We are chasing them daily."),
    ("Devendra Shah", "David",
     "A week late on the busway pushes hall three, which is exactly my point "
     "about January."),
    ("Kavitha Rao", "Zira",
     "There is also a commercial matter. Please hold the current invoice. Our "
     "finance team is reconciling the rack count against what was actually "
     "commissioned, and I do not want it chased in the meantime."),
    ("Siva (YuviPep)", "David",
     "Understood. We will pause the invoice reminders until your finance team "
     "confirms the reconciliation."),
    ("Kavitha Rao", "Zira",
     "Separately, and this is a different project entirely, we are building a "
     "new site at Chennai next year. Ms. Priya Menon heads that site."),
    ("Siva (YuviPep)", "David",
     "Understood. Chennai is separate work, so I will keep it out of this "
     "engagement and follow up on it on its own."),
    ("Kavitha Rao", "Zira",
     "Yes. Please do not mix Chennai into the Hinjewadi commissioning. It has "
     "its own budget and its own timeline."),
    ("Devendra Shah", "David",
     "One more thing we owe you. We will confirm the January window in writing "
     "if it comes to that, so you are not left guessing."),
    ("Siva (YuviPep)", "David",
     "Thank you. To summarise. I send the incident write up by Thursday. I "
     "come back with a plan for both the December and the January positions. "
     "We chase RackLine on the busway. The invoice reminders are paused until "
     "your reconciliation. Chennai is handled separately. And you confirm the "
     "January window in writing if it is needed."),
    ("Kavitha Rao", "Zira",
     "That is a fair summary of where we are."),
]

if __name__ == "__main__":
    run(TITLE, LINES, OUT_WAV)
