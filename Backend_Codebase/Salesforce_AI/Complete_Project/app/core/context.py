"""The organisation context that travels with every request and tool call.

The Backend API resolves it at login/auth time and it is injected — never
supplied by the client body and never by the AI model (doc §5, §6).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrgContext:
    org_id: str
    user_id: str
    role: str
    email: str
    name: str = ""

    @property
    def is_org_admin(self) -> bool:
        return self.role == "org_admin"
