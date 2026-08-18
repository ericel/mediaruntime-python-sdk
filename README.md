# MediaRuntime Python SDK

Official synchronous Python client for the MediaRuntime asynchronous media API.

Status: production/stable `1.0.0`, published on PyPI with GitHub trusted publishing.

The documented `1.x` public API follows semantic versioning. Breaking changes to public
imports, arguments, exceptions, or documented response projections require a new major
version; compatible fields and capabilities may be added in minor releases.

## Install

```bash
pip install mediaruntime
```

Set `MEDIARUNTIME_API_KEY`; the production API URL is built in. Pass the server-held key
explicitly when you want the credential source to be visible in application code.

```python
import os

from mediaruntime import MediaRuntime

media = MediaRuntime(api_key=os.environ["MEDIARUNTIME_API_KEY"])
job = media.jobs.create(
    source="./video.mp4",
    outputs=["video.web"],
    idempotency_key="video:vid_123:v1",
)

# Polling is convenient for scripts, tests, and first-run verification.
result = job.wait(timeout=300)
bundle_url = result.bundle.get("download_url")
if result.status != "COMPLETED" or not bundle_url:
    raise RuntimeError(f"MediaRuntime job ended with {result.status}")
print(bundle_url)
```

`bundle_url` is a short-lived URL for the canonical ZIP containing every requested
deliverable. One job can place a video, poster, subtitles, multiple renditions, or a
complete HLS directory tree in that bundle; the SDK does not model those files as
separate delivery URLs.

In production, persist `job.id` and complete the workflow from the signed terminal
webhook sent to the destination configured under Account → Webhooks. Redeem
`delivery.bundle.download.url` from that event for the same ZIP. A job submission does
not supply or override the webhook URL.

`MediaRuntime()` without arguments is equivalent: it reads `MEDIARUNTIME_API_KEY`
automatically. Never put the key in frontend code or commit its literal value.

Aliases are frozen gateway contracts: `video.web`, `video.streaming`, `video.social`,
`audio.web`, `audio.transcription`, and `image.web`. The gateway materializes them before
validation, estimation, billing, and persistence. Explicit `{ "type": ..., "preset": ... }`
output dictionaries remain supported and may be mixed with aliases.

HTTP(S) and `gs://` sources are submitted directly. Other strings and `pathlib.Path`
instances are treated as local files and uploaded through MediaRuntime's signed upload
flow.

## Batch inputs

Use `source` on every batch item. Each value accepts the same HTTP(S), `gs://`, local-path,
or `pathlib.Path` forms as a single job; the SDK uploads local files before submission.

```python
batch = media.jobs.create(
    inputs=[
        {"source": "https://cdn.example.com/a.mp4", "input_id": "asset-a"},
        {"source": "./b.mp4", "input_id": "asset-b", "metadata": {"position": 1}},
    ],
    outputs=["video.web"],
)
```

## Moderation

Choose observational `report` moderation or fail-closed `block` enforcement when creating
a visual-media job, then retrieve its result after completion. In block mode, `review` or
`block` ends the job as `REJECTED` before transcoding; `allow` continues.

```python
job = media.jobs.create(
    source="https://cdn.example.com/photo.jpg",
    outputs=["image.web"],
    moderation={
        "enabled": True,
        "mode": "report",
        "checks": ["sexual", "violence", "dangerous"],
    },
    idempotency_key="image:photo_123:v1",
)

result = job.wait()
moderation = media.jobs.get_moderation(result.id)
print(result.status, moderation.verdict, moderation.flagged_checks)
```

Explicit output mappings support MPEG-DASH and VP9/WebM:

```python
outputs = [
    {"type": "dash", "preset": "dash_ladder_v1"},
    {"type": "webm", "preset": "webm_vp9_1080p"},
]
```

`media.capabilities.retrieve()` includes the gateway's full preset catalog and feature
contracts, including smart-crop semantics and moderation enforcement modes.

## Verify webhooks

```python
event = media.webhooks.verify(raw_body, request.headers)
print(event.id, event.job_id, event.status)
```

`media.webhooks.flask(handler)`, `fastapi(handler)`, and `django(handler)` provide optional
framework adapters without making those frameworks package dependencies. Persist and
deduplicate `event.id` in your own datastore before acknowledging a delivery.

## Error handling

Every gateway response carries `X-Request-Id`. API exceptions expose the same correlation
ID together with the gateway-owned code and retry classification:

```python
from mediaruntime import MediaRuntimeAPIError

try:
    media.jobs.get("job_123")
except MediaRuntimeAPIError as error:
    print(error.code, error.status, error.retryable, error.request_id, error.details)
```

`response_body` retains the complete compatibility response. Treat `retryable` as a
transport classification. Every `jobs.create()` call uses one opaque, invocation-scoped
`Idempotency-Key` for its own bounded retries, including a response lost after gateway
acceptance. That generated key exists only for the live call; a later call receives a new
one. Continue to pass a stable `idempotency_key` when the same business operation may be
attempted after a process restart, queue redelivery, or from another machine.

See [the software design document](docs/PYTHON_SDK_SDD.md) for boundaries, retry safety,
security behavior, compatibility, and release gates.
