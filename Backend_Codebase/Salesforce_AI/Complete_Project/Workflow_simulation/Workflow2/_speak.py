#!/usr/bin/env python3
r"""Shared text-to-speech for the Workflow2 datacentre meetings.

Same mechanism Workflow1 used: Windows' built-in System.Speech voices, no
internet, no API key, no install. Each speaker gets a different voice so the
recording sounds like a real room and the transcriber can tell people apart.

The meeting scripts import this; you never run this file directly.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

Line = tuple[str, str, str]  # (speaker label, voice hint, spoken text)


def _ps_escape(text: str) -> str:
    """Escape for a single-quoted PowerShell literal."""
    return text.replace("'", "''")


def synth(lines: list[Line], out_wav: Path) -> None:
    ps: list[str] = [
        "Add-Type -AssemblyName System.Speech",
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
        "$s.Rate = -1",  # slightly slow -> cleaner transcription
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
    except ImportError:  # pragma: no cover
        print("winsound not available; open the WAV in any media player.")
        return
    print(">>> PLAYING now. Hold the phone near the speaker ...\n")
    winsound.PlaySound(str(out_wav), winsound.SND_FILENAME)
    print(">>> Done. Press STOP in the app.\n")


def run(title: str, lines: list[Line], out_wav: Path) -> None:
    """Print the script, build the WAV if needed, wait, then play it."""
    args = set(sys.argv[1:])
    print("=" * 74)
    print(title)
    print("=" * 74)
    for label, _voice, text in lines:
        print(f"  {label:22s}: {text}")
    print("=" * 74 + "\n")

    if "--regen" in args or not out_wav.exists():
        synth(lines, out_wav)
    else:
        print(f"Using existing {out_wav.name} (--regen to rebuild).\n")

    if "--no-play" in args:
        return
    if "--no-wait" not in args:
        input("Start the recording in the app, then press ENTER to play ... ")
    play(out_wav)
