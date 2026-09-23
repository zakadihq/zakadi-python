import importlib.metadata
import json
import threading
import time
import unittest
import uuid
from email.utils import formatdate
from unittest import mock

from fake_api import (
    API_KEY,
    JWKS,
    SECRET,
    FakeApi,
    Reply,
    Signer,
    event_body,
    ok,
    problem,
    result_claims,
    result_json,
    session_json,
    webhook_headers,
)

from zakadi import ApiError, Result, ResultPending, Session, Zakadi

SESSIONS = "/v1/sessions"
RESULT = "/v1/sessions/ses_01J8ZK/result"


class ClientTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeApi()
        self.addCleanup(self.api.close)
        self.client = Zakadi(api_key=API_KEY, base_url=self.api.base_url)
        self.signer = Signer("key-2026-09")
        self.api.reply("GET", JWKS, ok({"keys": [self.signer.jwk()]}))
        self.client_token = self.signer.token(result_claims(aud="ingest"))
        self.result_token = self.signer.token(result_claims())
        sleep = mock.patch("time.sleep")  # retries record their delays instead
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def slept(self) -> list[float]:
        return [c.args[0] for c in self.sleep.call_args_list]


class SessionTests(ClientTestCase):
    def test_create_posts_the_body_and_returns_the_session(self) -> None:
        created = session_json(self.client_token)
        self.api.reply("POST", SESSIONS, ok(created, 201))
        body = {
            "user_ref": "cust-88213",
            "locale": "en-NG",
            "channel": "android",
            "device_correlation_id": "dev-7",
            "policy": {"version": 12, "overrides": {"min_actions": 2}},
            "ingest_hint": {"country": "NG"},
            "callback": {"url": "https://rp.example/hook", "secret_ref": "wh_sec_01"},
            "metadata": {"flow": "onboarding", "attempt": 1},
            "evidence": {"audit_frames": True, "clip": False, "retention_days": 7},
        }
        session = self.client.sessions.create(**body, idempotency_key="onb-88213-1")
        (call,) = self.api.calls("POST", SESSIONS)
        self.assertEqual(json.loads(call.body), body)
        self.assertEqual(call.headers["content-type"], "application/json")
        self.assertEqual(call.headers["idempotency-key"], "onb-88213-1")
        self.assertIsInstance(session, Session)
        self.assertEqual(session.session_id, "ses_01J8ZK")
        self.assertEqual(session.client_token, self.client_token)
        self.assertEqual(session.expires_at, "2026-09-22T10:05:00Z")
        self.assertEqual(session.ingest, created["ingest"])
        self.assertEqual(session.prompt_pack, created["prompt_pack"])
        self.assertEqual(session.ui, created["ui"])
        self.assertEqual((session.policy_version, session.status), (12, "created"))

    def test_create_sends_only_the_fields_given(self) -> None:
        self.api.reply("POST", SESSIONS, ok(session_json(self.client_token), 201))
        self.client.sessions.create(user_ref="cust-88213", channel="web")
        (call,) = self.api.calls("POST", SESSIONS)
        self.assertEqual(
            json.loads(call.body), {"user_ref": "cust-88213", "channel": "web"}
        )

    def test_result_returns_the_result_fields(self) -> None:
        body = result_json(self.result_token)
        self.api.reply("GET", RESULT, ok(body))
        result = self.client.sessions.result("ses_01J8ZK")
        self.assertIsInstance(result, Result)
        for name in (
            "session_id",
            "decision",
            "band",
            "confidence",
            "reason_codes",
            "reasons_detail",
            "challenges",
            "quality",
            "device",
            "models",
            "policy_version",
            "verdict_at",
            "evidence",
            "metadata",
            "result_token",
        ):
            self.assertEqual(getattr(result, name), body[name], name)
        self.assertFalse(hasattr(result, "unlisted"))

    def test_result_quotes_the_session_id(self) -> None:
        self.api.reply("GET", "/v1/sessions/a%2F..%2Fb/result", ok(result_json("t")))
        self.assertEqual(self.client.sessions.result("a/../b").result_token, "t")


class AuthorizationTests(ClientTestCase):
    def test_every_request_carries_the_api_key(self) -> None:
        self.api.reply(
            "POST",
            SESSIONS,
            problem(503, "internal_error"),
            ok(session_json(self.client_token), 201),
        )
        self.api.reply("GET", RESULT, ok(result_json(self.result_token)))
        session = self.client.sessions.create(user_ref="cust-88213")
        result = self.client.sessions.result(session.session_id)
        self.client.results.verify_token(result.result_token)
        paths = [r.path for r in self.api.received]
        self.assertEqual(paths, [SESSIONS, SESSIONS, RESULT, JWKS])
        for call in self.api.received:
            self.assertEqual(call.headers["authorization"], f"Bearer {API_KEY}")


