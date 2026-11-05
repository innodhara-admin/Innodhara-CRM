"""Typed application errors mapped to HTTP responses in main.py."""
from __future__ import annotations


class AppError(Exception):
    status_code = 400

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class NotFoundError(AppError):
    status_code = 404


class PermissionDeniedError(AppError):
    status_code = 403


class ConflictError(AppError):
    status_code = 409


class ValidationFailedError(AppError):
    status_code = 422


class NeedsConfirmationError(ValidationFailedError):
    """The tool is not confused, it is *unsure* — and unsure is a question,
    not a failure (finding F28).

    Raised by a resolver that found several plausible people (or none) instead
    of guessing one. The agent loop turns it into a question the model asks the
    user, carrying `candidates` so the app can offer them as one-tap answers.
    Subclasses ValidationFailedError deliberately: it stays a 422 and every
    existing `except ValidationFailedError` keeps catching it, so nothing that
    handles today's ambiguity error changes behaviour.
    """

    def __init__(self, message: str, *, candidates: list[str] | None = None,
                 details: dict | None = None):
        super().__init__(message)
        self.candidates = candidates or []
        self.details = details


class LeadNotOpenError(ValidationFailedError):
    """Jarvis was asked to create sales work (a meeting, a demo, a proposal,
    an MOU) for a lead still in cold calling.

    Not a failure to explain but a rule to state: the agent loop records it as
    `outcome: "not_allowed"` and the message becomes the reply as written, so
    the model cannot soften it into "I'll try again" or claim it did the work.
    A ValidationFailedError, so anything already catching those still does.
    """


class BudgetExceededError(AppError):
    status_code = 429


class ExternalServiceError(AppError):
    status_code = 502
