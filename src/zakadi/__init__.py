"""Zakadi face-liveness API client for Python.

Pre-release. This version ships the shared protocol constants of the Zakadi
protocol (``zakadi.v1``); the server-side client (sessions, results, webhook
verification) follows in a later release. See https://zakadi.dev.
"""

from zakadi.protocol import (
    SUBPROTOCOL,
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
    WEBHOOK_EVENTS,
    terminal_state_for_end,
)

__version__ = "0.0.1"

__all__ = [
    "__version__",
    "SUBPROTOCOL",
    "Band",
    "ChallengeKind",
    "CloseCode",
    "Decision",
    "EndOutcome",
    "EndReason",
    "ErrorCode",
    "SessionState",
    "SessionStatus",
    "TerminalState",
    "WEBHOOK_EVENTS",
    "terminal_state_for_end",
]
