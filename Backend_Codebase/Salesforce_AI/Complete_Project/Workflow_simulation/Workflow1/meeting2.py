#!/usr/bin/env python3
r"""
meeting2.py  --  SECOND meeting recording for the YuviPep app demo.

This is the follow-up meeting, about a week after meeting1.py, on the SAME
client (ORCHID INTERNATIONAL SCHOOL). Its whole purpose is to CHANGE things
that were agreed in the first meeting, so you can show that the AI correctly
updates the live plan and proposal instead of starting from scratch.

Run it exactly like the first one:
  1. On the phone, open "Orchid International School" and start a NEW recording
     (Record meeting -> confirm consent).
  2. Laptop volume UP, phone near the speaker.
  3. Run:   python meeting2.py
  4. Press ENTER when the app is recording; it plays the meeting; press STOP.

What CHANGES from meeting 1 (this is what the AI must catch):
  1. Workshops go UP from 12 to 16            -> plan quantity + proposal price change
  2. The 40 printed maker kits are CANCELLED  -> materials go digital (task removed)
  3. A NEW two-day TEACHER TRAINING is added  -> extra tasks (a scope addition)
  4. Start date MOVES from 15 Aug to 1 Aug    -> a date change / conflict with meeting 1
  5. A NEW person appears: Trustee Mr. RAO    -> the AI adds him and CC's him on the proposal

Flags:  --regen  |  --no-play  |  --no-wait   (same meaning as meeting1.py)

No internet, no API key, no install -- Windows built-in voices only.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_WAV = HERE / "meeting2.wav"
TITLE = "MEETING 2  --  Review meeting: Orchid International School (the changes)"

# (speaker label, Windows-voice hint, spoken text). Our side = "David";
# the school's people alternate Zira / Hazel; the new trustee uses Zira so he
# is clearly a different voice from Siva.
LINES: list[tuple[str, str, str]] = [
    ("Siva (YuviPep)", "David",
     "Good morning Mrs. Nair. Thank you for the follow up meeting on the "
     "I B C program for Orchid International School."),
    ("Principal Nair", "Zira",
     "Good morning Siva. We reviewed your proposal and we have a few "
     "changes."),
    ("Principal Nair", "Zira",
     "First, we have decided to increase the workshops from twelve to "
     "sixteen. We want more sessions for the students."),
    ("Siva (YuviPep)", "David",
     "Understood. I will change it from twelve to sixteen workshops, and "
     "update the pricing in the proposal."),
    ("Coordinator Arjun", "Hazel",
     "Second, about the maker kits. We will not need the forty printed kits. "
     "Please make all the student materials digital instead. So you can "
     "cancel the kit procurement."),
    ("Siva (YuviPep)", "David",
     "Noted. I will cancel the procurement and delivery of the printed kits, "
     "and switch the materials to digital."),
    ("Principal Nair", "Zira",
     "Third, before the student workshops, we would like a two day teacher "
     "training program for our science teachers. Can you add that?"),
    ("Siva (YuviPep)", "David",
     "Yes. We will add a two day teacher training program before the "
     "workshops begin. My team will prepare the training plan and deliver "
     "it."),
    ("Coordinator Arjun", "Hazel",
     "Also, we need to start earlier. Instead of the fifteenth of August, "
     "please move the start date to the first of August."),
    ("Siva (YuviPep)", "David",
     "I will move the program start from the fifteenth of August to the "
     "first of August."),
    ("Principal Nair", "Zira",
     "One more thing. This is our trustee, Mr. Rao. He will approve the "
     "final budget."),
    ("Trustee Rao", "Zira",
     "Hello Siva. I am Rao, the trustee. Please add me to the proposal "
     "email. I will give the final financial approval."),
    ("Siva (YuviPep)", "David",
     "Welcome Mr. Rao. I will add you to the proposal, and send it to Mrs. "
     "Nair with Mr. Rao and Arjun in copy."),
    ("Trustee Rao", "Zira",
     "Good. Keep the budget clear, item by item."),
    ("Principal Nair", "Zira",
     "So to confirm, sixteen workshops, no printed kits, materials go "
     "digital, add a two day teacher training, start on the first of August, "
     "and copy Mr. Rao on everything."),
    ("Siva (YuviPep)", "David",
     "That is correct. I will update the plan and send the revised proposal "
     "today. To summarise the changes from last time, workshops go from "
     "twelve to sixteen, the forty kits are cancelled, we add a two day "
     "teacher training, and the start moves from the fifteenth to the first "
     "of August."),
    ("Principal Nair", "Zira",
     "Perfect. Thank you Siva."),
    ("Siva (YuviPep)", "David",
     "Thank you Mrs. Nair, Mr. Rao and Arjun."),
]


def _ps_escape(text: str) -> str:
    """Escape a string for a single-quoted PowerShell literal."""
    return text.replace("'", "''")


def synth(lines: list[tuple[str, str, str]], out_wav: Path) -> None:
    """Speak every line into one WAV file using Windows System.Speech."""
    ps: list[str] = [
        "Add-Type -AssemblyName System.Speech",
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
        "$s.Rate = -1",
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
        print("Built only (--no-play). Play meeting2.wav whenever you are ready.")
        return

    if "--no-wait" not in args:
        print("Checklist before you play:")
        print("  [ ] Laptop volume is UP")
        print("  [ ] Phone is RECORDING a NEW meeting (consent confirmed)")
        print("  [ ] Room is reasonably quiet")
        try:
            input("\nPress ENTER to start playback ...")
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return
    play(OUT_WAV)


if __name__ == "__main__":
    main()
