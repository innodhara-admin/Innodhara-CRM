"""Print the WhatsApp template sheet for the developer (4 Nov 2026).

    .venv/bin/python scripts/whatsapp_templates_doc.py > templates.md

Generated from app/services/whatsapp_templates.py, so the texts submitted in
Wati are exactly the texts the code fills in.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.whatsapp_templates import DOCUMENT_VALUE, TEMPLATES  # noqa: E402

SAMPLES = {
    "name": "Asha", "title": "Task assigned: Send the IBC proposal",
    "detail": "Due on Friday.", "client": "Abc School",
    "summary": "They want the lab for classes 8 to 10.",
    "action_items": "Send the proposal (due 7 Nov); Book a demo (due 12 Nov)",
    "date": "Wed 4 Nov", "day": "Due today: Call Abc School. Coming up: Demo on Friday",
    "contact_name": "Ravi Kumar", "programme": "IBC Proposal", "sender_name": "Ekaghni",
    "message": "Thank you for your time today. We will share the plan by Friday.",
}

WHY = {
    "staff_update": "every in-app update to a member of staff (tasks, reminders, approvals, plans)",
    "staff_meeting_summary": "after a recorded meeting is processed: summary, action items, transcript PDF",
    "staff_daily_brief": "each morning at the start of the working day",
    "client_proposal": "Jarvis sends a proposal PDF to a client, after approval",
    "client_message": "any other approved WhatsApp to a client (follow-ups, intros)",
    "test_message": "the dashboard's 'Send a test message' button",
}


def numbered(body: str, values: tuple[str, ...]) -> str:
    for i, v in enumerate(values, 1):
        body = body.replace("{{%s}}" % v, "{{%d}}" % i, 1)
    return body


def main() -> None:
    out = [
        "# WhatsApp templates to submit (Wati)",
        "",
        "Generated from `app/services/whatsapp_templates.py`. Submit each one in Wati",
        "(Broadcast > Your Templates > New Template) with the name, category, language",
        "and text EXACTLY as below. The values in `{{double braces}}` are typed as",
        "variables. Approval by WhatsApp takes from minutes to a day. Until a",
        "template is approved, its messages fail and are logged; nothing else breaks.",
        "",
        "After approval, open the dashboard (item 11, WhatsApp) and press",
        "**Check templates**: it reads the templates back from Wati and shows any",
        "that are missing or whose values differ.",
        "",
    ]
    for t in TEMPLATES.values():
        out += [f"## `{t.name}`", "", f"Used for: {WHY.get(t.name, '')}.", "",
                f"- Category: **{t.category.title()}**",
                "- Language: **English**",
                (f"- Header: **Document**, with a dynamic link: `{{{{{DOCUMENT_VALUE}}}}}`"
                 if t.document else "- Header: none"),
                "- Footer and buttons: none", "", "Body:", "", "```", t.body, "```", "",
                "Sample values (Wati asks for one per variable):", ""]
        out += [f"- `{v}`: {SAMPLES.get(v, 'example')}" for v in t.values]
        if t.document:
            out.append(f"- `{DOCUMENT_VALUE}`: any PDF link, for the sample only")
        out += ["", "For Meta (Business Manager) instead of Wati, the same body numbered:", "",
                "```", numbered(t.body, t.values), "```", ""]
    print("\n".join(out))


if __name__ == "__main__":
    main()
