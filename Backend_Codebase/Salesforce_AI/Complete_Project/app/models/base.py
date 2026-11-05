"""Shared model mixins.

Every business record inherits OrgScopedMixin so an org_id is stamped on the
row itself (design rule §2.3: "Every row also stores the org_id directly, so
the database can fence rows off even without following the links").
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


def new_id() -> str:
    return uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PKMixin:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class OrgScopedMixin:
    @declared_attr
    def org_id(cls) -> Mapped[str]:  # noqa: N805
        return mapped_column(
            String(32), ForeignKey("organisations.id"), nullable=False, index=True
        )
