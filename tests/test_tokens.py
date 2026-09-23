import base64
import hashlib
import hmac
import json
import time
import unittest

from fake_api import API_KEY, JWKS, FakeApi, Signer, b64url, ok, result_claims

from zakadi import VerificationError, Zakadi


class TokenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeApi()
        self.addCleanup(self.api.close)
        self.signer = Signer("key-2026-09")
        self.api.reply("GET", JWKS, ok({"keys": [self.signer.jwk()]}))
        self.results = Zakadi(api_key=API_KEY, base_url=self.api.base_url).results

    def fetches(self) -> int:
        return len(self.api.calls("GET", JWKS))

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
        claims = result_claims()
        self.assertEqual(self.results.verify_token(rotated.token(claims)), claims)
        self.assertEqual(self.fetches(), 2)
        with self.assertRaises(VerificationError):
            self.results.verify_token(Signer("key-unknown").token(result_claims()))
        self.assertEqual(self.fetches(), 3)
        self.results.verify_token(rotated.token(claims))
        self.assertEqual(self.fetches(), 3)

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
