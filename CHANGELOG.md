# Changelog

All notable changes to this project are documented here.

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
