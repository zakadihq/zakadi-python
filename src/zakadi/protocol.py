"""Constants shared by every Zakadi client and server (protocol ``zakadi.v1``)."""

from __future__ import annotations

from enum import Enum, IntEnum

#: The WebSocket subprotocol every Zakadi client requests.
SUBPROTOCOL = "zakadi.v1"


class SessionState(str, Enum):
    """Client-side session states, in lifecycle order."""

    IDLE = "idle"
    CONSENT = "consent"
    PERMISSION = "permission"
    CONNECTING = "connecting"
    ACTIVE = "active"
    ENDED = "ended"
    ERROR = "error"


class SessionStatus(str, Enum):
    """Server-side session status as returned by the Zakadi API."""

    CREATED = "created"
    CONNECTED = "connected"
    IN_PROGRESS = "in_progress"
    VERIFYING = "verifying"
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"
    EXPIRED = "expired"
    ABORTED = "aborted"


class Decision(str, Enum):
    """Verdict decision in a result."""

    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


class Band(str, Enum):
    """Assurance band of a session."""

    A = "A"
    B = "B"
    C = "C"


class ErrorCode(str, Enum):
    """SDK error codes. Runtime conditions only; API misuse raises a usage error."""

    CONSENT_DECLINED = "consent_declined"
    CANCELLED = "cancelled"
    PERMISSION_DENIED = "permission_denied"
    UNSUPPORTED_DEVICE = "unsupported_device"
    SDK_DISABLED = "sdk_disabled"
    PACK_UNAVAILABLE = "pack_unavailable"
    NETWORK_UNAVAILABLE = "network_unavailable"
    AUTH_ERROR = "auth_error"
    SESSION_EXPIRED = "session_expired"
    SESSION_USED = "session_used"
    MAX_DURATION = "max_duration"
    ADMISSION_REJECTED = "admission_rejected"
    NETWORK_FLOOR = "network_floor"
    PROTOCOL_ERROR = "protocol_error"
    INTERRUPTED = "interrupted"
    CAPTURE_ERROR = "capture_error"
    ENCODER_ERROR = "encoder_error"
    INTERNAL = "internal"


class TerminalState(str, Enum):
    """Terminal UI states of a session on the client."""

    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    DISCONNECTED = "disconnected"
    NETWORK_FLOOR = "network_floor"
    CANCELLED = "cancelled"
    ERROR = "error"
    UNSUPPORTED_DEVICE = "unsupported_device"
    PERMISSION_DENIED = "permission_denied"
    INTERRUPTED = "interrupted"
    SDK_DISABLED = "sdk_disabled"

    @property
    def cue(self) -> str:
        """The prompt-pack cue the SDK may play locally for this state."""
        return _TERMINAL_CUES[self]

    @property
    def offers_redial(self) -> bool:
        """Whether the SDK offers a redial action in this state."""
        return self in _REDIAL_STATES


_TERMINAL_CUES: dict[TerminalState, str] = {
    TerminalState.COMPLETED: "done.thanks",
    TerminalState.INCOMPLETE: "fail.one_more_step",
    TerminalState.DISCONNECTED: "net.dropped",
    TerminalState.NETWORK_FLOOR: "net.slow",
    TerminalState.CANCELLED: "end.cancelled",
    TerminalState.ERROR: "end.error",
    TerminalState.UNSUPPORTED_DEVICE: "end.unsupported",
    TerminalState.PERMISSION_DENIED: "end.permission",
    TerminalState.INTERRUPTED: "end.interrupted",
    TerminalState.SDK_DISABLED: "end.disabled",
}

_REDIAL_STATES = frozenset(
    {
        TerminalState.INCOMPLETE,
        TerminalState.DISCONNECTED,
        TerminalState.NETWORK_FLOOR,
        TerminalState.ERROR,
        TerminalState.INTERRUPTED,
    }
)


class EndOutcome(str, Enum):
    """Outcome carried by the server's ``end`` message."""

    COMPLETED = "completed"
    ABORTED = "aborted"


class EndReason(str, Enum):
    """Reason carried by the server's ``end`` message."""

    OK = "ok"
    FLOOR_BREACHED = "floor_breached"
    MAX_DURATION = "max_duration"
    USER_CANCEL = "user_cancel"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    SERVER_ERROR = "server_error"
    ADMISSION = "admission"


def terminal_state_for_end(reason: EndReason) -> TerminalState:
    """Map an ``end`` reason to the terminal UI state the SDK shows."""
    return _END_TO_TERMINAL[reason]


_END_TO_TERMINAL: dict[EndReason, TerminalState] = {
    EndReason.OK: TerminalState.COMPLETED,
    EndReason.ATTEMPTS_EXHAUSTED: TerminalState.INCOMPLETE,
    EndReason.MAX_DURATION: TerminalState.INCOMPLETE,
    EndReason.FLOOR_BREACHED: TerminalState.NETWORK_FLOOR,
    EndReason.USER_CANCEL: TerminalState.CANCELLED,
    EndReason.SERVER_ERROR: TerminalState.ERROR,
    EndReason.ADMISSION: TerminalState.ERROR,
}


class CloseCode(IntEnum):
    """Application-level WebSocket close codes."""

    NORMAL = 1000
    TOKEN_INVALID = 4001
    TOKEN_EXPIRED = 4002
    SESSION_NOT_FOUND = 4003
    SESSION_USED = 4004
    UNSUPPORTED_CAPABILITIES = 4005
    PROTOCOL_VIOLATION = 4006
    MEDIA_FLOOR_BREACHED = 4007
    ADMISSION_REJECTED = 4008
    MAX_DURATION_EXCEEDED = 4009
    CANCELLED_BY_USER = 4010
    INTERNAL_ERROR = 4011


class ChallengeKind(str, Enum):
    """Challenge kinds the server may issue."""

    HEAD_TURN = "head_turn"
    DISTANCE = "distance"
    FINGERS = "fingers"
    DIGITS = "digits"
    BLINK = "blink"
    EXPRESSION = "expression"
    HAND_OVER_FACE = "hand_over_face"
    LOOK_PROFILE = "look_profile"


#: Webhook event types delivered to relying parties.
WEBHOOK_EVENTS: tuple[str, ...] = (
    "zakadi.session.completed",
    "zakadi.session.aborted",
    "zakadi.session.expired",
)
