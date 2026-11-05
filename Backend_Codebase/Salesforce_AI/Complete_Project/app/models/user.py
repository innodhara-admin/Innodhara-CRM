"""Users (staff), their skills, and in-app notifications."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import OrgScopedMixin, PKMixin, TimestampMixin


class User(Base, PKMixin, TimestampMixin):
    """A staff member. Email = identity, tied to one organisation (doc §3).

    org_id is nullable only for the platform Super Admin, who sits above all
    organisations and cannot read any organisation's sales data.
    """

    __tablename__ = "users"
    __table_args__ = (Index("ix_users_org_role", "org_id", "role"),)

    org_id: Mapped[str | None] = mapped_column(String(32), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)

    # Per-user Gmail app password (encrypted) so proposals go out from the
    # salesperson's own address — "the school always sees a real person's email".
    smtp_app_password_enc: Mapped[str | None] = mapped_column(Text)

    # Per-user override of the org's "require review of action items" switch.
    # None = follow org setting.
    require_action_item_review: Mapped[bool | None] = mapped_column(Boolean)

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    # ── Workflow-design people model (Data Model §2.3 ✚ fields) ─────────────
    designation: Mapped[str | None] = mapped_column(String(100))   # human job title
    department: Mapped[str | None] = mapped_column(String(20))     # sales|operations|accounts|relationship
    whatsapp_number: Mapped[str | None] = mapped_column(String(30))
    # The size of this person's plate — the AI never loads beyond it except P1.
    max_open_tasks: Mapped[int] = mapped_column(Integer, default=8)
    # Personal working days if different from the org's. None = follow org.
    working_days: Mapped[list[str] | None] = mapped_column(JSON)
    on_leave_from: Mapped[date | None] = mapped_column(Date)
    on_leave_to: Mapped[date | None] = mapped_column(Date)


class UserSkill(Base, PKMixin, TimestampMixin, OrgScopedMixin):
    """One skill of one person, with a level — the heart of task assignment.

    action_items.required_skill is matched against these rows to build the
    Assignment Engine's candidate list (Data Model §2.4).
    """

    __tablename__ = "user_skills"
    __table_args__ = (
        Index("ix_user_skills_org_skill", "org_id", "skill"),
        Index("ix_user_skills_user_skill", "user_id", "skill", unique=True),
    )

    user_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    skill: Mapped[str] = mapped_column(String(100), nullable=False)
    level: Mapped[str] = mapped_column(String(10), default="good")  # basic|good|expert


class DeviceToken(Base, PKMixin, TimestampMixin):
    """One mobile device's push registration (FCM). A user may hold several
    (phone + tablet); tokens are upserted on app start and pruned when FCM
    reports them gone."""

    __tablename__ = "device_tokens"
    __table_args__ = (Index("ix_device_tokens_user", "user_id"),)

    org_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    fcm_token: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    platform: Mapped[str] = mapped_column(String(20), default="android")
    app_version: Mapped[str | None] = mapped_column(String(30))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)


class Notification(Base, PKMixin, TimestampMixin):
    """In-app notification (e.g. 'a task was assigned to you')."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_org_user_read", "org_id", "user_id", "is_read"),)

    org_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(50), default="general")
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(32))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
