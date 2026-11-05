#!/usr/bin/env python3
r"""
meeting4.py  --  FOURTH meeting recording: delivery has started, and it is
                 going wrong before it goes right.

Run this AFTER meetings 1-3. The programme is now RUNNING, so this meeting is
not about selling — it is about delivery, a complaint, and closing well.

WHAT IT IS TESTING
  W22  A complaint ("your trainer arrived forty minutes late") must become a
       real incident with fix tasks and a resolution, at P1 — not a note.
  W14  A finished piece of work the client can see should reach the client.
  W24  A dependency outside the company (the kit vendor) is slipping.
  W25  Money: an invoice is due and the client raises a query about it. That
       query must pause the payment ladder, not be argued with.
  W26  Closing well: feedback, certificates, a closure report.
  W30  Relationship: they open the door to a second campus. That is a NEW
       opportunity, and it must not be silently merged into this project.

THE FACTS PLANTED HERE
  * Trainer was 40 minutes late to the session on the 3rd -> complaint.
  * Two sessions completed; students built line-following robots.
  * The maker-kit vendor has slipped by a week -> blocks session five.
  * Invoice: the school says the advance was paid on the 28th and asks why a
    reminder arrived -> payment query, ladder must pause.
  * Certificates wanted for 40 students before the showcase.
  * They want a proposal for their SECOND campus in Hinjewadi.
  * Commitment from us: incident write-up by Thursday.

HOW TO USE IT
  1. On the phone open the Orchid project and start a recording
     (Record meeting -> confirm consent -> the app is listening).
  2. Turn the laptop volume UP, hold the phone near the speaker.
  3. Run:  python meeting4.py
  4. Press ENTER when prompted, let it finish, then press STOP in the app.

Flags:
  --regen    rebuild meeting4.wav even if it already exists
  --no-play  build the audio only, do not play it
  --no-wait  play immediately, do not wait for you to press ENTER

No internet, no API key -- Windows' built-in System.Speech voices.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_WAV = HERE / "meeting4.wav"
TITLE = "MEETING 4  --  Delivery review: a complaint, a vendor slip, a closure"

LINES: list[tuple[str, str, str]] = [
    ("Siva (YuviPep)", "David",
     "Thank you for the review meeting. I know the first two sessions are done, "
     "so I would like to hear how it has actually gone."),
    ("Principal Nair", "Zira",
     "Siva, I have to raise something first. On the third, your trainer arrived "
     "forty minutes late. The children were waiting in the lab."),
    ("Siva (YuviPep)", "David",
     "I am sorry. That should not have happened and I am not going to explain "
     "it away. I will log it properly and come back to you with what went wrong "
     "and what we are changing."),
    ("Principal Nair", "Zira",
     "Please do. If it happens again I will have to answer to the parents."),
    ("Coordinator Arjun", "Hazel",
     "To be fair, the sessions themselves have been excellent. The students "
     "built line following robots last week and they were thrilled."),
    ("Siva (YuviPep)", "David",
     "Good. I will make sure that goes into your progress update, with photos "
     "if the admin office permits."),
    ("Coordinator Arjun", "Hazel",
     "There is a problem coming though. The maker kits have not arrived. Your "
     "supplier told us a week's delay. Session five needs those kits."),
    ("Siva (YuviPep)", "David",
     "Understood. That is our vendor, so it is our problem to solve. I will "
     "chase them and tell you before session five either way."),
    ("Admin Divya", "Zira",
     "I also want to ask about the invoice. We paid the advance on the twenty "
     "eighth by bank transfer, but we received a payment reminder yesterday."),
    ("Siva (YuviPep)", "David",
     "Thank you for telling me. I will stop the reminders and check it against "
     "our records rather than ask you to prove it."),
    ("Principal Nair", "Zira",
     "Thank you. On a happier note, we would like certificates for all forty "
     "students before the showcase in December."),
    ("Coordinator Arjun", "Hazel",
     "And could we get the feedback forms out to the parents after session "
     "eight, while it is still fresh?"),
    ("Siva (YuviPep)", "David",
     "Yes to both. Certificates for forty students before the showcase, and "
     "feedback collection after session eight."),
    ("Principal Nair", "Zira",
     "One last thing, and this is the good news. Our second campus in "
     "Hinjewadi wants the same programme next term. Can you send them a "
     "separate proposal?"),
    ("Siva (YuviPep)", "David",
     "Very happy to hear it. I will treat Hinjewadi as its own engagement with "
     "its own proposal, so nothing gets confused with this campus."),
    ("Principal Nair", "Zira",
     "Good. Their head is Mrs. Kulkarni and she will be the decision maker "
     "there."),
    ("Siva (YuviPep)", "David",
     "Noted. To summarise. I will send you the incident write up on the late "
     "trainer by Thursday, chase the kit vendor before session five, pause and "
     "verify the invoice, arrange forty certificates before the showcase, send "
     "feedback forms after session eight, and prepare a separate proposal for "
     "Hinjewadi."),
    ("Principal Nair", "Zira",
     "That is a fair summary. Thank you Siva."),
]


def _ps_escape(text: str) -> str:
    """Escape a string for a single-quoted PowerShell literal."""
    return text.replace("'", "''")


def synth(lines: list[tuple[str, str, str]], out_wav: Path) -> None:
    """Speak every line into one WAV file using Windows System.Speech."""
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
    print("=" * 70)
    print("EXPECTED: complaint -> a real incident at P1 with fix tasks;")
    print("          vendor slip -> a blocked/dependency task, not a to-do;")
    print("          payment query -> the reminder ladder PAUSES;")
    print("          certificates + feedback -> closure tasks with due dates;")
    print("          Hinjewadi -> a NEW opportunity, never merged into this one.")
    print("=" * 70 + "\n")


def main() -> None:
    args = set(sys.argv[1:])
    print_script()

    if "--regen" in args or not OUT_WAV.exists():
        synth(LINES, OUT_WAV)
    else:
        print(f"Using existing {OUT_WAV.name} (pass --regen to rebuild).\n")

    if "--no-play" in args:
        print("Built only (--no-play). Play meeting4.wav whenever you are ready.")
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
