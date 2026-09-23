"""Server-side client for the Zakadi API (``spec/02-api.md`` 2.11).

``Zakadi`` creates sessions and reads results over ``urllib.request``, verifies webhook
deliveries (HMAC-SHA256, 2.4) and verifies result tokens (ES256 against the API's JWKS,
2.8). ``client_token`` and ``result_token`` never appear in a log record or a ``repr``.
"""

from __future__ import annotations

import base64
import email.utils
import hashlib
import hmac
import json
import logging
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from email.message import Message
from typing import IO, Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

_log = logging.getLogger(__name__)

_TIMEOUT = 30.0  # seconds per attempt
_MAX_RETRIES = 2
_BACKOFF = 0.5  # seconds before the first retry, doubled for each later one
_MAX_RETRY_AFTER = 60.0  # a longer Retry-After ends the retries instead
_WEBHOOK_TOLERANCE = 300  # seconds (2.4)
_JWS = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


class ApiError(Exception):
    """A non-2xx response, with the problem ``code`` and ``request_id`` (2.1, 2.9)."""

    def __init__(
        self,
        status: int,
        code: str | None = None,
        request_id: str | None = None,
        title: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(status, code, request_id, title, detail)
        self.status = status
        self.code = code
        self.request_id = request_id
        self.title = title
        self.detail = detail

    def __str__(self) -> str:
        text = " ".join(
            str(p) for p in (self.status, self.code, self.detail or self.title) if p
        )
        return f"{text} (request id {self.request_id})" if self.request_id else text


class ResultPending(ApiError):
    """``result_pending``: no verdict yet; poll with backoff or wait for the webhook."""


class VerificationError(Exception):
    """A webhook delivery or a token that does not verify."""


@dataclass(frozen=True, kw_only=True)
class Session:
    """A created session (``POST /v1/sessions``, 2.2).

    Hand ``client_token``, ``ingest``, ``prompt_pack`` and ``ui`` to the app unchanged.
    """

    session_id: str
    client_token: str = field(repr=False)
    expires_at: str
    ingest: list[dict[str, Any]]
    prompt_pack: dict[str, Any]
    ui: dict[str, Any]
    policy_version: int
    status: str


@dataclass(frozen=True, kw_only=True)
class Result:
    """A session's verdict (``GET /v1/sessions/{id}/result``, 2.3)."""

    session_id: str
    decision: str
    band: str
    confidence: float
    reason_codes: list[str]
    reasons_detail: list[dict[str, Any]]
    challenges: list[dict[str, Any]]
    quality: dict[str, Any]
    device: dict[str, Any]
    models: dict[str, Any]
    policy_version: int
    verdict_at: str
    evidence: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    result_token: str = field(repr=False)


@dataclass(frozen=True, kw_only=True)
class WebhookEvent:
    """A verified webhook delivery (2.4); ``data`` is the result without its token."""

    id: str
    type: str
    created_at: str
    data: dict[str, Any]
    result_token: str | None = field(default=None, repr=False)


def _known(cls: type[Any], data: dict[str, Any]) -> dict[str, Any]:
    """The members of ``data`` that ``cls`` declares; the rest are ignored."""
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in names}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: urllib would send the API key on to the new location."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


