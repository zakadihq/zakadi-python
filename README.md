# zakadi

Zakadi face-liveness API client for Python. Zakadi is an active face liveness check delivered as a short automated video call; relying parties create sessions and read verdicts server to server.

Pre-release. `Zakadi` is the server-side client, for Python 3.10 or newer: it creates sessions, reads results, verifies webhook deliveries and verifies result tokens. The package also ships the shared protocol constants (session states and statuses, decisions and bands, SDK error codes, terminal states, close codes, challenge kinds, webhook event types) with type annotations.

```python
from zakadi import ResultPending, Zakadi

client = Zakadi(api_key="zk_live_...", base_url="https://api.zakadi.dev")
s = client.sessions.create(
    user_ref="cust-88213",
    locale="en-NG",
    channel="android",
    idempotency_key="onb-88213-1",
)
# hand s.client_token, s.ingest, s.prompt_pack and s.ui to the app unchanged

try:
    r = client.sessions.result(s.session_id)
except ResultPending:
    ...  # no verdict yet: poll with backoff, or wait for the webhook

# in the webhook handler, with the request's headers and raw body
event = client.webhooks.verify(headers, raw_body, secret="...")
claims = client.results.verify_token(r.result_token)
```

- `sessions.create` takes the fields of `POST /v1/sessions` as keyword arguments and returns a `Session`; `sessions.result` returns a `Result`. Both are dataclasses with the API's fields; timestamps stay the strings the API sends.
- A problem response raises `ApiError` with its `status`, `code` and `request_id`; `ResultPending` is the `result_pending` case. 429 and 5xx responses are retried twice, with backoff that honours `Retry-After` and the same `Idempotency-Key` (the `idempotency_key` given, or one generated per call); nothing else is retried. Each attempt times out after 30 s.
- `webhooks.verify` takes the request headers, the raw body exactly as received and the endpoint's secret. It returns a `WebhookEvent`, or raises `VerificationError` when `Zakadi-Webhook-Signature` does not match or the timestamp is older than 300 s.
- `results.verify_token` checks a `result_token` (ES256) against the API's JWKS, which it caches and refetches once for an unknown `kid`, and returns its claims; any other token, or an expired one, raises `VerificationError`.
- Tokens stay out of the package's log records (logger `zakadi`) and out of the `repr` of every returned object. Do not log them either.

The API's other operations follow in a later release, with the layer generated from the API's OpenAPI document.

Links: https://zakadi.dev (documentation), https://github.com/zakadihq/zakadi-python (source).

## Licence

Zakadi SDKs and client libraries are open source under the Apache License 2.0 (see `LICENSE`; the `NOTICE` file reserves the Zakadi trademarks). They are clients for the Zakadi service, which is proprietary; using it requires an account and acceptance of the Zakadi Terms of Service. Zakadi and the Zakadi logo are trademarks and are not covered by the Apache licence.
