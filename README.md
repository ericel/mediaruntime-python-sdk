# MediaRuntime Python SDK

Official synchronous Python client for the MediaRuntime asynchronous media API.

Status: `0.1.0` release candidate. Publishing begins after PyPI ownership and GitHub
trusted publishing are configured.

## Install

```bash
pip install mediaruntime
```

Set `MEDIARUNTIME_API_KEY`; the production API URL is built in.

```python
from mediaruntime import MediaRuntime

media = MediaRuntime()
job = media.jobs.create(
    source="./video.mp4",
    outputs=[{"type": "mp4", "preset": "mp4_720p_h264_aac"}],
    moderation={"enabled": True, "mode": "report"},
    idempotency_key="video:vid_123:v1",
)

# Useful for scripts/tests. Prefer signed webhooks in production.
result = job.wait(timeout=300)
moderation = media.jobs.get_moderation(result.id)
print(result.bundle.get("download_url"), moderation.flagged_checks)
```

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
