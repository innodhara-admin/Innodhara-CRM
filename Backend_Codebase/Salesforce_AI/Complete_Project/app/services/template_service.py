"""Template variable rendering for proposals and messages.

Variables use {curly_braces}. Unknown variables are left visible as
[missing:name] so a human notices instead of silently sending blanks.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.program import MessageTemplate

_VAR = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def render(template: str, variables: dict[str, Any]) -> str:
    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        value = variables.get(key)
        if value is None or value == "":
            return f"[missing:{key}]"
        return str(value)

    return _VAR.sub(_sub, template)


def missing_variables(rendered: str) -> list[str]:
    return re.findall(r"\[missing:([a-zA-Z0-9_]+)\]", rendered)


async def get_current_message_template(
    db: AsyncSession, org_id: str, kind: str, channel: str
) -> MessageTemplate:
    tmpl = (
        await db.execute(
            select(MessageTemplate)
            .where(
                MessageTemplate.org_id == org_id,
                MessageTemplate.kind == kind,
                MessageTemplate.channel == channel,
                MessageTemplate.is_current.is_(True),
            )
            .order_by(MessageTemplate.version.desc())
        )
    ).scalars().first()
    if tmpl is None:
        raise NotFoundError(
            f"No current '{kind}' message template for channel '{channel}'. "
            "Ask your Org Admin to add one."
        )
    return tmpl
