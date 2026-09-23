"""Zakadi face-liveness API client for Python.

Pre-release. ``Zakadi`` is the server-side client: it creates sessions, reads
results, verifies webhook deliveries and verifies result tokens. The package also
ships the shared constants of the Zakadi protocol (``zakadi.v1``). See
https://zakadi.dev.
"""

from zakadi.client import (
    ApiError,
    Result,
    ResultPending,
    Session,
    VerificationError,
    WebhookEvent,
    Zakadi,
)
from zakadi.protocol import (
    SUBPROTOCOL,
    WEBHOOK_EVENTS,
    Band,
    ChallengeKind,
    CloseCode,
    Decision,
    EndOutcome,
    EndReason,
    ErrorCode,
    SessionState,
    SessionStatus,
    TerminalState,
    terminal_state_for_end,
)

__version__ = "0.0.1"

__all__ = [
    "SUBPROTOCOL",
    "WEBHOOK_EVENTS",
    "ApiError",
    "Band",
    "ChallengeKind",
    "CloseCode",
    "Decision",
    "EndOutcome",
    "EndReason",
    "ErrorCode",
    "Result",
    "ResultPending",
    "Session",
    "SessionState",
    "SessionStatus",
    "TerminalState",
    "VerificationError",
    "WebhookEvent",
    "Zakadi",
    "__version__",
    "terminal_state_for_end",
]
