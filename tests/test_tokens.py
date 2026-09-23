import base64
import hashlib
import hmac
import json
import threading
import time
import unittest
from unittest import mock

from fake_api import API_KEY, JWKS, FakeApi, Reply, Signer, b64url, ok, result_claims

from zakadi import ApiError, VerificationError, Zakadi

THREADS = 8


class TokenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeApi()
        self.addCleanup(self.api.close)
        self.signer = Signer("key-2026-09")
        self.api.reply("GET", JWKS, ok({"keys": [self.signer.jwk()]}))
        self.results = Zakadi(api_key=API_KEY, base_url=self.api.base_url).results
        self.now = 1000.0  # what time.monotonic() returns; the tests move it
        clock = mock.patch("time.monotonic", lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)

    def fetches(self) -> int:
        return len(self.api.calls("GET", JWKS))

    def verify_at_once(self, token: str, hold: threading.Event) -> list[object]:
        """Verify ``token`` on ``THREADS`` threads at once; return each outcome.

        The fake API holds its JWKS answer until ``hold`` is set, which happens once
        the first request has come and the other threads have had time to queue.
        """
        start = threading.Barrier(THREADS)
        outcomes: list[object] = [None] * THREADS

        def verify(index: int) -> None:
            start.wait()
            try:
                outcomes[index] = self.results.verify_token(token)
            except Exception as error:
                outcomes[index] = error

        before = self.fetches()
        threads = [threading.Thread(target=verify, args=(i,)) for i in range(THREADS)]
        for thread in threads:
            thread.start()
        for _ in range(500):  # up to 5 s for the first request
            if self.fetches() > before:
                break
            time.sleep(0.01)
        time.sleep(0.2)
        hold.set()
        for thread in threads:
            thread.join(10)
        return outcomes

    def test_a_valid_token_returns_its_claims(self) -> None:
        claims = result_claims()
        self.assertEqual(self.results.verify_token(self.signer.token(claims)), claims)

    def test_any_other_alg_raises(self) -> None:
        for alg in ("ES384", "ES512", "RS256", "PS256", "EdDSA", "HS256", "none"):
            with self.subTest(alg=alg):
                token = self.signer.token(result_claims(), alg=alg)
                with self.assertRaises(VerificationError):
                    self.results.verify_token(token)

    def test_an_hs256_token_keyed_with_the_public_key_raises(self) -> None:
        head = b64url(json.dumps({"alg": "HS256", "kid": self.signer.kid}).encode())
        payload = b64url(json.dumps(result_claims()).encode())
        key = json.dumps(self.signer.jwk()).encode()
        mac = hmac.new(key, f"{head}.{payload}".encode(), hashlib.sha256).digest()
        with self.assertRaises(VerificationError):
            self.results.verify_token(f"{head}.{payload}.{b64url(mac)}")

    def test_a_signature_by_another_key_raises(self) -> None:
        impostor = Signer(self.signer.kid)
        with self.assertRaises(VerificationError):
            self.results.verify_token(impostor.token(result_claims()))

    def test_a_changed_payload_raises(self) -> None:
        head, _, signature = self.signer.token(result_claims()).split(".")
        forged = b64url(json.dumps(result_claims(decision="fail")).encode())
        with self.assertRaises(VerificationError):
            self.results.verify_token(f"{head}.{forged}.{signature}")

    def test_an_expired_token_raises(self) -> None:
        expired = result_claims(iat=int(time.time()) - 3700, exp=int(time.time()) - 1)
        for claims in (expired, result_claims(exp=None), result_claims(exp="never")):
            with self.subTest(exp=claims["exp"]):
                with self.assertRaises(VerificationError):
                    self.results.verify_token(self.signer.token(claims))

    def test_a_malformed_token_raises(self) -> None:
        token = self.signer.token(result_claims())
        head, payload, signature = token.split(".")
        short = b64url(base64.urlsafe_b64decode(signature + "==")[:63])
        for bad in (
            "",
            "not-a-token",
            f"{head}.{payload}",
            f"{token}.extra",
            f"{head}.{payload}.",
            f"{head}.{payload}.{signature}=",
            f"{head}.{payload}.{short}",
            f"{b64url(b'[]')}.{payload}.{signature}",
            f"{b64url(b'{')}.{payload}.{signature}",
            f"{b64url(json.dumps({'alg': 'ES256'}).encode())}.{payload}.{signature}",
        ):
            with self.subTest(token=bad[:24]):
                with self.assertRaises(VerificationError):
                    self.results.verify_token(bad)

    def test_the_jwks_is_cached(self) -> None:
        self.results.verify_token(self.signer.token(result_claims()))
        self.results.verify_token(self.signer.token(result_claims(jti="second")))
        self.assertEqual(self.fetches(), 1)

    def test_an_unknown_kid_refetches_the_jwks_once(self) -> None:
        self.results.verify_token(self.signer.token(result_claims()))
        rotated = Signer("key-2026-12")
        self.api.reply("GET", JWKS, ok({"keys": [self.signer.jwk(), rotated.jwk()]}))
        self.now += 60
        claims = result_claims()
        self.assertEqual(self.results.verify_token(rotated.token(claims)), claims)
        self.assertEqual(self.fetches(), 2)
        self.now += 60
        with self.assertRaises(VerificationError):
            self.results.verify_token(Signer("key-unknown").token(result_claims()))
        self.assertEqual(self.fetches(), 3)
        self.results.verify_token(rotated.token(claims))
        self.assertEqual(self.fetches(), 3)

    def test_an_unknown_kid_within_60_s_raises_without_a_request(self) -> None:
        self.results.verify_token(self.signer.token(result_claims()))
        rotated = Signer("key-2026-12")
        self.api.reply("GET", JWKS, ok({"keys": [self.signer.jwk(), rotated.jwk()]}))
        claims = result_claims()
        self.now += 59.5  # after the first fetch
        with self.assertRaises(VerificationError):
            self.results.verify_token(rotated.token(claims))
        self.assertEqual(self.fetches(), 1)
        self.now += 0.5
        self.assertEqual(self.results.verify_token(rotated.token(claims)), claims)
        self.assertEqual(self.fetches(), 2)
        self.now += 59.5  # after a refetch
        with self.assertRaises(VerificationError):
            self.results.verify_token(Signer("key-unknown").token(claims))
        self.assertEqual(self.fetches(), 2)

    def test_threads_share_one_jwks_request(self) -> None:
        rotated = Signer("key-2026-12")
        rounds = [
            (self.signer, [self.signer.jwk()]),  # the first fetch
            (rotated, [self.signer.jwk(), rotated.jwk()]),  # a refetch, 60 s on
        ]
        for fetches, (signer, keys) in enumerate(rounds, 1):
            with self.subTest(kid=signer.kid):
                hold = threading.Event()
                self.addCleanup(hold.set)
                self.api.reply("GET", JWKS, Reply(200, {"keys": keys}, hold=hold))
                claims = result_claims()
                outcomes = self.verify_at_once(signer.token(claims), hold)
                self.assertEqual(outcomes, [claims] * THREADS)
                self.assertEqual(self.fetches(), fetches)
            self.now += 60

    def test_threads_share_a_failed_first_fetch(self) -> None:
        hold = threading.Event()
        self.addCleanup(hold.set)
        self.api.reply(
            "GET",
            JWKS,
            Reply(404, b"<html>not found</html>", hold=hold),
            ok({"keys": [self.signer.jwk()]}),
        )
        claims = result_claims()
        token = self.signer.token(claims)
        outcomes = self.verify_at_once(token, hold)
        statuses = [o.status if isinstance(o, ApiError) else o for o in outcomes]
        self.assertEqual(statuses, [404] * THREADS)
        self.assertEqual(self.fetches(), 1)  # the waiters made no request
        self.assertEqual(self.results.verify_token(token), claims)  # clock unmoved
        self.assertEqual(self.fetches(), 2)  # a later call fetches again

    def test_a_failed_refetch_keeps_the_keys_and_starts_the_floor(self) -> None:
        claims = result_claims()
        self.results.verify_token(self.signer.token(claims))
        rotated = Signer("key-2026-12")
        self.api.reply(
            "GET",
            JWKS,
            Reply(404, b"<html>not found</html>"),
            ok({"keys": [self.signer.jwk(), rotated.jwk()]}),
        )
        self.now += 60
        with self.assertRaises(ApiError) as caught:
            self.results.verify_token(rotated.token(claims))
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(self.fetches(), 2)
        self.assertEqual(self.results.verify_token(self.signer.token(claims)), claims)
        self.now += 59.5
        with self.assertRaises(VerificationError):
            self.results.verify_token(rotated.token(claims))
        self.assertEqual(self.fetches(), 2)
        self.now += 0.5
        self.assertEqual(self.results.verify_token(rotated.token(claims)), claims)
        self.assertEqual(self.fetches(), 3)

    def test_with_nothing_cached_the_next_token_fetches(self) -> None:
        self.api.reply(
            "GET",
            JWKS,
            Reply(404, b"<html>not found</html>"),
            ok({"keys": [self.signer.jwk()]}),
        )
        claims = result_claims()
        token = self.signer.token(claims)
        with self.assertRaises(ApiError):
            self.results.verify_token(token)
        self.assertEqual(self.results.verify_token(token), claims)  # clock unmoved
        self.assertEqual(self.fetches(), 2)

    def test_keys_that_are_not_es256_are_not_used(self) -> None:
        jwk = self.signer.jwk()
        for change in ({"crv": "P-384"}, {"kty": "RSA"}, {"alg": "ES384"}, {"x": "!"}):
            with self.subTest(change=change):
                self.api.reply("GET", JWKS, ok({"keys": [jwk | change]}))
                results = Zakadi(api_key=API_KEY, base_url=self.api.base_url).results
                with self.assertRaises(VerificationError):
                    results.verify_token(self.signer.token(result_claims()))


if __name__ == "__main__":
    unittest.main()
