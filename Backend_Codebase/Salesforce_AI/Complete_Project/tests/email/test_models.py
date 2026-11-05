"""The three email template tables, and the constants they rest on."""
from __future__ import annotations

import app.models  # noqa: F401  (registers every mapper)
from app.core.constants import (
    EMAIL_CATEGORY_PRESETS,
    BuiltDocument,
    EmailTemplateType,
    MessageKind,
    TemplateKind,
)
from app.database import Base


def test_tables_exist_after_init():
    for name in ("email_templates", "email_template_attachments",
                 "email_fill_sessions"):
        assert name in Base.metadata.tables, name


def test_template_kind_is_unchanged():
    # The card scan and the go-live checklist are built on these two.
    assert [m.value for m in TemplateKind] == ["intro", "follow_up"]


def test_presets_are_the_spec_six():
    assert list(EMAIL_CATEGORY_PRESETS) == [
        "intro", "meeting_confirmation", "after_meeting", "follow_up",
        "final_follow_up", "onboarding",
    ]


def test_new_vocabulary():
    assert [m.value for m in EmailTemplateType] == ["common", "product"]
    assert [m.value for m in BuiltDocument] == ["none", "proposal", "mou"]
    assert MessageKind.TEMPLATE_EMAIL.value == "template_email"


def test_no_column_added_to_an_existing_table():
    # No Alembic: create_all never adds a column, so the feature may only
    # add tables. The columns of the tables it touches are pinned here.
    assert "html_body" not in Base.metadata.tables["outbound_messages"].columns
    assert "email_template_id" not in Base.metadata.tables["programs"].columns
