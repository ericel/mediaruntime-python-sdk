# MediaRuntime Python SDK

Official synchronous Python client for the MediaRuntime asynchronous media API.

Status: stable `0.2.0`, published on PyPI with GitHub trusted publishing.

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
    moderation={"enabled": True, "mode": "report"},
    idempotency_key="video:vid_123:v1",
)

# Useful for scripts/tests. Prefer signed webhooks in production.
result = job.wait(timeout=300)
moderation = media.jobs.get_moderation(result.id)
print(result.bundle.get("download_url"), moderation.flagged_checks)
```

`MediaRuntime()` without arguments is equivalent: it reads `MEDIARUNTIME_API_KEY`
automatically. Never put the key in frontend code or commit its literal value.

Aliases are frozen gateway contracts: `video.web`, `video.streaming`, `video.social`,
`audio.web`, `audio.transcription`, and `image.web`. The gateway materializes them before
validation, estimation, billing, and persistence. Explicit `{ "type": ..., "preset": ... }`
output dictionaries remain supported and may be mixed with aliases.

HTTP(S) and `gs://` sources are submitted directly. Other strings and `pathlib.Path`
instances are treated as local files and uploaded through MediaRuntime's signed upload
flow.

## Verify webhooks

```python
event = media.webhooks.verify(raw_body, request.headers)
print(event.id, event.job_id, event.status)
```

`media.webhooks.flask(handler)`, `fastapi(handler)`, and `django(handler)` provide optional
framework adapters without making those frameworks package dependencies. Persist and
deduplicate `event.id` in your own datastore before acknowledging a delivery.

See [the software design document](docs/PYTHON_SDK_SDD.md) for boundaries, retry safety,
security behavior, compatibility, and release gates.
