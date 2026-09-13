# Assisted clipping

Requires SDK `1.4.0` or newer and the matching deployed gateway/engine. Confirm
that the API capability catalog includes both clipping presets before submitting jobs.

```python
from mediaruntime import MediaRuntime

media = MediaRuntime()  # Uses MEDIARUNTIME_API_KEY.
source = "https://your-cdn.example/episode.mp4"
analysis = media.jobs.create(
    source=source,
    outputs=[
        {
            "type": "frames",
            "preset": "clip_candidates_v1",
            "clip_analysis": {"min_duration_sec": 15, "max_duration_sec": 60, "max_candidates": 5},
        }
    ],
)
if analysis.wait().status != "COMPLETED":
    raise RuntimeError("Analysis did not complete")
plan = media.jobs.get_clip_candidates(analysis.id)
if not plan.candidates:
    print("No suggestions:", plan.empty_reason or "No reason in this older report")
    # Stop this automatic render path; the transcript remains usable for manual clips.
    raise SystemExit(0)

# Show candidates for review before selecting one. Scores are transcript heuristics.
selected = plan.candidates[0]
start = selected["start_time_sec"]
duration = selected["duration_sec"]
render = media.jobs.create(
    source=source,
    outputs=[
        {
            "type": "mp4",
            "preset": "video_clip_v1",
            "clip": {
                "start_time_sec": start,
                "duration_sec": duration,
                "layout": "vertical_blur",
                "burn_captions": True,
                # Preserve SOURCE times; the engine rebases them to the rendered clip.
                "transcript": [
                    cue
                    for cue in plan.transcript
                    if cue["end_time_sec"] > start and cue["start_time_sec"] < start + duration
                ],
            },
        }
    ],
)
result = render.wait()
if result.status != "COMPLETED":
    raise RuntimeError(f"Render {result.status}")
print(result.bundle.get("download_url"))  # Short-lived URL for the complete ZIP.
```

Analysis uses the existing Whisper model if no transcript is supplied. Supplied
`clip_analysis.transcript` skips transcription. Rendering is a separate Standard job
and never reruns analysis. Candidate analysis remains Premium. Retain the original
source reference with your plan; all transcript times refer to that source.

The render bundle contains an H.264/AAC clip, a poster and overlapping SRT/VTT captions.
Use `layout: "original"` to preserve framing. Renders last 0.1–300 seconds; candidate
duration bounds are 1–300 seconds. Captions have segment timing, and blur-fill uses no
speaker tracking or new ML model.

Standard renders cap original framing at a 1920-pixel long edge and 30 fps. Vertical
blur-fill uses 720×1280 at up to 30 fps.

## Manual clips and caption reuse

A manual `video_clip_v1` output needs only a source, a nonnegative start, and a
0.1–300 second duration fully inside the source. It does not run Whisper. Captions
are optional: set burn captions only when supplying overlapping transcript segments.
Supplied transcripts produce SRT/VTT sidecars even when burn captions is false.

Candidate analysis automatically uses the existing Whisper model when its transcript
is absent or empty. A nonempty supplied transcript skips Whisper, but analysis still
requires Premium processing. The SDK accepts parsed segment arrays; it does not load
SRT/VTT files or cloud transcript paths into those arrays automatically. All timestamps
must refer to the original source, not the trimmed clip, and the same source must be
used for analysis and render. Do not rebase cues before submission.

The public Sandbox is limited to its enabled presets and fixtures; Premium candidate
analysis is unavailable there. Use an authorized workspace/API key for analysis.

## Empty analysis results

An empty candidates array is a successful analysis outcome, not a failed render.
`empty_reason` explains it when available; older reports return `None`.

| Reason | Meaning and next step |
| --- | --- |
| `no_speech` | No usable spoken transcript was found. Choose a manual range or supply a transcript. |
| `no_keyword_match` | No transcript passages matched the keywords. Change/remove keywords. |
| `no_matching_ranges` | Transcript passages did not satisfy the requested ranges. Adjust duration bounds. |
| `source_too_short` | The minimum exceeded source duration. Lower it; current preflight rejects this before processing. |

A nonempty transcript can still caption a manual clip even when no suggestions match.
Keep the report source reference alongside it. Treat ranking scores as transcript
heuristics, not predictions of virality or engagement.
