# MediaRuntime Python SDK — Software Design Document

Status: implemented and published as stable `0.2.3`

Distribution/module: `mediaruntime`

Repository: `ericel/mediaruntime-python-sdk`

Runtime: Python 3.10+

## Purpose

The Python SDK provides feature parity with `@mediaruntime/node` while remaining
idiomatic for scripts, services, notebooks, and reconciliation jobs. Gateway validation,
billing, tier, preset, and compatibility policy remain server-owned.

## Public surface

```text
MediaRuntime
├── jobs.create/get/list/wait/get_moderation/get_media_report/retry_webhook
├── uploads.create_target/upload_file
├── capabilities.retrieve
├── watermark_logo.create_upload_target/confirm/upload
└── webhooks.verify/flask/fastapi/django
```

The first release is synchronous. An async client is additive follow-up work.

## Configuration

`MediaRuntime()` reads `MEDIARUNTIME_API_KEY` and `MEDIARUNTIME_WEBHOOK_SECRET`. The API
base defaults to `https://mediaruntime.com`; `base_url` or `MEDIARUNTIME_API_URL` exists
only for local, staging, proxy, and test environments.

## Job and upload behavior

`jobs.create()` accepts exactly one of `source` or `inputs`. HTTP(S) and `gs://` values are
passed through. Local paths obtain a signed target through `POST /v1/upload-url`, upload
with every returned header, and submit the opaque `file_uri`. Both scalar and batch wire
requests use canonical `source`; `file_url` is gateway-only legacy compatibility.

`outputs` accepts explicit output dictionaries and the six typed frozen aliases. The SDK
forwards alias strings unchanged; the gateway materializes them before validation,
estimation, billing, and persistence. Job receipts expose `required_tier` and the resolved
alias/type/preset tuples, while `capabilities.retrieve()` exposes the live alias catalog.

The caller controls `idempotency_key`. The SDK never invents one. An unkeyed job submit
is never replayed after an ambiguous network/5xx outcome; a keyed submit may use the
normal bounded retry policy. Safe reads retry `429` and `5xx`. Mutations and signed PUTs
do not retry automatically.

`job.wait()` is for scripts, tests, notebooks, and reconciliation. Production completion
should use signed webhooks.

`MediaRuntimeAPIError` projects the gateway-owned `code`, message, HTTP `status`,
`retryable`, `request_id`, and normalized `details`. `response_body` retains the complete
legacy-compatible response, while typed subclasses continue to distinguish authentication,
authorization, validation, rate-limit, not-found, and idempotency cases.

## Webhook security

Verification uses the exact raw bytes and the `X-Transcoder-Id`,
`X-Transcoder-Timestamp`, and `X-Transcoder-Signature` headers. It parses
`t=<timestamp>,v1=<digest>`, requires both timestamp values to agree, enforces a 300-second
window, computes HMAC-SHA256 over `timestamp + "." + event_id + "." + raw_body`, and uses
`hmac.compare_digest`. JSON is parsed only after authentication.

Flask, FastAPI, and Django helpers read each framework's raw request body and fail closed
with HTTP 401. They do not attempt datastore-level event deduplication.

## Packaging

- `src/` layout, typed public API, and `py.typed` marker.
- `httpx` is the only runtime dependency.
- Wheels and source distributions are built with Hatchling.
- Python 3.10–3.13 are tested.
- PyPI publishing must use trusted publishing; no long-lived token belongs in GitHub.

## Contract conformance

`contracts/v1/openapi.json` and `contracts/v1/conformance.json` are deterministic copies
of the versioned gateway artifacts. SDK CI validates those local files and exercises the
public client against their aliases, source spelling, terminal states, errors, and bundle
delivery examples. The SDK has no runtime dependency on a gateway checkout.

Maintainers refresh or compare the snapshot with `scripts/sync_gateway_contract.py` and
an explicit `--gateway-repo` path. This keeps cross-repository updates intentional and
reproducible.

## Release gates

- Ruff, strict mypy, and pytest pass.
- Wheel and sdist build; Twine validates metadata.
- A fresh virtual environment can import the wheel.
- Tests pin request mapping, retry safety, signed upload headers, polling timeout, webhook
  raw-body sensitivity, replay protection, and framework adapter behavior.
- Package/repository ownership and PyPI trusted publishing are configured.