class RetryTests(ClientTestCase):
    def test_429_and_5xx_are_retried_with_the_same_idempotency_key(self) -> None:
        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status):
                self.api.received.clear()
                self.api.reply(
                    "POST",
                    SESSIONS,
                    problem(status, "rate_limited"),
                    problem(status, "rate_limited"),
                    ok(session_json(self.client_token), 201),
                )
                self.client.sessions.create(user_ref="u", idempotency_key="onb-1")
                calls = self.api.calls("POST", SESSIONS)
                self.assertEqual(len(calls), 3)
                keys = {c.headers["idempotency-key"] for c in calls}
                self.assertEqual(keys, {"onb-1"})
                self.assertEqual(len({c.body for c in calls}), 1)

    def test_a_generated_idempotency_key_is_kept_across_retries(self) -> None:
        self.api.reply(
            "POST",
            SESSIONS,
            problem(502, "internal_error"),
            ok(session_json(self.client_token), 201),
        )
        self.client.sessions.create(user_ref="u")
        first, second = self.api.calls("POST", SESSIONS)
        key = first.headers["idempotency-key"]
        self.assertEqual(second.headers["idempotency-key"], key)
        self.assertEqual(str(uuid.UUID(key)), key)

    def test_each_call_generates_its_own_idempotency_key(self) -> None:
        self.api.reply("POST", SESSIONS, ok(session_json(self.client_token), 201))
        self.client.sessions.create(user_ref="u")
        self.client.sessions.create(user_ref="u")
        first, second = self.api.calls("POST", SESSIONS)
        self.assertNotEqual(
            first.headers["idempotency-key"], second.headers["idempotency-key"]
        )

    def test_backoff_grows_between_attempts(self) -> None:
        self.api.reply("POST", SESSIONS, problem(503, "internal_error"))
        with self.assertRaises(ApiError):
            self.client.sessions.create(user_ref="u")
        first, second = self.slept()
        self.assertTrue(0.25 <= first <= 0.5, first)
        self.assertTrue(0.5 <= second <= 1.0, second)

    def test_retry_after_seconds_is_honoured(self) -> None:
        self.api.reply(
            "POST",
            SESSIONS,
            problem(429, "rate_limited", **{"Retry-After": "7"}),
            ok(session_json(self.client_token), 201),
        )
        self.client.sessions.create(user_ref="u")
        self.assertEqual(self.slept(), [7.0])

    def test_retry_after_http_date_is_honoured(self) -> None:
        when = formatdate(time.time() + 20, usegmt=True)
        self.api.reply(
            "POST",
            SESSIONS,
            problem(503, "internal_error", **{"Retry-After": when}),
            ok(session_json(self.client_token), 201),
        )
        self.client.sessions.create(user_ref="u")
        (delay,) = self.slept()
        self.assertTrue(18 <= delay <= 20, delay)

    def test_retry_after_beyond_a_minute_raises_instead_of_waiting(self) -> None:
        self.api.reply(
            "POST", SESSIONS, problem(429, "rate_limited", **{"Retry-After": "3600"})
        )
        with self.assertRaises(ApiError) as caught:
            self.client.sessions.create(user_ref="u")
        self.assertEqual(caught.exception.code, "rate_limited")
        self.assertEqual(len(self.api.calls("POST", SESSIONS)), 1)
        self.assertEqual(self.slept(), [])

    def test_retries_stop_after_two(self) -> None:
        self.api.reply("POST", SESSIONS, problem(503, "internal_error"))
        with self.assertRaises(ApiError) as caught:
            self.client.sessions.create(user_ref="u")
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(len(self.api.calls("POST", SESSIONS)), 3)

    def test_gets_are_retried(self) -> None:
        self.api.reply(
            "GET", RESULT, problem(502, "internal_error"), ok(result_json("t"))
        )
        self.assertEqual(self.client.sessions.result("ses_01J8ZK").result_token, "t")
        self.assertEqual(len(self.api.calls("GET", RESULT)), 2)

    def test_no_other_4xx_is_retried(self) -> None:
        for status in (400, 401, 403, 404, 408, 409, 422):
            with self.subTest(status=status):
                self.api.received.clear()
                self.api.reply("POST", SESSIONS, problem(status, "validation_error"))
                with self.assertRaises(ApiError) as caught:
                    self.client.sessions.create(user_ref="u")
                self.assertEqual(caught.exception.status, status)
                self.assertEqual(len(self.api.calls("POST", SESSIONS)), 1)
        self.assertEqual(self.slept(), [])


