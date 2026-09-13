import json

import httpx

from mediaruntime import MediaRuntime


def test_candidate_transcript_can_be_reused_without_rebasing() -> None:
    captured = []
    transcript = [{"start_time_sec": 31, "end_time_sec": 34, "text": "Keep_My Case."}]

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.path == "/v1/jobs/job_plan/clip-candidates"
            return httpx.Response(
                200,
                json={
                    "schema_version": 1,
                    "source_duration_sec": 120,
                    "method": "transcript_heuristics_v1",
                    "transcript_source": "supplied",
                    "transcript": transcript,
                    "candidates": [
                        {
                            "id": "clip_1",
                            "start_time_sec": 30,
                            "duration_sec": 20,
                            "text": "Keep_My Case.",
                            "score": 0.8,
                            "reasons": [],
                        }
                    ],
                },
            )
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"job_id": "job_render", "status": "QUEUED"})

    media = MediaRuntime(
        api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handle))
    )
    plan = media.jobs.get_clip_candidates("job_plan")
    selected = plan.candidates[0]
    media.jobs.create(
        source="https://example.test/episode.mp4",
        outputs=[
            {
                "type": "mp4",
                "preset": "video_clip_v1",
                "clip": {
                    "start_time_sec": selected["start_time_sec"] + 0.5,
                    "duration_sec": selected["duration_sec"],
                    "transcript": plan.transcript,
                    "burn_captions": True,
                },
            }
        ],
    )
    assert captured[0]["outputs"][0]["clip"]["transcript"] == transcript
    assert captured[0]["outputs"][0]["clip"]["start_time_sec"] == 30.5


def valid_plan():
    return {
        "schema_version": 1,
        "source_duration_sec": 120,
        "method": "transcript_heuristics_v1",
        "transcript_source": "supplied",
        "transcript": [{"start_time_sec": 30, "end_time_sec": 35, "text": "Reviewed text."}],
        "candidates": [
            {
                "id": "clip_1",
                "start_time_sec": 30,
                "duration_sec": 20,
                "text": "Reviewed text.",
                "score": 0.8,
                "reasons": [],
            }
        ],
    }


def test_malformed_clip_plans_raise_typed_errors_without_transcript_contents():
    import copy

    import pytest

    from mediaruntime import ValidationError

    cases = [
        {"schema_version": 2},
        {"schema_version": True},
        {"source_duration_sec": 0},
        {"source_duration_sec": "120"},
        {"transcript": None},
        {"candidates": {}},
        {"transcript": [{"start_time_sec": "30", "end_time_sec": 35, "text": "text"}]},
        {"transcript": [{"start_time_sec": 30, "end_time_sec": 29, "text": "text"}]},
        {"transcript": [{"start_time_sec": 30, "end_time_sec": 121, "text": "text"}]},
        {"transcript": [{"start_time_sec": 30, "end_time_sec": 35, "text": "가" * 667}]},
        {"transcript": [{"start_time_sec": 0, "end_time_sec": 1, "text": "x" * 2000}] * 140},
        {"transcript": valid_plan()["transcript"] * 2001},
        {"candidates": valid_plan()["candidates"] * 21},
        {"candidates": [dict(valid_plan()["candidates"][0], duration_sec=100)]},
        {"candidates": [dict(valid_plan()["candidates"][0], reasons=[42])]},
        {"candidates": [dict(valid_plan()["candidates"][0], score=-1)]},
    ]
    for changes in cases:
        report = copy.deepcopy(valid_plan()) | changes
        media = MediaRuntime(
            api_key="test",
            http_client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda _, report=report: httpx.Response(200, json=report)
                )
            ),
        )
        with pytest.raises(ValidationError) as error:
            media.jobs.get_clip_candidates("job_plan")
        assert error.value.code == "invalid_clip_plan"
        assert error.value.status == 502
        assert "Reviewed text" not in str(error.value)


def test_nonfinite_response_numbers_are_not_coerced_into_reusable_plans():
    import pytest

    from mediaruntime import ValidationError

    for raw_number in ("NaN", "Infinity", "-Infinity", "1e999"):
        body = json.dumps(valid_plan()).replace(
            '"source_duration_sec": 120', f'"source_duration_sec": {raw_number}'
        )
        media = MediaRuntime(
            api_key="test",
            http_client=httpx.Client(
                transport=httpx.MockTransport(lambda _, body=body: httpx.Response(200, text=body))
            ),
        )
        with pytest.raises(ValidationError, match="source_duration_sec"):
            media.jobs.get_clip_candidates("job_plan")


def test_empty_candidates_and_rounded_overlapping_cues_remain_valid():
    report = valid_plan()
    report["candidates"] = []
    report["transcript"] = [
        {"start_time_sec": 115, "end_time_sec": 119, "text": "First."},
        {"start_time_sec": 118, "end_time_sec": 120.05, "text": "Second."},
    ]
    report["internal_path"] = "/private/worker"
    media = MediaRuntime(
        api_key="test",
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda _, report=report: httpx.Response(200, json=report))
        ),
    )
    result = media.jobs.get_clip_candidates("job_plan")
    assert result.transcript[1]["end_time_sec"] == 120.05
    assert result.candidates == []
    assert not hasattr(result, "internal_path")
    report["transcript"] = []
    assert media.jobs.get_clip_candidates("job_plan").transcript == []


def test_empty_analysis_reasons_and_older_reports_preserve_transcript():
    for reason in (None, "no_speech", "no_keyword_match", "no_matching_ranges", "source_too_short"):
        report = valid_plan() | {"candidates": [], "empty_reason": reason}
        media = MediaRuntime(
            api_key="test",
            http_client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda _, report=report: httpx.Response(200, json=report)
                )
            ),
        )
        result = media.jobs.get_clip_candidates("job_plan")
        assert result.empty_reason == reason
        assert result.transcript[0]["start_time_sec"] == 30
    report.pop("empty_reason")
    assert media.jobs.get_clip_candidates("job_plan").empty_reason is None


def test_malformed_empty_reasons_raise_typed_errors():
    import pytest

    from mediaruntime import ValidationError

    for reason in ("unknown_reason", "", 0, False, [], {"text": "PRIVATE TRANSCRIPT"}):
        report = valid_plan() | {"candidates": [], "empty_reason": reason}
        media = MediaRuntime(
            api_key="test",
            http_client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda _, report=report: httpx.Response(200, json=report)
                )
            ),
        )
        with pytest.raises(ValidationError) as error:
            media.jobs.get_clip_candidates("job_plan")
        assert error.value.code == "invalid_clip_plan"
        assert error.value.field == "clip_candidates.empty_reason"
        assert "PRIVATE TRANSCRIPT" not in str(error.value)


def test_result_can_still_be_constructed_without_optional_empty_reason():
    from mediaruntime import ClipCandidatesResult

    result = ClipCandidatesResult(1, 12.5, "transcript_heuristics_v1", "supplied", [], [])
    assert result.empty_reason is None
