# tests/docx/test_models.py
import pytest
from sqlalchemy import inspect

from app.database import Base
from app.models.program import ProposalTemplate, ProposalTemplateDoc
from app.models.proposal import Proposal


def test_templates_default_to_the_markdown_kind():
    assert ProposalTemplate.__table__.c.kind.default.arg == "markdown"
    assert ProposalTemplate.__table__.c.kind.nullable is False


def test_the_template_doc_table_exists_with_its_columns():
    cols = set(ProposalTemplateDoc.__table__.c.keys())
    assert {"template_id", "source_path", "filename", "sha256", "size_bytes",
            "outline_json", "ocr_json", "plan_json", "index_kind",
            "analysis_status", "analysis_error"} <= cols


def test_one_doc_row_per_template_version():
    assert ProposalTemplateDoc.__table__.c.template_id.unique is True


def test_proposals_record_what_was_filled():
    assert "filled_json" in Proposal.__table__.c.keys()


def test_proposals_remember_which_kind_of_template_built_them():
    """Rendering must not have to load the template row to know how to make the
    PDF, and an old proposal keeps rendering the way it was built even if its
    template family later changes kind."""
    column = Proposal.__table__.c.template_kind
    assert column.default.arg == "markdown"
    assert column.nullable is False


def test_the_template_doc_table_shares_its_templates_reset_bucket():
    """A template's document is part of the template: if a reset replaces one it
    must replace the other, or a surviving template row points at a file that is
    gone and `_current_template` finds a template that cannot build anything."""
    from app.core.reset_taxonomy import CONFIG, KEEP, REPLACE, WIPE

    assert "proposal_templates" in REPLACE
    assert "proposal_template_docs" in REPLACE
    for other in (KEEP, CONFIG, WIPE):
        assert "proposal_template_docs" not in other


# --- the simple-flow fill session (Task A4) ---------------------------------


def test_the_fill_session_table_exists_with_exactly_its_columns():
    from app.models.proposal_fill import ProposalFillSession

    assert set(ProposalFillSession.__table__.c.keys()) == {
        "id", "org_id", "created_at", "updated_at",
        "lead_id", "program_id", "template_id", "template_doc_id",
        # D-C: mou_id records a built MOU beside proposal_id, and
        # document_type says which of the two this fill will ever set. The
        # status machine is shared; only the build half differs.
        "proposal_id", "mou_id", "document_type",
        "user_id", "chat_session_id",
        "status", "dossier_json", "tags_json", "asked_json",
    }


def test_a_fill_session_starts_by_gathering():
    from app.models.proposal_fill import FillStatus, ProposalFillSession

    column = ProposalFillSession.__table__.c.status
    assert column.default.arg == FillStatus.GATHERING
    assert column.nullable is False


def test_the_working_memory_defaults_to_empty_containers():
    """The row IS the working memory, so it must be readable before it is filled.

    conversation.py replays 12 turns inside a 6,000-character budget and prunes
    at 60 rows, so a 25-tag fill with a dozen clarifications would lose its own
    state if the transcript were carrying it (plan section 2.7, D6).
    """
    from app.models.proposal_fill import ProposalFillSession

    columns = ProposalFillSession.__table__.c
    # SQLAlchemy wraps a zero-argument callable default in one taking a
    # context, so the default is exercised rather than compared by identity.
    assert columns.dossier_json.default.arg(None) == {}
    assert columns.tags_json.default.arg(None) == []
    assert columns.asked_json.default.arg(None) == []


def test_only_the_written_document_and_the_chat_session_may_be_absent():
    """Everything else is known the moment a fill opens.

    proposal_id and mou_id are set once the document is produced, and EXACTLY
    ONE of them ever is -- which one is decided by document_type (D-C).
    chat_session_id is null for a fill that did not come from a conversation.

    document_type is deliberately NOT in this set: it is known at open time
    and defaults to "proposal", so every fill that existed before the MOU
    pipeline reads as what it always was.
    """
    from app.models.proposal_fill import ProposalFillSession

    nullable = {c.name for c in ProposalFillSession.__table__.c if c.nullable}
    assert nullable == {"proposal_id", "mou_id", "chat_session_id"}


def test_a_fill_session_is_transactional_work_not_catalogue():
    """A half-answered fill is a client's work in progress, not a catalogue
    entry: a reset that keeps it would resume week-old answers about a client
    whose records have just been wiped."""
    from app.core.reset_taxonomy import CONFIG, KEEP, REPLACE, WIPE

    assert "proposal_fill_sessions" in WIPE
    for other in (KEEP, CONFIG, REPLACE):
        assert "proposal_fill_sessions" not in other


def test_a_fill_session_is_wiped_before_the_proposal_it_produced():
    """It carries a foreign key to proposals, and nothing here declares
    `ondelete=`, so child-before-parent is the only thing keeping a reset from
    failing on a constraint."""
    from app.core.reset_taxonomy import WIPE

    assert WIPE.index("proposal_fill_sessions") < WIPE.index("proposals")
    assert WIPE.index("proposal_fill_sessions") < WIPE.index("leads")


def test_create_all_makes_the_fill_session_table_on_a_fresh_database():
    """The reason the simple flow adds one table and no columns.

    This project has no Alembic: `create_all` creates a missing TABLE at
    startup but never adds a COLUMN, so a new column is a manual migration on
    every environment and a new table is free (plan section 2.7).
    """
    from sqlalchemy import create_engine

    import app.models  # noqa: F401  (registers every mapper)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    assert "proposal_fill_sessions" in inspect(engine).get_table_names()


def test_the_fill_session_is_exported_from_the_models_package():
    """`app.models` is what registers every mapper; a model it does not import
    is invisible to create_all and to the partition test."""
    import app.models as models

    from app.models.proposal_fill import ProposalFillSession

    assert models.ProposalFillSession is ProposalFillSession
    assert "ProposalFillSession" in models.__all__
