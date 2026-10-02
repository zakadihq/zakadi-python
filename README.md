# zakadi

Zakadi face-liveness API client for Python. Zakadi is an active face liveness check delivered as a short automated video call; relying parties create sessions and read verdicts server to server.

Pre-release. `Zakadi` is the server-side client, for Python 3.10 or newer: it calls the API's operations, verifies webhook deliveries and verifies result tokens. The package also ships the shared protocol constants (session states and statuses, decisions and bands, SDK error codes, terminal states, close codes, challenge kinds, webhook event types) with type annotations.

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

page = client.sessions.list(user_ref="cust-88213", status="passed", limit=20)
client.sessions.purge(s.session_id)  # None: the API answers 202 without a body
```

- `sessions.create` takes the fields of `POST /v1/sessions` as keyword arguments and returns a `Session`; `sessions.result` returns a `Result`. Both are dataclasses with the API's fields; timestamps stay the strings the API sends.
- A problem response raises `ApiError` with its `status`, `code` and `request_id`; `ResultPending` is the `result_pending` case. 429 and 5xx responses to an idempotent call (every GET, PUT and DELETE, and `sessions.create` and `webhooks.create`, which carry an `Idempotency-Key`) are retried twice, with backoff that honours `Retry-After` and the same `Idempotency-Key` (the `idempotency_key` given, or one generated per call); `sessions.cancel` and `subjects.purge` are never retried, and nothing else is. Each attempt times out after 30 s.
- `webhooks.verify` takes the request headers, the raw body exactly as received and the endpoint's secret. It returns a `WebhookEvent`, or raises `VerificationError` when `Zakadi-Webhook-Signature` does not match or the timestamp is older than 300 s.
- `results.verify_token` checks a `result_token` (ES256) against the API's JWKS, which it fetches without the API key, caches, and refetches for an unknown `kid` at most once per 60 s, and returns its claims; any other token, or an expired one, raises `VerificationError`, as does an unknown `kid` inside those 60 s, without a request.
- Tokens stay out of the package's log records (logger `zakadi`) and out of the `repr` of every returned object. Do not log them either.

## Operations

The other operations return the API's JSON body unchanged, a `dict` typed with the `TypedDict` of `zakadi.models` that the table names, or `None` for an answer without a body. Path parameters are positional and percent-encoded; query and body members are keyword arguments under the API's names, `from_` for `from`, and a `None` argument is left out; `tenants.update_policy` takes the whole policy as one argument.

| Method | Operation | Returns |
| --- | --- | --- |
| `sessions.get(session_id)` | `GET /v1/sessions/{id}` | `Session` |
| `sessions.list(user_ref=, status=, from_=, to=, cursor=, limit=)` | `GET /v1/sessions` | `SessionPage` |
| `sessions.cancel(session_id)` | `POST /v1/sessions/{id}/cancel`, never retried | `Session` |
| `sessions.evidence(session_id)` | `GET /v1/sessions/{id}/evidence` | `SessionEvidence` |
| `sessions.purge(session_id)` | `DELETE /v1/sessions/{id}` | `None` (202) |
| `subjects.purge(user_ref=)` | `POST /v1/subjects/purge`, never retried | `Job` |
| `jobs.get(job_id)` | `GET /v1/jobs/{id}` | `Job` |
| `webhooks.create(url=, events=, secret=, active=None, idempotency_key=None)` | `POST /v1/webhooks` | `Webhook` |
| `webhooks.list()` | `GET /v1/webhooks` | `WebhookList` |
| `webhooks.get(webhook_id)` | `GET /v1/webhooks/{id}` | `Webhook` |
| `webhooks.update(webhook_id, url=, events=, active=, secret=None)` | `PUT /v1/webhooks/{id}` | `Webhook` |
| `webhooks.delete(webhook_id)` | `DELETE /v1/webhooks/{id}` | `None` (204) |
| `webhooks.deliveries(webhook_id, cursor=, limit=)` | `GET /v1/webhooks/{id}/deliveries` | `WebhookDeliveryPage` |
| `tenants.policy(tenant_id)` | `GET /v1/tenants/{id}/policy` | `Policy` |
| `tenants.update_policy(tenant_id, policy)` | `PUT /v1/tenants/{id}/policy` | `Policy` |
| `tenants.usage(tenant_id, from_=, to=)` | `GET /v1/tenants/{id}/usage` | `Usage` |

The SDK-facing and health operations have no method. In `zakadi.models`, enumerations are `Literal` types and timestamps, dates, URLs and UUIDs stay strings; `typing-extensions` is the one dependency it adds.

## The OpenAPI document

`zakadi.models` is generated from `openapi/openapi.yaml`, a copy of `api/openapi.yaml` of the Zakadi server, the document the API is built from. `scripts/fetch-openapi.sh` pins the copy by the server commit and the SHA-256 of its bytes:

- `sh scripts/fetch-openapi.sh --check` verifies the committed copy against the pin, offline.
- `sh scripts/fetch-openapi.sh` writes the copy from the pinned commit through `gh api`, with an account that can read the server repository, and refuses any other bytes.
- `uv run --frozen datamodel-codegen` writes `src/zakadi/models.py` from the copy, with the settings under `[tool.datamodel-codegen]` in `pyproject.toml`; with `--check` it fails when the file would change instead.

The git hooks and CI run both checks. A new revision of the document is a change of its own: the commit and the SHA-256 in the script move together, then the copy is fetched and the models regenerated. The generator (`datamodel-code-generator` 0.83.0) is pinned as well, and Dependabot leaves it alone, since a new version can change the generated code.

Links: https://zakadi.dev (documentation), https://github.com/zakadihq/zakadi-python (source).

## Licence

Zakadi SDKs and client libraries are open source under the Apache License 2.0 (see `LICENSE`; the `NOTICE` file reserves the Zakadi trademarks). They are clients for the Zakadi service, which is proprietary; using it requires an account and acceptance of the Zakadi Terms of Service. Zakadi and the Zakadi logo are trademarks and are not covered by the Apache licence. The copy of the API's OpenAPI document under `openapi/` and the code generated from it are published under the same Apache License 2.0.