class _Transport:
    def __init__(self, api_key: str, base_url: str) -> None:
        from zakadi import __version__

        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": f"zakadi-python/{__version__}",
        }
        self._opener = urllib.request.build_opener(_NoRedirect)

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Send one call, retrying 429 and 5xx; return the JSON object it answers."""
        headers = dict(self._headers)
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        attempt = 0
        while True:
            request = urllib.request.Request(
                self._base_url + path, data=data, headers=headers, method=method
            )
            status, reply_headers, raw = self._send(request)
            request_id = reply_headers.get("Zakadi-Request-Id")
            _log.debug("%s %s -> %d (request id %s)", method, path, status, request_id)
            if 200 <= status < 300:
                try:
                    reply = json.loads(raw)
                except ValueError:
                    reply = None
                if not isinstance(reply, dict):
                    raise ApiError(status, None, request_id, None, "not a JSON object")
                return reply
            if (status == 429 or status >= 500) and attempt < _MAX_RETRIES:
                delay = _retry_delay(attempt, reply_headers.get("Retry-After"))
                if delay is not None:
                    _log.info(
                        "%s %s -> %d, retrying in %.2f s", method, path, status, delay
                    )
                    time.sleep(delay)
                    attempt += 1
                    continue
            raise _api_error(status, request_id, raw)

    def _send(self, request: urllib.request.Request) -> tuple[int, Message, bytes]:
        try:
            with self._opener.open(request, timeout=_TIMEOUT) as reply:
                return reply.status, reply.headers, reply.read()
        except urllib.error.HTTPError as error:
            try:
                return error.code, error.headers, error.read()
            finally:
                error.close()


def _retry_delay(attempt: int, retry_after: str | None) -> float | None:
    """Seconds before the next attempt: the backoff, or Retry-After when longer.

    None when Retry-After asks for more than ``_MAX_RETRY_AFTER`` seconds.
    """
    backoff = _BACKOFF * 2**attempt * random.uniform(0.5, 1.0)
    value = (retry_after or "").strip()
    if value.isascii() and value.isdigit():
        wait = float(value)
    else:
        parsed = email.utils.parsedate_tz(value)
        if parsed is None:
            return backoff
        try:
            wait = email.utils.mktime_tz(parsed) - time.time()
        except (OverflowError, ValueError):
            return backoff
    if wait > _MAX_RETRY_AFTER:
        return None
    return max(backoff, wait)


def _api_error(status: int, request_id: str | None, raw: bytes) -> ApiError:
    try:
        problem = json.loads(raw)
    except ValueError:
        problem = None
    if not isinstance(problem, dict):
        problem = {}

    def text(name: str) -> str | None:
        value = problem.get(name)
        return value if isinstance(value, str) else None

    code = text("code")
    kind = ResultPending if code == "result_pending" else ApiError
    return kind(
        status, code, text("request_id") or request_id, text("title"), text("detail")
    )


class Sessions:
    """``client.sessions``: create a session and read its result."""

    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    def create(
        self,
        *,
        user_ref: str,
        locale: str | None = None,
        channel: str | None = None,
        device_correlation_id: str | None = None,
        policy: dict[str, Any] | None = None,
        ingest_hint: dict[str, Any] | None = None,
        callback: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Session:
        """``POST /v1/sessions`` with the 2.2 fields given; None fields are left out.

        Every attempt carries the same ``Idempotency-Key``: ``idempotency_key`` when
        given, else one generated for this call.
        """
        given = {
            "user_ref": user_ref,
            "locale": locale,
            "channel": channel,
            "device_correlation_id": device_correlation_id,
            "policy": policy,
            "ingest_hint": ingest_hint,
            "callback": callback,
            "metadata": metadata,
            "evidence": evidence,
        }
        body = {k: v for k, v in given.items() if v is not None}
        key = idempotency_key or str(uuid.uuid4())
        reply = self._transport.request("POST", "/v1/sessions", body, key)
        return Session(**_known(Session, reply))

    def result(self, session_id: str) -> Result:
        """``GET /v1/sessions/{id}/result``.

        Raises ``ResultPending`` until the verdict exists.
        """
        path = f"/v1/sessions/{urllib.parse.quote(session_id, safe='')}/result"
        return Result(**_known(Result, self._transport.request("GET", path)))


class Results:
    """``client.results``: verify a ``result_token`` against the API's JWKS."""

    def __init__(self, transport: _Transport) -> None:
        self._transport = transport
        self._keys: dict[str, ec.EllipticCurvePublicKey] | None = None

    def verify_token(self, token: str) -> dict[str, Any]:
        """The claims of an unexpired ES256 JWS signed by the JWKS key named by ``kid``.

        Raises ``VerificationError`` for any other ``alg``, an unknown ``kid``, a
        signature that does not verify, or an ``exp`` that is missing or past;
        ``ApiError`` when the JWKS cannot be fetched.
        """
        if not isinstance(token, str) or not _JWS.fullmatch(token):
            raise VerificationError("token is not a compact JWS")
        header_b64, payload_b64, signature_b64 = token.split(".")
        header = _json_segment(header_b64)
        if header.get("alg") != "ES256":
            raise VerificationError("token alg is not ES256")
        kid = header.get("kid")
        if not isinstance(kid, str):
            raise VerificationError("token has no kid")
        key = self._key(kid)
        signature = _segment(signature_b64)
        if len(signature) != 64:
            raise VerificationError("token signature is not ES256")
        der = encode_dss_signature(
            int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
        )
        signed = f"{header_b64}.{payload_b64}".encode("ascii")
        try:
            key.verify(der, signed, ec.ECDSA(hashes.SHA256()))
        except InvalidSignature:
            raise VerificationError("token signature does not verify") from None
        claims = _json_segment(payload_b64)
        exp = claims.get("exp")
        if (
            isinstance(exp, bool)
            or not isinstance(exp, (int, float))
            or exp <= time.time()
        ):
            raise VerificationError("token has expired or has no exp")
        return claims

    def _key(self, kid: str) -> ec.EllipticCurvePublicKey:
        """The cached key for ``kid``; an unknown ``kid`` refetches the JWKS once."""
        key = self._keys.get(kid) if self._keys is not None else None
        if key is None:
            self._keys = self._fetch_keys()
            key = self._keys.get(kid)
        if key is None:
            raise VerificationError("no JWKS key has the token's kid")
        return key

    def _fetch_keys(self) -> dict[str, ec.EllipticCurvePublicKey]:
        jwks = self._transport.request("GET", "/.well-known/jwks.json")
        keys: dict[str, ec.EllipticCurvePublicKey] = {}
        entries = jwks.get("keys")
        for jwk in entries if isinstance(entries, list) else []:
            if not isinstance(jwk, dict) or not isinstance(jwk.get("kid"), str):
                continue
            if (jwk.get("kty"), jwk.get("crv"), jwk.get("alg", "ES256")) != (
                "EC",
                "P-256",
                "ES256",
            ):
                continue
            try:
                x = int.from_bytes(_segment(jwk["x"]), "big")
                y = int.from_bytes(_segment(jwk["y"]), "big")
                keys[jwk["kid"]] = ec.EllipticCurvePublicNumbers(
                    x, y, ec.SECP256R1()
                ).public_key()
            except (KeyError, ValueError, VerificationError):
                continue
        return keys


