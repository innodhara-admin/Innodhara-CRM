"""The 11 tagged email templates built from the developer's document (28 Oct 2026).

These files are what Task 10's loader publishes to YuviPep, so they are pinned
here: every one scans, carries a subject line, has no `[Square bracket]` blank
left in it, and every always-asked tag sits after words that say what it is.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from app.services import draft_check
from app.services.docx import tags
from app.services.docx import text as dt

FIXTURES = Path(__file__).parent / "fixtures"

#: Where each file goes. Copied into scripts/load_email_templates.py, and
#: test_loader.py asserts the two stay equal.
MANIFEST: dict[str, dict] = {
    "Intro and appointment seeking.docx": {
        "type": "common", "category": "intro", "program_code": None,
        "name": "Intro and appointment seeking", "built_document": "none",
        "when_to_use": "First email to a new client contact: introduces the "
                       "organisation and asks for a 20-minute meeting with two "
                       "time options."},
    "Meeting confirmation.docx": {
        "type": "common", "category": "meeting_confirmation", "program_code": None,
        "name": "Meeting confirmation", "built_document": "none",
        "when_to_use": "After the client agrees to meet: confirms the date, "
                       "time and venue or video link."},
    "After the meeting.docx": {
        "type": "common", "category": "after_meeting", "program_code": None,
        "name": "After the meeting", "built_document": "none",
        "when_to_use": "Right after a meeting: thanks them and sums up what was "
                       "discussed and the agreed action plan."},
    "No reply follow-up.docx": {
        "type": "common", "category": "follow_up", "program_code": None,
        "name": "No reply follow-up", "built_document": "none",
        "when_to_use": "The client has not replied: a follow-up with two impact "
                       "video links, asking again for a 20-minute meeting."},
    "Final follow-up.docx": {
        "type": "common", "category": "final_follow_up", "program_code": None,
        "name": "Final follow-up", "built_document": "none",
        "when_to_use": "No response after several follow-ups: a polite last "
                       "note that leaves the next move to the client."},
    "Onboarding.docx": {
        "type": "common", "category": "onboarding", "program_code": None,
        "name": "Onboarding", "built_document": "none",
        "when_to_use": "After the client signs up: contacts, the onboarding "
                       "roadmap and what is needed from them."},
    "IBC proposal email.docx": {
        "type": "product", "category": None, "program_code": "IBC",
        "name": "IBC proposal email", "built_document": "proposal",
        "when_to_use": "Sends the client's IBC proposal."},
    "Kaushal Bodh and Kaushal Vikaas proposal email.docx": {
        "type": "product", "category": None, "program_code": "KBKV",
        "name": "Kaushal Bodh and Kaushal Vikaas proposal email",
        "built_document": "proposal",
        "when_to_use": "Sends the client's Kaushal Bodh and Kaushal Vikaas "
                       "proposal."},
    "Innovation Lab proposal email.docx": {
        "type": "product", "category": None, "program_code": "YFIL",
        "name": "Innovation Lab proposal email", "built_document": "proposal",
        "when_to_use": "Sends the client's Innovation Lab proposal."},
    "Innovation Fest proposal email.docx": {
        "type": "product", "category": None, "program_code": "IFEST",
        "name": "Innovation Fest proposal email", "built_document": "proposal",
        "when_to_use": "Sends the client's Innovation Fest proposal."},
    "IBC MoU cover letter.docx": {
        "type": "product", "category": None, "program_code": "IBC",
        "name": "IBC MoU cover letter", "built_document": "mou",
        "when_to_use": "Sends the client's IBC MoU with a cover letter."},
}


def _paragraph_texts(data: bytes) -> list[str]:
    import io
    return [dt.node_text(p) for p in dt.walk_paragraphs(Document(io.BytesIO(data)))]


def test_manifest_is_eleven_six_common_five_product():
    assert len(MANIFEST) == 11
    kinds = [m["type"] for m in MANIFEST.values()]
    assert kinds.count("common") == 6 and kinds.count("product") == 5
    assert sorted(p.name for p in FIXTURES.glob("*.docx")) == sorted(MANIFEST)


@pytest.mark.parametrize("filename", sorted(MANIFEST))
def test_every_file_scans_cleanly(filename):
    data = (FIXTURES / filename).read_bytes()
    found = tags.scan(data)
    assert found, "no tags"
    texts = [t for t in _paragraph_texts(data) if t.strip()]
    assert texts[0].startswith("Subject: ")
    assert draft_check.find_blanks("\n".join(texts)) == []
    for occurrence in found:
        if occurrence.kind == "ask":
            assert occurrence.context.strip(), occurrence.raw
    salutations = [o for o in found if o.raw == "<ask:Mr.|Ms.|Mrs.>"]
    assert len(salutations) == 1