class ErrorTests(ClientTestCase):
    def test_a_problem_raises_api_error_with_code_and_request_id(self) -> None:
        self.api.reply("POST", SESSIONS, problem(422, "idempotency_conflict", "req_42"))
        with self.assertRaises(ApiError) as caught:
            self.client.sessions.create(user_ref="u")
        error = caught.exception
        self.assertIs(type(error), ApiError)
        self.assertEqual((error.status, error.code), (422, "idempotency_conflict"))
        self.assertEqual(error.request_id, "req_42")
        self.assertEqual(error.detail, "test problem idempotency_conflict")
        self.assertIn("idempotency_conflict", str(error))
        self.assertIn("req_42", str(error))

    def test_result_pending_raises_the_subclass(self) -> None:
        self.api.reply("GET", RESULT, problem(404, "result_pending", "req_404"))
        with self.assertRaises(ResultPending) as caught:
            self.client.sessions.result("ses_01J8ZK")
        self.assertIsInstance(caught.exception, ApiError)
        self.assertEqual(caught.exception.code, "result_pending")
        self.assertEqual(caught.exception.request_id, "req_404")
        self.assertEqual(len(self.api.calls("GET", RESULT)), 1)

    def test_the_request_id_header_stands_in_for_a_missing_one(self) -> None:
        self.api.reply("GET", RESULT, problem(404, "session_not_found", None))
        with self.assertRaises(ApiError) as caught:
            self.client.sessions.result("ses_01J8ZK")
        self.assertEqual(caught.exception.code, "session_not_found")
        self.assertEqual(caught.exception.request_id, "req_header")

    def test_a_response_that_is_not_a_problem_still_raises_api_error(self) -> None:
        self.api.reply("GET", RESULT, Reply(400, b"<html>bad gateway</html>"))
        with self.assertRaises(ApiError) as caught:
            self.client.sessions.result("ses_01J8ZK")
        self.assertEqual((caught.exception.status, caught.exception.code), (400, None))
        self.assertEqual(caught.exception.request_id, "req_header")

    def test_redirects_are_not_followed(self) -> None:
        self.api.reply("GET", RESULT, Reply(302, b"", {"Location": "http://other/"}))
        with self.assertRaises(ApiError) as caught:
            self.client.sessions.result("ses_01J8ZK")
        self.assertEqual(caught.exception.status, 302)
        self.assertEqual(len(self.api.received), 1)

    def test_an_empty_api_key_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            Zakadi(api_key="")


class TimeoutTests(ClientTestCase):
    def test_a_request_times_out(self) -> None:
        hold = threading.Event()
        self.addCleanup(hold.set)
        self.api.reply("GET", RESULT, Reply(200, result_json("t"), hold=hold))
        with mock.patch("zakadi.client._TIMEOUT", 0.2):
            started = time.monotonic()
            with self.assertRaises(OSError):
                self.client.sessions.result("ses_01J8ZK")
        self.assertLess(time.monotonic() - started, 5)
        hold.set()


class RedactionTests(ClientTestCase):
    def test_tokens_stay_out_of_log_records_and_reprs(self) -> None:
        self.api.reply(
            "POST",
            SESSIONS,
            problem(503, "internal_error"),
            ok(session_json(self.client_token), 201),
        )
        self.api.reply("GET", RESULT, ok(result_json(self.result_token)))
        body = event_body(self.result_token)
        with self.assertLogs("zakadi", level="DEBUG") as logs:
            session = self.client.sessions.create(user_ref="cust-88213")
            result = self.client.sessions.result(session.session_id)
            self.client.results.verify_token(result.result_token)
            event = self.client.webhooks.verify(
                webhook_headers(body), body, secret=SECRET
            )
        logged = "\n".join(logs.output + [str(r.args) for r in logs.records])
        shown = "\n".join(repr(o) for o in (session, result, event))
        self.assertIn("ses_01J8ZK", shown)
        for token in (self.client_token, self.result_token):
            for part in [token, *token.split(".")[1:]]:
                self.assertNotIn(part, logged)
                self.assertNotIn(part, shown)
        self.assertEqual(session.client_token, self.client_token)
        self.assertEqual(event.result_token, self.result_token)


class PackageTests(unittest.TestCase):
    def test_requires_python_stays_3_10(self) -> None:
        metadata = importlib.metadata.metadata("zakadi")
        self.assertEqual(metadata["Requires-Python"], ">=3.10")


if __name__ == "__main__":
    unittest.main()
