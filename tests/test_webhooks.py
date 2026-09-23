import hmac
import time
import unittest
from unittest import mock

from fake_api import API_KEY, SECRET, event_body, webhook_headers

from zakadi import VerificationError, WebhookEvent, Zakadi

TOKEN = "eyJhbGciOiJFUzI1NiJ9.eyJzdWIiOiJzZXNfMDFKOFpLIn0.c2lnbmF0dXJl"


class WebhookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.webhooks = Zakadi(api_key=API_KEY).webhooks
        self.body = event_body(TOKEN)

    def test_a_signed_delivery_returns_the_event(self) -> None:
        event = self.webhooks.verify(
            webhook_headers(self.body), self.body, secret=SECRET
        )
        self.assertIsInstance(event, WebhookEvent)
        self.assertEqual(event.id, "evt_01J8ZK")
        self.assertEqual(event.type, "zakadi.session.completed")
        self.assertEqual(event.created_at, "2026-09-22T10:01:13Z")
        self.assertEqual(event.data["decision"], "pass")
        self.assertNotIn("result_token", event.data)
        self.assertEqual(event.result_token, TOKEN)

    def test_header_names_match_case_insensitively(self) -> None:
        headers = webhook_headers(self.body)
        for case in (str.lower, str.upper, str.title):
            with self.subTest(case=case.__name__):
                cased = {case(name): value for name, value in headers.items()}
                event = self.webhooks.verify(cased, self.body, secret=SECRET)
                self.assertEqual(event.id, "evt_01J8ZK")

    def test_the_signature_is_compared_in_constant_time(self) -> None:
        headers = webhook_headers(self.body)
        with mock.patch("hmac.compare_digest", wraps=hmac.compare_digest) as compare:
            self.webhooks.verify(headers, self.body, secret=SECRET)
        compare.assert_called_once()
        expected = headers["Zakadi-Webhook-Signature"].removeprefix("v1=")
        self.assertEqual(compare.call_args.args, (expected.encode(), expected.encode()))

    def test_a_str_body_and_a_bytes_secret_are_accepted(self) -> None:
        headers = webhook_headers(self.body)
        text = self.body.decode()
        event = self.webhooks.verify(headers, text, secret=SECRET.encode())
        self.assertEqual(event.id, "evt_01J8ZK")

    def test_anything_else_raises_verification_error(self) -> None:
        now = int(time.time())
        good = webhook_headers(self.body, timestamp=now)
        signature = good["Zakadi-Webhook-Signature"]
        other_body = event_body(TOKEN, event_id="evt_other")
        cases = {
            "no id": ({**good, "Zakadi-Webhook-Id": ""}, self.body, SECRET),
            "no timestamp": (
                {k: v for k, v in good.items() if k != "Zakadi-Webhook-Timestamp"},
                self.body,
                SECRET,
            ),
            "no signature": (
                {k: v for k, v in good.items() if k != "Zakadi-Webhook-Signature"},
                self.body,
                SECRET,
            ),
            "other scheme": (
                {**good, "Zakadi-Webhook-Signature": signature.replace("v1=", "v0=")},
                self.body,
                SECRET,
            ),
            "bare digest": (
                {**good, "Zakadi-Webhook-Signature": signature.removeprefix("v1=")},
                self.body,
                SECRET,
            ),
            "wrong digest": (
                {**good, "Zakadi-Webhook-Signature": "v1=" + "0" * 64},
                self.body,
                SECRET,
            ),
            "wrong secret": (good, self.body, SECRET + "x"),
            "other body": (good, other_body, SECRET),
            "other id": ({**good, "Zakadi-Webhook-Id": "evt_other"}, self.body, SECRET),
            "other timestamp": (
                {**good, "Zakadi-Webhook-Timestamp": str(now + 1)},
                self.body,
                SECRET,
            ),
            "timestamp not seconds": (
                webhook_headers(self.body, timestamp=now)
                | {"Zakadi-Webhook-Timestamp": f"{now}.0"},
                self.body,
                SECRET,
            ),
            "not an event": (webhook_headers(b"[]"), b"[]", SECRET),
            "not json": (webhook_headers(b"{"), b"{", SECRET),
        }
        for name, (headers, body, secret) in cases.items():
            with self.subTest(name):
                with self.assertRaises(VerificationError):
                    self.webhooks.verify(headers, body, secret=secret)

    def test_a_timestamp_older_than_300_s_raises(self) -> None:
        old = webhook_headers(self.body, timestamp=int(time.time()) - 301)
        with self.assertRaises(VerificationError):
            self.webhooks.verify(old, self.body, secret=SECRET)
        recent = webhook_headers(self.body, timestamp=int(time.time()) - 290)
        self.assertEqual(
            self.webhooks.verify(recent, self.body, secret=SECRET).id, "evt_01J8ZK"
        )

    def test_an_empty_secret_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.webhooks.verify(webhook_headers(self.body), self.body, secret="")


if __name__ == "__main__":
    unittest.main()
