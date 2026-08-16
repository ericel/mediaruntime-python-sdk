# Changelog

All notable changes to this project are documented here.

## 0.2.5 - 2026-08-16

- Protect every `jobs.create()` invocation with one opaque generated UUID when the caller
  omits `idempotency_key`, reusing it only for that call's bounded transport retries.
- Retry a typed idempotency-in-progress `409` during keyed submission while keeping a
  different-body `422` conflict terminal.
- Preserve explicit stable keys for durable business-level deduplication across calls.

## 0.2.4 - 2026-08-16

- Vendor only the filtered public OpenAPI surface in repository conformance fixtures.
- Remove private upstream repository naming from public maintenance documentation.

## 0.2.3 - 2026-08-16

- Surface gateway-owned `code`, `retryable`, and `request_id` fields on API errors.
- Preserve normalized `details` separately from the complete legacy-compatible response body.
- Pin request correlation and error classification in the shared conformance fixture.

## 0.2.2 - 2026-08-16

- Send canonical `source` for both scalar and batch job submissions; legacy `file_url`
  acceptance remains a gateway compatibility concern.
- Add a checked-in gateway OpenAPI/conformance snapshot with deterministic sync and CI
  drift checks.
- Treat batch `PARTIAL` as terminal when polling with `job.wait()`.

## 0.2.1 - 2026-08-16

- Send canonical `source` for every batch item while retaining transparent local uploads.
- Document the batch input surface and canonical ZIP bundle workflow.

## 0.2.0 - 2026-08-16

- Add typed support for the six frozen output aliases.
- Expose gateway-resolved output tuples and the required tier on job receipts.
- Expose the live output-alias catalog through capabilities.

## 0.1.1 - 2026-08-15

- Correct the public package status after the initial trusted-publishing release.

## 0.1.0 - 2026-08-15

- Add the synchronous `MediaRuntime` client with jobs, uploads, capabilities, and
  account watermark-logo resources.
- Add local-file uploads through signed targets without forwarding API credentials.
- Add bounded retries for safe requests and caller-keyed job submissions.
- Add exact-byte webhook verification and optional Flask, FastAPI, and Django adapters.
- Ship inline typing and support Python 3.10 through 3.13.