def _segment(value: object) -> bytes:
    """Decode one unpadded base64url segment."""
    if not isinstance(value, str):
        raise VerificationError("not a base64url string")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError:
        raise VerificationError("not a base64url string") from None


def _json_segment(value: str) -> dict[str, Any]:
    try:
        decoded = json.loads(_segment(value))
    except ValueError:
        decoded = None
    if not isinstance(decoded, dict):
        raise VerificationError("token segment is not a JSON object")
    return decoded


class Webhooks:
    """``client.webhooks``: verify a webhook delivery (2.4)."""

    def verify(
        self, headers: Mapping[str, str], raw_body: bytes | str, *, secret: str | bytes
    ) -> WebhookEvent:
        """Return the event when ``Zakadi-Webhook-Signature`` is ``v1=`` and the hex
        HMAC-SHA256 under ``secret`` of ``<id>.<timestamp>.<body>``, from
        ``Zakadi-Webhook-Id``, ``Zakadi-Webhook-Timestamp`` and the raw body.

        Header names match case-insensitively. Raises ``VerificationError`` otherwise,
        and for a timestamp older than 300 s.
        """
        if not secret:
            raise ValueError("secret is required")
        found: dict[str, str] = {}
        for name, value in headers.items():
            found.setdefault(name.lower(), value)
        event_id = found.get("zakadi-webhook-id")
        timestamp = found.get("zakadi-webhook-timestamp")
        signature = found.get("zakadi-webhook-signature")
        if not event_id or not timestamp or not signature:
            raise VerificationError(
                "a Zakadi-Webhook-Id, -Timestamp or -Signature header is missing"
            )
        if not (timestamp.isascii() and timestamp.isdigit()):
            raise VerificationError("Zakadi-Webhook-Timestamp is not unix seconds")
        scheme, _, digest = signature.strip().partition("=")
        body = raw_body.encode() if isinstance(raw_body, str) else raw_body
        key = secret.encode() if isinstance(secret, str) else secret
        signed = b".".join((event_id.encode(), timestamp.encode(), body))
        expected = hmac.new(key, signed, hashlib.sha256).hexdigest()
        if scheme != "v1" or not hmac.compare_digest(
            expected.encode(), digest.encode()
        ):
            raise VerificationError("Zakadi-Webhook-Signature does not match")
        if time.time() - int(timestamp) > _WEBHOOK_TOLERANCE:
            raise VerificationError("Zakadi-Webhook-Timestamp is older than 300 s")
        try:
            event = json.loads(body)
        except ValueError:
            event = None
        if not isinstance(event, dict):
            raise VerificationError("webhook body is not a JSON object")
        try:
            return WebhookEvent(**_known(WebhookEvent, event))
        except TypeError:
            raise VerificationError("webhook body is not an event") from None


class Zakadi:
    """Client for the Zakadi server-to-server API (2.11).

    Every request carries ``Authorization: Bearer <api_key>``, times out after 30 s,
    and is retried twice on 429 and 5xx with backoff that honours ``Retry-After``.
    Transport failures (timeouts, refused connections) propagate from urllib.
    """

    def __init__(
        self, *, api_key: str, base_url: str = "https://api.zakadi.dev"
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        transport = _Transport(api_key, base_url)
        self.sessions = Sessions(transport)
        self.results = Results(transport)
        self.webhooks = Webhooks()
