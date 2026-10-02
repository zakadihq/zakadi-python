# Changelog

All notable changes to this package are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `Zakadi` client: `sessions.create`, `sessions.result`, `webhooks.verify` and
  `results.verify_token`, returning `Session`, `Result`, `WebhookEvent` and the token
  claims, raising `ApiError`, `ResultPending` and `VerificationError`, and retrying 429
  and 5xx responses. New dependency: `cryptography`.
- JWKS refetch floor: `results.verify_token` refetches the JWKS for an unknown `kid`
  at most once per 60 s, failed requests included, and inside that floor raises
  `VerificationError` without a request. Concurrent verifications share one request:
  calls that waited on a failed first fetch re-raise its error without a request of
  their own. A failed refetch keeps the cached keys.
- The API key goes to `/v1/` paths only: the request for the public JWKS
  (`/.well-known/jwks.json`) carries no `Authorization` header.
- `zakadi.models`: `TypedDict` and `Literal` types generated from the API's OpenAPI
  document, whose copy, `openapi/openapi.yaml` (also in the sdist), is pinned by
  commit and SHA-256. New dependency: `typing-extensions`.
- `Result.superseded`: true on a verdict that replaced one written after a verdict
  timeout.

### Changed

- CI: every `astral-sh/setup-uv` step pins uv 0.11.32, the version the workstations, the hooks and the images run; the runner had taken the newest release (0.12.21) on its own.
- Licence: Apache License 2.0 with a NOTICE file (0.0.1 shipped with an
  all-rights-reserved placeholder).

## [0.0.1] - 2026-09-23

### Added

- Initial release: shared protocol constants of the Zakadi protocol (zakadi.v1) with
  type annotations. No client yet.

[Unreleased]: https://github.com/zakadihq/zakadi-python/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/zakadihq/zakadi-python/releases/tag/v0.0.1
