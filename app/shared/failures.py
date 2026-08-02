"""The one place a user-facing failure message is written.

Why the catalog is server-side and not in the UI: the browser is not the only
thing that shows these. A failed assistant turn is persisted as
`message.error_message` and re-rendered on reload, the SSE stream carries it
live, and the orchestrator logs it. Defining the copy once here means those
three never disagree, and changing the wording is one edit.

The UI still owns *behaviour* - whether to offer a sign-in link, whether to
show a retry button - which it decides from `code`, never from message text.
Matching on message text is what this module exists to replace: the frontend
used to `message.includes('401')` and `includes('inference')` against raw
Python exception strings, so any upstream rewording silently downgraded a
precise message to "Something went wrong."

Contract, everywhere a failure crosses a service boundary:

    {"code": "MODEL_UNAVAILABLE", "message": "<user-facing>", "retryable": true}
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Failure:
    code: str
    message: str
    # Whether trying the same request again could plausibly succeed. Drives the
    # retry affordance in the UI; it is not a promise that a retry will work.
    retryable: bool
    http_status: int

    def payload(self, detail: str | None = None) -> dict:
        """The wire shape. `detail` is for operators, never shown to users."""
        body = {"code": self.code, "message": self.message, "retryable": self.retryable}
        if detail:
            body["detail"] = detail[:300]
        return body


def _failure(code: str, message: str, retryable: bool, http_status: int) -> Failure:
    failure = Failure(code=code, message=message, retryable=retryable, http_status=http_status)
    CATALOG[code] = failure
    return failure


CATALOG: dict[str, Failure] = {}

# ── The caller ──────────────────────────────────────────────────────────────

AUTH_REQUIRED = _failure(
    "AUTH_REQUIRED",
    "Your session could not be verified. Please sign in again.",
    retryable=False,
    http_status=401,
)
REQUEST_INVALID = _failure(
    "REQUEST_INVALID",
    "That request could not be understood. Please rephrase and try again.",
    retryable=False,
    http_status=422,
)
CANCELLED = _failure(
    "CANCELLED",
    "The response was stopped.",
    retryable=True,
    http_status=499,
)

# ── Services in the chain ───────────────────────────────────────────────────

AGENT_UNAVAILABLE = _failure(
    "AGENT_UNAVAILABLE",
    "The assistant is not reachable right now. Please try again in a moment.",
    retryable=True,
    http_status=503,
)
DOMAIN_UNAVAILABLE = _failure(
    "DOMAIN_UNAVAILABLE",
    "The assistant could not load its configuration. Please try again shortly.",
    retryable=True,
    http_status=503,
)

# ── Models ──────────────────────────────────────────────────────────────────

MODEL_UNAVAILABLE = _failure(
    "MODEL_UNAVAILABLE",
    "The AI service is unavailable right now. Please try again in a moment.",
    retryable=True,
    http_status=503,
)
MODEL_TIMEOUT = _failure(
    "MODEL_TIMEOUT",
    "That took too long to answer. Please try again, or ask something narrower.",
    retryable=True,
    http_status=504,
)
RATE_LIMITED = _failure(
    "RATE_LIMITED",
    "Too many requests at once. Please wait a few seconds and try again.",
    retryable=True,
    http_status=429,
)

# ── Retrieval and tools ─────────────────────────────────────────────────────

RETRIEVAL_UNAVAILABLE = _failure(
    "RETRIEVAL_UNAVAILABLE",
    "Your notes could not be searched right now. Please try again shortly.",
    retryable=True,
    http_status=503,
)
NOTES_NOT_INDEXED = _failure(
    "NOTES_NOT_INDEXED",
    "Your notes are still being prepared for search. This usually takes a "
    "moment after you write or edit a note - please try again shortly.",
    retryable=True,
    http_status=200,
)
TOOL_UNAVAILABLE = _failure(
    "TOOL_UNAVAILABLE",
    "A tool the assistant needs is unavailable. Please try again in a moment.",
    retryable=True,
    http_status=503,
)
TOOL_FAILED = _failure(
    "TOOL_FAILED",
    "The assistant could not complete that action. Please try again.",
    retryable=True,
    http_status=502,
)

# ── Deliberate refusals ─────────────────────────────────────────────────────

ACTION_NOT_SUPPORTED = _failure(
    "ACTION_NOT_SUPPORTED",
    "I can't change your notes yet - creating, editing, moving, deleting, and "
    "tagging are still being built. For now I can find things and answer "
    "questions from your notes.",
    retryable=False,
    http_status=200,
)
APPROVAL_REQUIRED = _failure(
    "APPROVAL_REQUIRED",
    "That action needs your confirmation before it can run.",
    retryable=False,
    http_status=200,
)

# ── Anything else ───────────────────────────────────────────────────────────

INTERNAL_ERROR = _failure(
    "INTERNAL_ERROR",
    "Something went wrong on our end. Please try again.",
    retryable=True,
    http_status=500,
)


def get(code: str | None) -> Failure:
    """Look up a failure, falling back to INTERNAL_ERROR for unknown codes.

    Unknown codes are expected during a rolling deploy, when a newer service
    emits a code an older one has not learned yet. Falling back beats raising
    inside an error path.
    """
    return CATALOG.get(code or "", INTERNAL_ERROR)


def classify(exc: BaseException) -> Failure:
    """Map an exception to a failure without importing every service's types.

    Matching is on class name and message rather than on imported classes: this
    module is shared by services that do not install each other's dependencies,
    and an httpx import here would make the catalog un-importable in a service
    that does not use httpx.
    """
    name = type(exc).__name__
    text = str(exc).lower()

    if name in {"ApprovalRequired"}:
        return APPROVAL_REQUIRED
    if name in {"DomainUnavailableError"}:
        return DOMAIN_UNAVAILABLE
    if name in {"McpError", "RerankerUnavailableError"}:
        return TOOL_UNAVAILABLE if "failed:" not in text else TOOL_FAILED
    if name in {"SoftTimeLimitExceeded"} or "timeout" in name.lower() or "timed out" in text:
        return MODEL_TIMEOUT
    if "429" in text or "too many requests" in text or "rate limit" in text:
        return RATE_LIMITED
    if name in {"ConnectError", "ConnectTimeout"} or "connection refused" in text:
        return MODEL_UNAVAILABLE
    if "401" in text or "unauthorized" in text or "403" in text:
        return AUTH_REQUIRED
    return INTERNAL_ERROR


def from_status(status_code: int) -> Failure:
    """Map an upstream HTTP status onto the catalog."""
    if status_code in (401, 403):
        return AUTH_REQUIRED
    if status_code == 422:
        return REQUEST_INVALID
    if status_code == 429:
        return RATE_LIMITED
    if status_code in (502, 503):
        return AGENT_UNAVAILABLE
    if status_code == 504:
        return MODEL_TIMEOUT
    return INTERNAL_ERROR
