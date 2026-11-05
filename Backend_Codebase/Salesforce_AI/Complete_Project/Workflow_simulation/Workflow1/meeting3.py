#!/usr/bin/env python3
r"""
meeting3.py  --  THIRD meeting recording: two people contradict each other.

Run this AFTER meeting1.py and meeting2.py. Where meeting 2 changed decisions
cleanly, this one is deliberately *incoherent*: the newly-introduced Trustee and
the day-to-day Coordinator state flatly contradictory things, in the same room,
about scope, dates and money.

WHAT IT IS TESTING (30-Workflows W7 — "Two people said different things")
  The Planner must NOT silently pick a side and must NOT average them. The
  correct behaviour is to raise a CONFLICT and hold the re-plan for a human,
  showing both positions with who said what. If the app quietly re-plans to one
  version, that is a finding.

THE CONTRADICTIONS PLANTED HERE
  1. SCOPE   Trustee Rao says cut back to eight workshops.
             Coordinator Arjun says the sixteen are already timetabled.
  2. DATE    Rao wants it pushed to October.
             Arjun says the first session runs next week and cannot move.
  3. AUDIENCE Rao says grades six and seven only.
             Arjun says grade eight is already enrolled.
  4. MONEY   Rao asks for a twenty percent discount.
             (Money must take the approval chain, never the casual path.)
  5. A commitment OUR side makes: revised plan by Tuesday.

HOW TO USE IT
  1. On the phone open the Orchid International School project/lead and start a
     recording (Record meeting -> confirm consent -> the app is listening).
  2. Turn the laptop volume UP, hold the phone near the speaker.
  3. Run:  python meeting3.py
  4. Press ENTER when prompted, let it finish, then press STOP in the app.

Flags:
  --regen    rebuild meeting3.wav even if it already exists
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
OUT_WAV = HERE / "meeting3.wav"
TITLE = "MEETING 3  --  Conflicting instructions: Trustee vs Coordinator"

# Each line = (speaker label, Windows-voice hint, spoken text).
# Trustee Rao is a NEW senior voice; Arjun is the established coordinator.
LINES: list[tuple[str, str, str]] = [
    ("Siva (YuviPep)", "David",
     "Good morning. Thank you for making time. I have Mister Rao the Trustee, "
     "and Arjun our Science Coordinator, on this call about the Orchid "
     "programme."),
    ("Trustee Rao", "David",
     "Good morning Siva. I have reviewed the plan and I have concerns. I want "
     "the programme cut back to eight workshops, not sixteen."),
    ("Coordinator Arjun", "Hazel",
     "That is not possible mister Rao. All sixteen workshops are already on the "
     "school timetable and the teachers have been informed."),
    ("Trustee Rao", "David",
     "The timetable can be redone. Eight workshops is what the budget allows "
     "this year."),
    ("Siva (YuviPep)", "David",
     "I want to make sure I have this right. Am I hearing eight workshops, or "
     "sixteen?"),
    ("Trustee Rao", "David",
     "Eight. And I want the whole programme pushed to October. We are not ready "
     "before then."),
    ("Coordinator Arjun", "Hazel",
     "Siva, the first session is next week. The students are expecting it. We "
     "cannot move it to October."),
    ("Trustee Rao", "David",
     "Also, restrict it to grades six and seven only. Grade eight has board "
     "preparation."),
    ("Coordinator Arjun", "Hazel",
     "Grade eight is already enrolled. Thirty of those students have signed up "
     "and paid their activity fee."),
    ("Siva (YuviPep)", "David",
     "I understand. These are two quite different pictures, so I will not "
     "change anything today."),
    ("Trustee Rao", "David",
     "One more thing. Given the reduced scope I expect a twenty percent "
     "discount on the total."),
    ("Siva (YuviPep)", "David",
     "Any change to price has to go through our approval process, so I cannot "
     "confirm a discount on this call."),
    ("Coordinator Arjun", "Hazel",
     "I would ask that we keep the programme as agreed. The parents have "
     "already been told."),
    ("Siva (YuviPep)", "David",
     "Here is what I will do. I will take both positions back to my team, and "
     "send you one revised plan by Tuesday for you to agree between "
     "yourselves."),
    ("Trustee Rao", "David",
     "That is acceptable. But my view carries the final say on budget."),
    ("Coordinator Arjun", "Hazel",
     "And mine on what is deliverable in the school day."),
    ("Siva (YuviPep)", "David",
     "Understood. Revised plan by Tuesday. Thank you both."),
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
    print("EXPECTED: a CONFLICT raised and the re-plan HELD for a human.")
    print("          Not a silent re-plan to either version, not an average.")
    print("          The discount must enter the approval chain, not be agreed.")
    print("=" * 70 + "\n")


def main() -> None:
    args = set(sys.argv[1:])
    print_script()

    if "--regen" in args or not OUT_WAV.exists():
        synth(LINES, OUT_WAV)
    else:
        print(f"Using existing {OUT_WAV.name} (pass --regen to rebuild).\n")

    if "--no-play" in args:
        print("Built only (--no-play). Play meeting3.wav whenever you are ready.")
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
