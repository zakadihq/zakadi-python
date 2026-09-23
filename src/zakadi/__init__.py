"""Zakadi face-liveness API client for Python.

Pre-release. This version ships the shared protocol constants of the Zakadi
protocol (``zakadi.v1``); the server-side client (sessions, results, webhook
verification) follows in a later release. See https://zakadi.dev.
"""

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
    "__version__",
    "terminal_state_for_end",
]
