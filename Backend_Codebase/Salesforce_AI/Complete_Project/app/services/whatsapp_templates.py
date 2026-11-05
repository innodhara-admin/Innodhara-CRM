"""The WhatsApp templates this platform sends (4 Nov 2026).

WhatsApp lets a business start a conversation only with a template approved in
advance. The developer submits these in Wati (or Meta) exactly as written here:
docs/superpowers/specs/2026-11-04-whatsapp-templates.md is generated from this
file's texts. Each `{{name}}` is a value filled in at send time; Wati takes
them by name, Meta by position, in the order they appear.

A document template's header is a PDF fetched from `{{document_url}}`, which
is not part of the body. WhatsApp refuses a body that starts or ends with a
value, so every body here starts and ends with fixed words.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_VALUE = re.compile(r"\{\{(\w+)\}\}")


@dataclass(frozen=True)
class Template:
    name: str
    category: str               # UTILITY | MARKETING, as submitted
    body: str
    document: bool = False
    values: tuple[str, ...] = field(init=False)
    fixed_len: int = field(init=False)

    def __post_init__(self) -> None:
        values = tuple(_VALUE.findall(self.body))
        object.__setattr__(self, "values", values)
        object.__setattr__(
            self, "fixed_len", len(self.body) - sum(len("{{%s}}" % v) for v in values))


_ALL = (
    Template(
        "staff_update", "UTILITY",
        "Hi {{name}}, an update from the CRM: {{title}}. {{detail}} "
        "Please open the app for details."),
    Template(
        "staff_meeting_summary", "UTILITY",
        "Hi {{name}}, your meeting with {{client}} has been processed. "
        "Summary: {{summary}} Action items: {{action_items}} "
        "The transcript is attached. Please review the items in the app.",
        document=True),
    Template(
        "staff_daily_brief", "UTILITY",
        "Good morning {{name}}, here is your plan for {{date}}: {{day}} Have a good day."),
    Template(
        "client_proposal", "UTILITY",
        "Dear {{contact_name}}, please find attached our proposal for {{programme}}. "
        "We look forward to hearing from you. Regards, {{sender_name}}. "
        "You can reply here with any questions.",
        document=True),
    Template(
        "client_message", "MARKETING",
        "Dear {{contact_name}}, here is a message from your account team. {{message}} "
        "Regards, {{sender_name}}. You can reply here with any questions."),
    Template(
        "test_message", "UTILITY",
        "Hi {{name}}, this is a test message from the CRM. WhatsApp updates are working."),
)

TEMPLATES: dict[str, Template] = {t.name: t for t in _ALL}


def render(name: str, values: dict[str, str]) -> str:
    """The body as the recipient will read it (values already cleaned)."""
    body = TEMPLATES[name].body
    for key, value in values.items():
        body = body.replace("{{%s}}" % key, value)
    return body
DOCUMENT_VALUE = "document_url"
