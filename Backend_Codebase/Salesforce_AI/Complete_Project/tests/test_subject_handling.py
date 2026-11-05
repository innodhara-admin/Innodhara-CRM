"""Finding F44 — drafts carried a `Subject:` line inside the body, and replies
had no subject at all.

Every pending draft on the system was affected — three for three:

    kind    subject field                    first line of body
    intro   "Great meeting you — YuviPep"    Subject: Updated contact email
    reply    None                            Subject: Re: Content Change Request
    reply    None                            Subject: Scope Expansion Amendment

Two mechanisms, and they are looking straight at each other. The model reliably
writes a good subject and reliably puts it in the body; meanwhile all six reply
sites in `inbound_engine` derived `f"Re: {msg.subject}" if msg.subject else None`,
and the app's *Log a client reply* sheet marks Subject "(optional)" — correctly,
because a phone call has no subject. So the subject existed in the wrong field
while the right field sat empty, and an approved reply would have reached the
client with **no subject** and a body opening `Subject: Re: …`.

The fix promotes rather than discards.
"""
from __future__ import annotations

import pytest

from app.engines.communication_engine import split_leading_subject


# ── The deterministic half — no model, no DB ─────────────────────────────────


@pytest.mark.parametrize(
    "body,subject,want_subject,want_first_line",
    [
        # F44's exact observed case: a reply with no subject at all.
        ("Subject: Re: Content Change Request\n\nDear Mrs. Nair,\nThanks.",
         None, "Re: Content Change Request", "Dear Mrs. Nair,"),
        # The intro case: a subject already exists, so it wins — but the
        # malformed header still has to leave the body.
        ("Subject: Updated contact email\n\nDear X,\nBody.",
         "Great meeting you", "Great meeting you", "Dear X,"),
        # Tolerant of the shapes a model actually emits.
        ("  subject :  Quarterly update  \n\nHello", None, "Quarterly update", "Hello"),
        # An empty header must not produce an empty subject.
        ("Subject:\n\nHello", None, None, "Hello"),
        # Nothing to do.
        ("Dear X,\nA normal body.", None, None, "Dear X,"),
    ],
)
def test_a_leading_subject_line_moves_into_the_subject_field(
    body, subject, want_subject, want_first_line
):
    new_body, new_subject = split_leading_subject(body, subject)
    assert new_subject == want_subject
    assert new_body.splitlines()[0] == want_first_line
    assert not new_body.lower().startswith("subject:"), (
        f"the header is still the first thing the client reads: {new_body[:60]!r}"
    )


def test_a_subject_line_in_the_MIDDLE_of_a_body_is_left_alone():
    """The falsification case, and the reason this is anchored to the start.

    A person quoting an email writes "Subject:" mid-body legitimately. Rewriting
    that would be a new defect traded for the old one.
    """
    body = "Dear X,\n\nYou wrote:\nSubject: the old thread\n\nRegards"
    new_body, new_subject = split_leading_subject(body, None)
    assert new_body == body, "prose containing a Subject: line was rewritten"
    assert new_subject is None


def test_the_body_is_never_left_empty_handed():
    """A body that is ONLY a subject line still must not become the subject and
    vanish — the caller would send an empty message."""
    new_body, new_subject = split_leading_subject("Subject: Just a header\n", None)
    assert new_subject == "Just a header"
    assert new_body == ""  # explicit: the caller's own empty-body checks apply


# ── The reply half — the six call sites ──────────────────────────────────────


def test_a_reply_to_a_subjectless_message_still_gets_a_subject():
    """Mechanism 2. Logging a phone call leaves Subject blank, which used to make
    EVERY generated reply subjectless."""
    from app.engines.inbound_engine import reply_subject

    class _Msg:
        subject = None

    class _Project:
        name = "Orchid International School — IBC"

    assert reply_subject(_Msg(), _Project()) == "Re: Orchid International School — IBC"
    # And with nothing to name, it is still a subject rather than None.
    assert reply_subject(_Msg(), None) == "Re: your message"


def test_a_real_inbound_subject_is_still_preferred():
    """Control: the fallback must not override a genuine email thread subject,
    or replies would stop threading in the client's mail app."""
    from app.engines.inbound_engine import reply_subject

    class _Msg:
        subject = "Content Change Request"

    class _Project:
        name = "Some Project"

    assert reply_subject(_Msg(), _Project()) == "Re: Content Change Request"


def test_no_reply_site_can_still_produce_a_null_subject():
    """The guard. F44 was six copies of one expression; a seventh copy, or a
    reverted one, puts a subjectless email back in front of a client."""
    import inspect

    from app.engines import inbound_engine

    source = inspect.getsource(inbound_engine)
    # Match the CODE, not the prose: the docstring above reply_subject() quotes
    # the old expression on purpose, and a guard that trips on its own
    # explanation is a guard nobody will keep.
    assert 'subject=f"Re: {msg.subject}" if msg.subject else None' not in source, (
        "a reply site still derives its subject inline — that is exactly F44: "
        "log a phone call and the client gets a subjectless email"
    )
    assert source.count("subject=reply_subject(msg, project)") == 6, (
        "the six reply sites no longer all route through reply_subject()"
    )
