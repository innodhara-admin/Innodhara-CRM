#!/usr/bin/env python3
r"""
meeting1.py  --  FIRST meeting recording for the YuviPep app demo.

This is the "first meeting" between our sales lead (Siva) and a brand-new
client, ORCHID INTERNATIONAL SCHOOL. When you run it, it speaks the whole
conversation out loud (using the voices already built into Windows) and saves
it as  meeting1.wav  next to this file.

HOW TO USE IT IN THE DEMO
  1. On the phone, open the lead "Orchid International School" and start a
     recording (Record meeting -> confirm consent -> the app is now listening).
  2. Turn your laptop volume UP and hold the phone near the speaker.
  3. Run:   python meeting1.py
  4. It builds the audio (first time only), shows the script, then waits.
     Press ENTER and it plays the meeting. Let it finish, then press STOP in
     the app.

What this meeting establishes (so meeting2.py can later CHANGE it):
  * Program: IBC STEM, for grades 6-8, about 40 students
  * 12 workshops, 40 student maker kits, 1 annual showcase
  * Program starts on the 15th of August; showcase in December
  * Three people at the school:
        - Principal  Mrs. Nair   -> the decision maker
        - Coordinator Mr. Arjun  -> the day-to-day contact
        - Admin       Ms. Divya  -> scheduling / campus access
  * Work to be split by the AI: curriculum design, materials/content,
    logistics + kit procurement, facilitator training + a teacher pilot,
    proposal preparation, keeping the principal updated.

Flags:
  --regen    rebuild meeting1.wav even if it already exists
  --no-play  build the audio only, do not play it
  --no-wait  play immediately, do not wait for you to press ENTER

No internet, no API key, no extra install -- it uses Windows' built-in
System.Speech voices (David / Zira / Hazel).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_WAV = HERE / "meeting1.wav"
TITLE = "MEETING 1  --  First meeting: Orchid International School (IBC STEM)"

# Each line = (speaker label, Windows-voice hint, spoken text).
# Our side speaks in the male "David" voice; the school's people alternate
# between the "Zira" and "Hazel" voices so the recording sounds like a real
# multi-person meeting (this also helps the transcription tell speakers apart).
LINES: list[tuple[str, str, str]] = [
    ("Siva (YuviPep)", "David",
     "Good morning everyone. Thank you for meeting me today at Orchid "
     "International School. I am Siva from YuviPep."),
    ("Principal Nair", "Zira",
     "Welcome Siva. I am Mrs. Nair, the Principal. I will be taking the "
     "final decision on this program."),
    ("Coordinator Arjun", "Hazel",
     "And I am Arjun, the Science Coordinator. I will be your main point of "
     "contact for the day to day work."),
    ("Admin Divya", "Zira",
     "I am Divya from the admin office. I will help you with scheduling and "
     "access to the campus."),
    ("Siva (YuviPep)", "David",
     "Wonderful. As discussed, we would like to bring our I B C STEM program "
     "to your school. It is a hands on program that turns students into young "
     "inventors."),
    ("Principal Nair", "Zira",
     "Yes, we want this for our grades six, seven and eight. We have about "
     "forty students who will take part."),
    ("Siva (YuviPep)", "David",
     "Perfect. For that group I recommend twelve workshops over the term, "
     "forty student maker kits, one kit per student, and one annual "
     "innovation showcase at the end."),
    ("Coordinator Arjun", "Hazel",
     "Twelve workshops sounds good. Can we start the program on the "
     "fifteenth of August?"),
    ("Siva (YuviPep)", "David",
     "The fifteenth of August works. The showcase can be in the second week "
     "of December."),
    ("Principal Nair", "Zira",
     "Good. What do you need from our side?"),
    ("Siva (YuviPep)", "David",
     "A few things. My team will design the workshop curriculum for grades "
     "six to eight, and develop all the hands on worksheets and materials."),
    ("Siva (YuviPep)", "David",
     "On our operations side we will coordinate the logistics, that is the "
     "lab space, and the procurement and delivery of the forty maker kits."),
    ("Siva (YuviPep)", "David",
     "We will also train and schedule our facilitators, and run one pilot "
     "workshop for your teachers before the program begins."),
    ("Coordinator Arjun", "Hazel",
     "A pilot workshop for the teachers is a great idea. I will share the "
     "full student list and the class timetable with you by Friday."),
    ("Admin Divya", "Zira",
     "I will book the science lab for the pilot. Please tell me two possible "
     "dates."),
    ("Siva (YuviPep)", "David",
     "I will send you two dates for the pilot demo this week. I will also "
     "prepare and send the full proposal to Mrs. Nair by Friday, with Arjun "
     "in copy."),
    ("Principal Nair", "Zira",
     "Please do. Once I review the proposal and the pricing, I will give you "
     "our decision."),
    ("Siva (YuviPep)", "David",
     "Thank you. To summarise, twelve workshops, forty kits, one showcase, "
     "starting the fifteenth of August, with a teacher pilot before that. We "
     "will send the proposal by Friday."),
    ("Principal Nair", "Zira",
     "That is correct. We look forward to it."),
    ("Siva (YuviPep)", "David",
     "Thank you Mrs. Nair, Arjun and Divya. Have a great day."),
]


def _ps_escape(text: str) -> str:
    """Escape a string for a single-quoted PowerShell literal."""
    return text.replace("'", "''")


def synth(lines: list[tuple[str, str, str]], out_wav: Path) -> None:
    """Speak every line into one WAV file using Windows System.Speech.
    Different voices are selected per speaker; all utterances append into the
    same file."""
    ps: list[str] = [
        "Add-Type -AssemblyName System.Speech",
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
        "$s.Rate = -1",       # a touch slower -> cleaner transcription
        "$s.Volume = 100",
        (
            "function Set-Voice($synth,$like){ "
            "$v=$synth.GetInstalledVoices()|"
            "Where-Object{$_.Enabled -and $_.VoiceInfo.Name -like ('*'+$like+'*')}|"
            "Select-Object -First 1; "
            "if($v){ $synth.SelectVoice($v.VoiceInfo.Name) } }"
        ),
        f"$s.SetOutputToWaveFile('{_ps_escape(str(out_wav))}')",
    ]
    for _label, voice, text in lines:
        ps.append(f"Set-Voice $s '{_ps_escape(voice)}'")
        ps.append(f"$s.Speak('{_ps_escape(text)}')")
    ps.append("$s.Dispose()")

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".ps1", delete=False, encoding="utf-8"
    )
    try:
        tmp.write("\r\n".join(ps))
        tmp.close()
        print(f"Building {out_wav.name} with the built-in Windows voices ...")
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", tmp.name],
            check=True,
        )
    finally:
        os.unlink(tmp.name)
    print(f"Saved: {out_wav}  ({out_wav.stat().st_size // 1024} KB)\n")


def play(out_wav: Path) -> None:
    try:
        import winsound
    except ImportError:  # pragma: no cover - non-Windows fallback
        print("winsound not available; open the WAV in any media player.")
        return
    print(">>> PLAYING the meeting now. Keep the phone near the speaker ...\n")
    winsound.PlaySound(str(out_wav), winsound.SND_FILENAME)
    print(">>> Done. Press STOP in the app.\n")


def print_script() -> None:
    print("=" * 70)
    print(TITLE)
    print("=" * 70)
    for label, _voice, text in LINES:
        print(f"  {label:20s}: {text}")
    print("=" * 70 + "\n")


def main() -> None:
    args = set(sys.argv[1:])
    print_script()

    if "--regen" in args or not OUT_WAV.exists():
        synth(LINES, OUT_WAV)
    else:
        print(f"Using existing {OUT_WAV.name} (pass --regen to rebuild).\n")

    if "--no-play" in args:
        print("Built only (--no-play). Play meeting1.wav whenever you are ready.")
        return

    if "--no-wait" not in args:
        print("Checklist before you play:")
        print("  [ ] Laptop volume is UP")
        print("  [ ] Phone is RECORDING the meeting (consent confirmed)")
        print("  [ ] Room is reasonably quiet")
        try:
            input("\nPress ENTER to start playback ...")
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return
    play(OUT_WAV)


if __name__ == "__main__":
    main()
