"""Every held conversation is known from the first command after a restart
(2 Oct 2026).

A held conversation is answered by the flow registered for its kind. The
meeting flow registered itself only when `meeting_draft` was first imported,
which happened inside the scheduling agent's tool, so after a restart a
person answering "what time?" before anyone had scheduled a meeting reached
an unknown kind: `orchestrator._held_conversation` dropped the row and routed
the answer as a new message. Checked in a fresh interpreter, because inside
this test run other tests have long since imported the modules.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHECK = """
import app.ai.orchestrator  # what the app imports at startup
from app.ai import confirmations
for kind in ("create_client", "meeting_draft", "proposal_recipient"):
    print(kind, confirmations.flow_for(kind) is not None)
"""


def test_every_held_flow_is_registered_at_startup():
    out = subprocess.run([sys.executable, "-c", CHECK], cwd=ROOT,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    found = dict(line.split() for line in out.stdout.strip().splitlines())
    assert found == {"create_client": "True", "meeting_draft": "True",
                     "proposal_recipient": "True"}, out.stdout
