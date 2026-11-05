#!/usr/bin/env python3
r"""meeting1.py -- FIRST meeting for the DATACENTRE demo (Workflow2).

Siva (YuviPep sales lead) meets MERIDIAN DATA CENTRES for the first time.
Speaks the whole conversation aloud and saves meeting1.wav next to this file.

USE
  1. In the app: open the "Meridian Data Centres" lead -> Meetings tab ->
     Record meeting -> consent (verbal) -> recording starts.
  2. Laptop volume UP, phone near the speaker.
  3. Run:  python meeting1.py     (ENTER to play; STOP in the app when done)

WHAT THIS MEETING ESTABLISHES  (meeting2 later CHANGES it)
  * Programme : DC Commissioning & Handover
  * Scope     : 2 halls, 120 racks, power-on + load-bank checks, handover pack
  * Dates     : start 1 September, handover before the December change freeze
  * People    : Kavitha Rao  (Head of Infrastructure)  -> decision maker
                Devendra Shah (Critical Facilities Mgr) -> day-to-day contact
                Fatima Sheikh (Security & Access)       -> passes / escorts
  * Promises  : ours   - full proposal with commercials by Friday
                ours   - commissioning schedule once passes are cleared
                theirs - single-line diagrams and access passes before start
  * Work the AI should split by skill: site access & escorts, commissioning
    schedule, rack acceptance checks, daily client reports, operator
    enablement, and the proposal itself.

Flags: --regen  --no-play  --no-wait
"""
from __future__ import annotations

from pathlib import Path

from _speak import run

HERE = Path(__file__).resolve().parent
OUT_WAV = HERE / "meeting1.wav"
TITLE = "MEETING 1  --  First meeting: Meridian Data Centres (Commissioning)"

LINES: list[tuple[str, str, str]] = [
    ("Siva (YuviPep)", "David",
     "Good morning. Thank you for making time today at Meridian Data Centres. "
     "I am Siva from YuviPep."),
    ("Kavitha Rao", "Zira",
     "Welcome Siva. I am Kavitha Rao, Head of Infrastructure. I will be taking "
     "the final decision on this engagement."),
    ("Devendra Shah", "David",
     "I am Devendra Shah, the Critical Facilities Manager. I will be your main "
     "point of contact for the day to day work on site."),
    ("Fatima Sheikh", "Hazel",
     "And I am Fatima Sheikh. I look after site security and access. Any "
     "engineer who comes on site has to be cleared through me."),
    ("Siva (YuviPep)", "David",
     "Perfect. As discussed, we would like to run our D C Commissioning and "
     "Handover programme for your new capacity at the Hinjewadi campus."),
    ("Kavitha Rao", "Zira",
     "Yes. We are bringing two halls live. Hall one and hall two. That is one "
     "hundred and twenty racks in total."),
    ("Siva (YuviPep)", "David",
     "Understood. For one hundred and twenty racks across two halls I would "
     "recommend rack level acceptance on every rack, power on and load bank "
     "checks per hall, and one documented handover pack for the site."),
    ("Devendra Shah", "David",
     "That matches what we need. The handover pack matters most to me. My team "
     "has to run this hall after you leave, and right now we have nothing "
     "written down."),
    ("Siva (YuviPep)", "David",
     "That is exactly what the pack is for. When would you like us to start?"),
    ("Kavitha Rao", "Zira",
     "We want to start on the first of September. And everything must be "
     "handed over before the December change freeze. Nothing goes into "
     "production after that."),
    ("Siva (YuviPep)", "David",
     "Noted. Start first of September, full handover before the December "
     "freeze. Fatima, what do you need from us on access?"),
    ("Fatima Sheikh", "Hazel",
     "I need the names and identity documents of every engineer at least ten "
     "working days before they arrive. No exceptions. And each visit needs an "
     "escort booked in advance."),
    ("Siva (YuviPep)", "David",
     "We will send the engineer list well ahead of that. Devendra, will you be "
     "able to give us the single line diagrams and the rack elevation drawings?"),
    ("Devendra Shah", "David",
     "Yes. I will share the single line diagrams and the access passes before "
     "the start date. You will have both from my side."),
    ("Kavitha Rao", "Zira",
     "One more thing. We would like your team to train our own operators as "
     "part of this, so we are not dependent on you afterwards."),
    ("Siva (YuviPep)", "David",
     "We can do that. We will plan operator enablement sessions alongside the "
     "commissioning so your staff learn on the real equipment."),
    ("Devendra Shah", "David",
     "Good. And please send us a daily commissioning report while you are on "
     "site. I have to brief the group every morning."),
    ("Siva (YuviPep)", "David",
     "Understood. A short written report at the end of each commissioning day. "
     "Kavitha, on commercials, I will prepare and send the full proposal to "
     "you by Friday with Devendra in copy."),
    ("Kavitha Rao", "Zira",
     "Please do. I will review it and come back to you."),
    ("Siva (YuviPep)", "David",
     "I will also share the commissioning schedule once Fatima has cleared the "
     "passes, so your team can plan around the windows."),
    ("Fatima Sheikh", "Hazel",
     "Thank you. Send me the engineer names as early as you can and I will "
     "start the clearance."),
    ("Siva (YuviPep)", "David",
     "To summarise. Two halls, one hundred and twenty racks, power on and load "
     "bank checks, one handover pack, operator enablement for your team, start "
     "first of September, handover before the December freeze. I send the "
     "proposal by Friday and the schedule after clearance. You send the single "
     "line diagrams and the access passes before we start."),
    ("Kavitha Rao", "Zira",
     "That is a fair summary. We look forward to it."),
]

if __name__ == "__main__":
    run(TITLE, LINES, OUT_WAV)
