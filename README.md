# MediaRuntime Python SDK

Official synchronous Python client for the MediaRuntime asynchronous media API.

Status: production/stable `1.3.0`, published on PyPI with GitHub trusted publishing.

The documented `1.x` public API follows semantic versioning. Breaking changes to public
imports, arguments, exceptions, or documented response projections require a new major
version; compatible fields and capabilities may be added in minor releases.

## Install

```bash
pip install mediaruntime
```

For a complete clone-and-run project, see the [MediaRuntime Python quickstart](https://github.com/ericel/mediaruntime-quickstarts/tree/main/python). The shared repository also includes webhook receivers, Postman guidance, and equivalent Node.js, Go, and PHP examples.

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

## Hosted recipes

Hosted recipes are immutable, account-scoped versions of a complete outputs, moderation,
and watermark policy. They let several services and teammates run the same policy without
copying request configuration.

```python
available = media.recipes.list()

created = media.recipes.create(
    name="team-video",
    description="Default web playback policy",
    template={"outputs": ["video.web"]},
)

job = media.jobs.create(
    source="./launch.mp4",
    recipe=created.reference,  # team-video@1
    metadata={"asset_id": "launch-01"},
)
```

Use `media.recipes.get(name, version=...)`, `create_version(...)`, and `archive(name)`
to manage custom policies. Versions are immutable and optimistically locked. Built-ins
`web-video@1`, `social-video@1`, and `ai-transcription@1` are always available. A recipe
job cannot also supply inline `outputs`, `moderation`, or `watermark`; the gateway resolves
it before validation, estimation, billing, idempotency, and dispatch.

HTTP(S) and `gs://` sources are submitted directly. Other strings and `pathlib.Path`
instances are treated as local files and uploaded through MediaRuntime's signed upload
flow.

## Hosted Sticker Runtime

Use `media.stickers` to configure application collections and access enabled hosted
packs. Collection configuration uses the same server-held API key as the rest of the
SDK and does not purchase or activate a pack.

```python
collection = media.stickers.create_collection(
    name="Support chat",
    description="Approved stickers available to support agents",
)

# The pack must already have an active Hosted Sticker Runtime activation.
media.stickers.enable_pack(collection.collection_id, "sage-summer-v1")

# Binding the collection once prevents accidental cross-collection searches.
stickers = media.stickers.collection(collection.collection_id)
matches = stickers.search("beach", animated=True, limit=12)
if not matches.items:
    raise RuntimeError("No matching sticker is enabled")

selected = matches.items[0]
asset = stickers.resolve(selected.sticker_id, "small_160")
print(asset.url)  # Five-minute, generation-pinned private delivery URL.
```

The collection-bound client also provides `list_packs()`, `typeahead()`, and `get()`.
Workspace management is available through `list_collections()`, `get_collection()`,
`update_collection()`, `archive_collection()`, `list_pack_bindings()`,
`add_activation()`, `enable_pack()`, and `disable_pack()`. Disabling a pack removes it
from new discovery while the gateway preserves eligible historical asset resolution.
Read current pooled limits and usage with `media.stickers.usage()`.

API keys belong only on trusted servers. If a browser or mobile application must call
runtime reads directly, mint a short-lived, collection-scoped token on your server and
return only that token to the client:

```python
token = media.stickers.create_client_token(
    collection_id=collection.collection_id,
    expires_in_seconds=900,
    scopes=["stickers:search", "stickers:read", "assets:resolve"],
)

# This resource sends Authorization: Bearer and never sends the workspace API key.
client_stickers = media.stickers.collection(
    collection.collection_id,
    client_token=token.access_token,
)
result = client_stickers.search("hello")
```

Scoped tokens cannot alter collections or read workspace usage. The gateway rechecks
the parent API key on every token-authenticated call, so revoking the key invalidates
its outstanding client tokens. Signed asset URLs authorize at most the reported byte
count; authoritative delivered-byte accounting remains a storage/CDN concern.

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

## Animated WebP and APNG

Animated images use `type: "image"` with a timeline-specific Premium preset. The Python
SDK accepts the gateway request fields directly:

```python
job = media.jobs.create(
    source="./launch.mp4",
    outputs=[
        {
            "type": "image",
            "preset": "image_animated_webp_v1",
            "animation": {
                "width": 720,
                "fps": 15,
                "start_time": 0,
                "duration": 6,
                "loop": 0,
                "quality": 80,
            },
        }
    ],
)
```

Use `image_animated_apng_v1` for lossless animated PNG. `loop: 0` repeats forever;
`quality` applies only to WebP. Watermarking these animation presets is rejected until
that combination is explicitly supported.

## BlurHash, ThumbHash, and LQIP

The Standard `image_placeholders_v1` preset accepts a still image or video and returns
`placeholders.json` plus a byte-bounded `lqip.webp` in the canonical ZIP bundle:

```python
job = media.jobs.create(
    source="./product-photo.png",
    outputs=[
        {
            "type": "image",
            "preset": "image_placeholders_v1",
            "placeholders": {
                "max_dimension": 32,
                "source_time_sec": 0,
                "lqip_quality": 50,
                "lqip_max_bytes": 4096,
            },
        }
    ],
)
```

`placeholders.json` contains standard BlurHash and base64 ThumbHash values, explicit
source and placeholder dimensions, source format, requested frame time, and an
alpha-aware dominant colour. `source_time_sec` defaults to the first frame at `0`; no
representative-frame selection is performed. The job
fails instead of silently exceeding `lqip_max_bytes`; watermarking this preset is
rejected.

## Audiograms

Compose timed audio with supplied artwork, a generated waveform, and optional supplied
captions using the Premium `audiogram_v1` preset:

```python
job = media.jobs.create(
    source="./episode.mp3",
    outputs=[
        {
            "type": "social",
            "preset": "audiogram_v1",
            "audiogram": {
                "artwork_source": "https://cdn.example.com/podcast/cover.png",
                "captions_source": "https://cdn.example.com/podcast/episode.vtt",
                "burn_captions": True,
                "layout": "square",
                "artwork_fit": "blurred_background",
                "background_color": "#101827",
                "waveform_color": "#5B5CFF",
                "waveform_gain": 2,
                "caption_position": "bottom",
                "caption_font_scale": 1,
                "normalize_audio": True,
                "loudness_target_lufs": -16,
                "duration_sec": 60,
                "fps": 30,
            },
        }
    ],
)
```

Artwork must be PNG, JPEG, or WebP up to 10 MB; captions must be UTF-8 SRT or VTT up to
2 MB. Artwork can be contained, covered, or preserved over a blurred fill. Waveforms and
captions use separate regions in a reserved high-contrast safe band; `top` and `bottom`
select the caption strip and never place text over caller artwork. Multi-line cues scale down
adaptively, and the caption-free poster is sampled after waveform activity begins. Loudness
normalization is optional and reports its target plus measured input/output values. The
ZIP contains `audiogram.mp4`, a caption-free `poster.jpg`, `audiogram.json`, and
`audiogram.waveform.json`. Account watermarking and speech-generated subtitles cannot be
combined with this preset in v1.

## Composite video contact sheets

Use the Standard `contact_sheet_v1` preset to produce numbered review grids plus
`contact_sheet.json`, which maps every tile to its exact source timestamp:

```python
job = media.jobs.create(
    source="./interview.mp4",
    outputs=[
        {
            "type": "frames",
            "preset": "contact_sheet_v1",
            "contact_sheet": {
                "columns": 5,
                "rows": 4,
                "tile_width": 240,
                "tile_height": 135,
                "interval_sec": 12,
                "start_time_sec": 0,
                "duration_sec": 0,  # remaining video
                "max_sheets": 3,
                "format": "jpg",
                "quality": 80,
            },
        }
    ],
)
```

Billing is one flat processing unit per produced composite sheet. Watermarking this
preset is rejected. `quality` applies to JPG and WebP; PNG is lossless.

For JPG and WebP renditions, `max_bytes` is a hard final-file ceiling. The engine searches
between `quality` and `min_quality`, verifies the encoded file, and fails instead of
returning an oversized artifact:

```python
job = media.jobs.create(
    source="./product-photo.png",
    outputs=[
        {
            "type": "image",
            "preset": "image_multi_v1",
            "images": [
                {
                    "width": 1280,
                    "height": 720,
                    "mode": "cover",
                    "format": "webp",
                    "quality": 86,
                    "max_bytes": 200_000,
                    "min_quality": 35,
                }
            ],
        }
    ],
)
```

The ZIP includes `image_size_limits.json` with the selected quality, final byte count,
and bounded attempt history. PNG and AVIF do not currently accept `max_bytes`.

## Privacy redaction

Privacy redaction is an explicit Premium Preview for still-image inputs and image outputs.
Video and animated-image requests are rejected before billing and execution.

```python
job = media.jobs.create(
    source="./team-photo.jpg",
    outputs=[
        {
            "type": "image",
            "preset": "image_multi_v1",
            "images": [
                {
                    "width": 1280,
                    "height": 720,
                    "mode": "fit",
                    "format": "png",
                    "quality": 80,
                }
            ],
            "privacy_redaction": {
                "detectors": ["face", "license_plate", "text"],
                "style": "blur",
                "failure_mode": "fail_closed",
                "min_confidence": 0.65,
                "sample_interval_sec": 0.2,
                "max_frames": 1800,
                "box_padding_ratio": 0.15,
                "privacy_strength": "strong",
                "pixel_block_size": 24,
                "include_debug_observations": False,
            },
        }
    ],
)
```

Use `report_only` only when an unsafe or incomplete image is acceptable for review.
`fail_closed` stops on detector failure, unresolved ambiguity, bounded-limit truncation,
or a residual that remediation cannot eliminate. Recognizable residuals under blur or
pixelation may be escalated to bounded opaque masks and verified again. The ZIP includes
the redacted image and `privacy_redaction.json` schema v3. Public metadata reports stable
detector categories, counts, verification outcomes, and ZIP-relative
`report_bundle_path` and `output_bundle_paths`; it does not expose detector vendors, model
identities, model or worker paths, bucket names, or raw OCR text. Automated recall is not
exhaustive, so `coverage_verified` remains false and human review is required. Per-sample
observations are included only when
`include_debug_observations` is true.

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

For an actionable, versioned delivery verdict, request the compatibility sidecar and
read it directly after completion (it also remains in the ZIP bundle):

```python
job = media.jobs.create(
    source="https://cdn.example.com/video.webm",
    outputs=[{"type": "image", "preset": "compatibility_report_v1"}],
)
result = job.wait()
compatibility = media.jobs.get_compatibility_report(result.id)
print(compatibility.report["profiles"] if compatibility.report else None)
```

To extract QR codes and barcodes from an image, sampled video frames, or an audio
file's embedded cover artwork, request `code_detect_v1` and read the report:

```python
job = media.jobs.create(
    source="./label.png",
    outputs=[{"type": "frames", "preset": "code_detect_v1"}],
)
job = media.jobs.wait(job.id)
codes = media.jobs.get_code_detections(job.id)
print(codes.report["detections"] if codes.report else [])
```

The engine samples the first visual frame and then every 10 seconds, up to 12
frames and 16 unique codes per frame. Plain audio without embedded artwork is
rejected. Decoded values are untrusted input: render them as text and never
automatically follow a detected URL.

The five named profiles are conservative, versioned guidance rather than exhaustive
certification of every browser, device, editor, or social platform version.

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
