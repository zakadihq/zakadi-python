"""A fake Zakadi API for the tests: scripted replies served by http.server on 127.0.0.1.

It also holds what the real API signs with: ES256 keys published as a JWKS, and the
webhook HMAC of ``spec/02-api.md`` 2.4.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

API_KEY = "zk_test_4Fq9LmZ2xT7bN1cR8vK3pW6sY0dH5jEa"
JWKS = "/.well-known/jwks.json"
SECRET = "zakadi-test-webhook-secret-of-at-least-32-bytes"


@dataclass
class Reply:
    """One scripted answer: a JSON value (or raw bytes), its status and headers."""

    status: int
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    hold: threading.Event | None = None  # answer only once this is set


@dataclass
class Received:
    method: str
    path: str
    headers: dict[str, str]  # names lower-cased
    body: bytes


def ok(body: Any, status: int = 200) -> Reply:
    return Reply(status, body, {"Content-Type": "application/json"})


def problem(
    status: int, code: str, request_id: str | None = "req_body", **headers: str
) -> Reply:
    body = {
        "type": f"https://docs.zakadi.dev/errors/{code}",
        "title": code.replace("_", " "),
        "status": status,
        "detail": f"test problem {code}",
        "code": code,
    }
    if request_id is not None:
        body["request_id"] = request_id
    return Reply(status, body, {"Content-Type": "application/problem+json", **headers})


class _QuietServer(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:
        pass  # a client that timed out closed its socket first


class FakeApi:
    """Answers each ``(method, path)`` with its scripted replies; the last repeats."""

    def __init__(self) -> None:
        self.received: list[Received] = []
        self._replies: dict[tuple[str, str], list[Reply]] = {}
        self._lock = threading.Lock()
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                api._answer(self)

            def do_POST(self) -> None:
                api._answer(self)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self._server = _QuietServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, args=(0.01,), daemon=True
        )
        self._thread.start()
        self.base_url = f"http://127.0.0.1:{self._server.server_port}"

    def reply(self, method: str, path: str, *replies: Reply) -> None:
        with self._lock:
            self._replies[(method, path)] = list(replies)

    def calls(self, method: str, path: str) -> list[Received]:
        with self._lock:
            return [r for r in self.received if (r.method, r.path) == (method, path)]

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()

    def _answer(self, handler: BaseHTTPRequestHandler) -> None:
        length = int(handler.headers.get("Content-Length") or 0)
        headers = {name.lower(): value for name, value in handler.headers.items()}
        received = Received(
            handler.command, handler.path, headers, handler.rfile.read(length)
        )
        with self._lock:
            self.received.append(received)
            queue = self._replies.get((handler.command, handler.path), [])
            reply = queue.pop(0) if len(queue) > 1 else None
            if reply is None:
                reply = queue[0] if queue else problem(404, "session_not_found")
        if reply.hold is not None:
            reply.hold.wait(10)
        body = reply.body
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
        handler.send_response(reply.status)
        handler.send_header("Zakadi-Request-Id", "req_header")
        for name, value in reply.headers.items():
            handler.send_header(name, value)
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Signer:
    """An ES256 key under ``kid``, as the API publishes it in its JWKS (2.8)."""

    def __init__(self, kid: str) -> None:
        self.kid = kid
        self._key = ec.generate_private_key(ec.SECP256R1())

    def jwk(self) -> dict[str, str]:
        numbers = self._key.public_key().public_numbers()
        return {
            "kty": "EC",
            "crv": "P-256",
            "alg": "ES256",
            "use": "sig",
            "kid": self.kid,
            "x": b64url(numbers.x.to_bytes(32, "big")),
            "y": b64url(numbers.y.to_bytes(32, "big")),
        }

    def token(self, claims: dict[str, Any], **header: Any) -> str:
        head = b64url(json.dumps({"alg": "ES256", "kid": self.kid, **header}).encode())
        payload = b64url(json.dumps(claims).encode())
        der = self._key.sign(f"{head}.{payload}".encode(), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        return f"{head}.{payload}.{b64url(signature)}"


def result_claims(**changes: Any) -> dict[str, Any]:
    """The ``result_token`` claims of ``spec/02-api.md`` 2.3, valid for an hour."""
    now = int(time.time())
    claims = {
        "iss": "https://api.zakadi.dev",
        "aud": "ten_01J8TEST",
        "sub": "ses_01J8ZK",
        "jti": "3q2-7wAAAAAAAAAAAAAAAA",
        "iat": now,
        "exp": now + 3600,
        "decision": "pass",
        "band": "A",
        "confidence": 0.97,
        "reason_codes": ["ACTIONS_OK", "PAD_OK", "NONCE_OK", "TIMING_OK"],
        "user_ref_hash": "9f86d081884c7d659a2feaa0c55ad015",
        "policy_version": 12,
        "models_hash": "d41d8cd98f00b204",
    }
    claims.update(changes)
    return claims


def session_json(client_token: str) -> dict[str, Any]:
    """The 201 body of ``spec/02-api.md`` 2.2, plus an unlisted field."""
    return {
        "session_id": "ses_01J8ZK",
        "client_token": client_token,
        "expires_at": "2026-09-22T10:05:00Z",
        "ingest": [
            {
                "region": "eu-west-2",
                "url": "wss://ingest-euw2.zakadi.dev/v1/sessions/ses_01J8ZK/stream",
            },
            {
                "region": "af-south-1",
                "url": "wss://ingest-afs1.zakadi.dev/v1/sessions/ses_01J8ZK/stream",
            },
        ],
        "prompt_pack": {
            "lang": "en-NG",
            "version": "2026.09.1",
            "url": "https://cdn.zakadi.dev/packs/en-NG/2026.09.1/manifest.json",
        },
        "ui": {
            "consent_copy": {
                "en-NG": {"title": "t", "body": "b", "recording_notice": "r"}
            },
            "brand": {"primary": "#0A5", "logo_url": None},
            "badge_text": None,
            "packs": [
                {"lang": "en-NG", "version": "2026.09.1", "url": "https://cdn/en"},
                {"lang": "fr-CI", "version": "2026.09.1", "url": "https://cdn/fr"},
            ],
        },
        "policy_version": 12,
        "status": "created",
        "unlisted": "ignored",
    }


def result_json(result_token: str | None) -> dict[str, Any]:
    """The result 200 body of ``spec/02-api.md`` 2.3, plus an unlisted field."""
    body: dict[str, Any] = {
        "session_id": "ses_01J8ZK",
        "decision": "pass",
        "band": "A",
        "confidence": 0.97,
        "reason_codes": ["ACTIONS_OK", "PAD_OK", "NONCE_OK", "TIMING_OK"],
        "reasons_detail": [
            {
                "code": "NONCE_WEAK",
                "severity": "info",
                "text": "illumination response weak; outdoor session",
            }
        ],
        "challenges": [
            {
                "id": "a1",
                "kind": "head_turn",
                "result": "pass",
                "attempts": 1,
                "latency_ms": 640,
            },
            {
                "id": "a2",
                "kind": "fingers",
                "result": "pass",
                "attempts": 2,
                "latency_ms": 910,
            },
        ],
        "quality": {
            "lighting": "low",
            "face_size": "ok",
            "network_rung_median": 2,
            "received_fps_median": 14.6,
        },
        "device": {
            "platform": "android",
            "attested": True,
            "attestation_verdict": "MEETS_DEVICE_INTEGRITY",
        },
        "models": {
            "pad_trunk": "dinov2b-reg-pad@1.3.0+d41d8",
            "fusion": "fusion@0.9.2",
            "landmarks": "mediapipe-face-0.10.31",
        },
        "policy_version": 12,
        "verdict_at": "2026-09-22T10:01:12Z",
        "evidence": {
            "audit_frames": 2,
            "clip": False,
            "expires_at": "2026-09-29T10:01:12Z",
        },
        "metadata": {"flow": "onboarding", "attempt": 1},
        "unlisted": "ignored",
    }
    if result_token is not None:
        body["result_token"] = result_token
    return body


def event_body(result_token: str, event_id: str = "evt_01J8ZK") -> bytes:
    """A ``zakadi.session.completed`` delivery body (2.4)."""
    event = {
        "id": event_id,
        "type": "zakadi.session.completed",
        "created_at": "2026-09-22T10:01:13Z",
        "data": result_json(None),
        "result_token": result_token,
    }
    return json.dumps(event).encode()


def webhook_headers(
    body: bytes,
    *,
    secret: str = SECRET,
    event_id: str = "evt_01J8ZK",
    timestamp: int | None = None,
) -> dict[str, str]:
    """The three delivery headers of 2.4, signing ``<id>.<timestamp>.<body>``."""
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    signed = f"{event_id}.{stamp}.".encode() + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return {
        "Zakadi-Webhook-Id": event_id,
        "Zakadi-Webhook-Timestamp": stamp,
        "Zakadi-Webhook-Signature": f"v1={digest}",
    }
