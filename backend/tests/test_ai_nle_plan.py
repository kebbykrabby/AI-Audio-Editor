"""Integration tests for POST /api/assets/{id}/ai/plan (NLE Phase 2).

Uses FakeLLMProvider so no real LLM call happens. Confirms:
- Happy path: prompt → completed op with valid steps in result
- Selection plumbing: passing a selection lands in the system prompt context
  (via the LlmPlanResponse the fake provider returns + manual inspection)
- Validation marks invalid params without dropping them
- Empty plan + final_response (ambiguity path) survives end-to-end
- Cross-user IDOR (404 on both POST and poll)
- ASSET_NOT_READY short-circuit
- Oversize duration → 422 AI_INPUT_TOO_LONG
- Transcript cache shared with filler / profanity detection
"""
from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import drain_jobs_async


pytestmark = pytest.mark.asyncio


def _install_fake_llm(response):
    from app.providers.fake_llm import FakeLLMProvider
    from app.services import nle_service

    nle_service._llm_provider = FakeLLMProvider(response=response)


def _install_fake_transcript():
    """Make sure the worker's transcription side also runs on the fake provider
    (default in tests, but tests that previously injected a Whisper fake may
    have left state)."""
    from app.providers.fake import FakeTranscriptionProvider
    from app.providers.transcription import TranscribedWord, WordLevelTranscript
    from app.services import ai_service

    ai_service._provider = FakeTranscriptionProvider(
        transcript=WordLevelTranscript(
            language="en",
            duration_sec=2.0,
            words=[
                TranscribedWord(text="hello", start=0.0, end=0.4),
                TranscribedWord(text="world", start=0.5, end=0.9),
            ],
            model_version="fake-v1",
            cost_usd=0.0,
        ),
    )


def _trim_then_fade_response():
    from app.providers.fake_llm import make_plan_response
    return make_plan_response(
        tool_calls=[
            ("trim", {"start_sec": 0.0, "end_sec": 1.5}),
            ("fade_out", {"duration_sec": 0.3, "curve": "linear"}),
        ],
        final_response="Trimming and fading.",
        model_version="fake-llm-v1",
        cost_usd=0.0,
    )


async def _upload_and_ready(client, stub_broker, user, wav_path: Path) -> str:
    with open(wav_path, "rb") as f:
        res = await client.post(
            "/api/assets/upload",
            headers=user["headers"],
            files={"file": (wav_path.name, f, "audio/wav")},
        )
    assert res.status_code == 202
    await drain_jobs_async(stub_broker)
    return res.json()["assetId"]


# --- Happy path -------------------------------------------------------------


async def test_plan_happy_path(client, stub_broker, auth_user, stereo_music_wav):
    _install_fake_llm(_trim_then_fade_response())
    _install_fake_transcript()
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/ai/plan",
        headers=auth_user["headers"],
        json={"prompt": "trim to first 1.5 seconds then fade out"},
    )
    assert r.status_code == 202, r.text
    op_id = r.json()["operationId"]

    await drain_jobs_async(stub_broker)

    poll = await client.get(f"/api/operations/{op_id}", headers=auth_user["headers"])
    assert poll.status_code == 200
    body = poll.json()
    assert body["status"] == "completed", body
    result = body["result"]
    assert result["prompt"] == "trim to first 1.5 seconds then fade out"
    assert result["modelVersion"] == "fake-llm-v1"
    assert result["finalResponse"] == "Trimming and fading."
    assert result["transcriptUsed"] is True
    assert result["selectionUsed"] is False

    steps = result["steps"]
    assert len(steps) == 2
    # All steps valid because FakeLLMProvider returned schema-valid params.
    assert all(s["validationStatus"] == "valid" for s in steps)
    assert [s["operation"]["type"] for s in steps] == ["trim", "fade_out"]
    # Descriptions are human-readable, not raw JSON.
    assert "1.50" in steps[0]["description"] or "1.5" in steps[0]["description"]


async def test_plan_with_selection(
    client, stub_broker, auth_user, stereo_music_wav,
):
    _install_fake_llm(_trim_then_fade_response())
    _install_fake_transcript()
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/ai/plan",
        headers=auth_user["headers"],
        json={
            "prompt": "fade this part out",
            "selection": {"startSec": 0.3, "endSec": 0.9},
        },
    )
    assert r.status_code == 202
    op_id = r.json()["operationId"]
    await drain_jobs_async(stub_broker)

    body = (await client.get(
        f"/api/operations/{op_id}", headers=auth_user["headers"],
    )).json()
    assert body["status"] == "completed"
    assert body["result"]["selectionUsed"] is True


# --- Validation: invalid steps survive in the result -----------------------


async def test_plan_marks_invalid_steps_without_dropping_them(
    client, stub_broker, auth_user, stereo_music_wav,
):
    """LLM proposed a fade with a negative duration → Pydantic rejects →
    step is included in result with validationStatus=invalid."""
    from app.providers.fake_llm import make_plan_response

    _install_fake_llm(make_plan_response(
        tool_calls=[
            ("fade_in", {"duration_sec": -1.0, "curve": "linear"}),  # invalid
            ("reverse", {}),                                          # valid
        ],
        final_response="",
    ))
    _install_fake_transcript()
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/ai/plan",
        headers=auth_user["headers"],
        json={"prompt": "reverse it then fade in negatively (impossible)"},
    )
    op_id = r.json()["operationId"]
    await drain_jobs_async(stub_broker)
    body = (await client.get(
        f"/api/operations/{op_id}", headers=auth_user["headers"],
    )).json()

    steps = body["result"]["steps"]
    assert len(steps) == 2
    assert steps[0]["validationStatus"] == "invalid"
    assert steps[0]["validationError"] is not None
    assert steps[1]["validationStatus"] == "valid"


async def test_plan_handles_unknown_tool_name_as_invalid(
    client, stub_broker, auth_user, stereo_music_wav,
):
    """A defense-in-depth case — real APIs prevent unknown tool names but
    the fake one lets us simulate the failure path."""
    from app.providers.fake_llm import make_plan_response

    _install_fake_llm(make_plan_response(
        tool_calls=[("invent_a_filter", {"weight": 0.5})],
        final_response="",
    ))
    _install_fake_transcript()
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/ai/plan",
        headers=auth_user["headers"],
        json={"prompt": "apply a magic filter"},
    )
    op_id = r.json()["operationId"]
    await drain_jobs_async(stub_broker)
    body = (await client.get(
        f"/api/operations/{op_id}", headers=auth_user["headers"],
    )).json()

    steps = body["result"]["steps"]
    assert len(steps) == 1
    assert steps[0]["validationStatus"] == "invalid"
    assert "invent_a_filter" in (steps[0]["validationError"] or "").lower() \
        or "unknown" in (steps[0]["validationError"] or "").lower()


# --- Ambiguity (empty plan + final_response) -------------------------------


async def test_plan_ambiguity_path_returns_final_response_with_zero_steps(
    client, stub_broker, auth_user, stereo_music_wav,
):
    from app.providers.fake_llm import make_plan_response

    _install_fake_llm(make_plan_response(
        tool_calls=[],
        final_response="Did you mean trim or delete? Please clarify.",
    ))
    _install_fake_transcript()
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/ai/plan",
        headers=auth_user["headers"],
        json={"prompt": "cut it"},
    )
    op_id = r.json()["operationId"]
    await drain_jobs_async(stub_broker)
    body = (await client.get(
        f"/api/operations/{op_id}", headers=auth_user["headers"],
    )).json()

    assert body["status"] == "completed"
    assert body["result"]["steps"] == []
    assert "Did you mean" in body["result"]["finalResponse"]


# --- Pre-flight admission ---------------------------------------------------


async def test_plan_rejects_empty_prompt(
    client, stub_broker, auth_user, stereo_music_wav,
):
    _install_fake_llm(_trim_then_fade_response())
    _install_fake_transcript()
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/ai/plan",
        headers=auth_user["headers"],
        json={"prompt": "   "},
    )
    assert r.status_code == 422


async def test_plan_on_non_ready_asset_returns_409(
    client, stub_broker, auth_user, stereo_music_wav,
):
    _install_fake_llm(_trim_then_fade_response())
    _install_fake_transcript()
    # Upload but do NOT drain — asset stays in 'processing'.
    with open(stereo_music_wav, "rb") as f:
        up = await client.post(
            "/api/assets/upload",
            headers=auth_user["headers"],
            files={"file": (stereo_music_wav.name, f, "audio/wav")},
        )
    asset_id = up.json()["assetId"]
    r = await client.post(
        f"/api/assets/{asset_id}/ai/plan",
        headers=auth_user["headers"],
        json={"prompt": "trim it"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ASSET_NOT_READY"


async def test_plan_rejects_oversize_duration(
    client, stub_broker, auth_user, stereo_music_wav, monkeypatch,
):
    _install_fake_llm(_trim_then_fade_response())
    _install_fake_transcript()
    monkeypatch.setattr(
        "app.config.settings.AI_MAX_INPUT_DURATION_SEC", 1, raising=False,
    )
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)
    r = await client.post(
        f"/api/assets/{asset_id}/ai/plan",
        headers=auth_user["headers"],
        json={"prompt": "trim it"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "AI_INPUT_TOO_LONG"


# --- IDOR -------------------------------------------------------------------


async def test_plan_cross_user_returns_404(
    client, stub_broker, auth_user, auth_user_b, stereo_music_wav,
):
    _install_fake_llm(_trim_then_fade_response())
    _install_fake_transcript()
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)
    r = await client.post(
        f"/api/assets/{asset_id}/ai/plan",
        headers=auth_user_b["headers"],
        json={"prompt": "trim it"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "ASSET_NOT_FOUND"


async def test_plan_cross_user_poll_returns_404(
    client, stub_broker, auth_user, auth_user_b, stereo_music_wav,
):
    _install_fake_llm(_trim_then_fade_response())
    _install_fake_transcript()
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)
    r = await client.post(
        f"/api/assets/{asset_id}/ai/plan",
        headers=auth_user["headers"],
        json={"prompt": "trim it"},
    )
    op_id = r.json()["operationId"]
    await drain_jobs_async(stub_broker)

    poll = await client.get(
        f"/api/operations/{op_id}", headers=auth_user_b["headers"],
    )
    assert poll.status_code == 404


# --- Transcript cache shared across AI features ----------------------------


async def test_transient_llm_error_leaves_op_running_for_dramatiq_retry(
    client, stub_broker, auth_user, stereo_music_wav,
):
    """Transient LLMProviderError (provider_unavailable / rate_limited) should
    re-raise so Dramatiq's max_retries=2 kicks in. The op row stays in
    `running` so the retry can re-claim it; only after attempt_count hits 3
    does it get marked `failed` permanently.
    """
    from app.providers.llm import LLMProviderError
    from app.services import nle_service

    _install_fake_transcript()

    # Provider that always raises a transient error.
    class _Always503:
        async def generate_plan(self, **kwargs):
            raise LLMProviderError("provider_unavailable", "fake 503")

    nle_service._llm_provider = _Always503()
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    # Submit the plan request the normal way.
    r = await client.post(
        f"/api/assets/{asset_id}/ai/plan",
        headers=auth_user["headers"],
        json={"prompt": "trim to first 1 sec"},
    )
    op_id = r.json()["operationId"]

    # Drain once. The transient error should re-raise; drain swallows it but the
    # op row should NOT be in terminal state — attempt_count was 1, retries remain.
    await drain_jobs_async(stub_broker)
    poll = await client.get(f"/api/operations/{op_id}", headers=auth_user["headers"])
    body = poll.json()
    assert body["status"] != "completed"
    assert body["status"] != "failed", (
        f"Op should still be retryable after 1 transient failure, got: {body}"
    )

    # Simulate retries exhausted: manually bump attempt_count to 3 and re-run
    # the job directly. Now the error must mark the row failed permanently.
    from app.models.operation import Operation
    from app.workers.db import SyncSession
    with SyncSession() as db:
        op = db.get(Operation, op_id)
        op.attempt_count = 3
        op.status = "queued"  # allow re-claim
        db.commit()

    from app.services.nle_service import _run_ai_nle_plan_job_async
    db2 = SyncSession()
    try:
        try:
            await _run_ai_nle_plan_job_async(db2, op_id)
        except LLMProviderError:
            pass
    finally:
        db2.close()

    poll = await client.get(f"/api/operations/{op_id}", headers=auth_user["headers"])
    body = poll.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "AI_PROVIDER_UNAVAILABLE"


async def test_nle_plan_reuses_transcript_cache_from_filler_detect(
    client, stub_broker, auth_user, stereo_music_wav,
):
    """Per D5: NLE auto-transcribes. Per filler/profanity design: transcript
    cache uses kind='transcript'. So an NLE plan after a filler detect on
    the same asset must reuse the same transcript row, not re-transcribe.
    """
    _install_fake_llm(_trim_then_fade_response())
    _install_fake_transcript()
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    # First: filler detect creates the transcript row.
    r1 = await client.post(
        f"/api/assets/{asset_id}/ai/detect-fillers",
        headers=auth_user["headers"], json={},
    )
    await drain_jobs_async(stub_broker)
    filler_body = (await client.get(
        f"/api/operations/{r1.json()['operationId']}",
        headers=auth_user["headers"],
    )).json()
    fillers_tx_id = filler_body["result"]["transcriptId"]

    # Second: NLE plan must reuse it.
    r2 = await client.post(
        f"/api/assets/{asset_id}/ai/plan",
        headers=auth_user["headers"],
        json={"prompt": "trim the first second"},
    )
    op_id = r2.json()["operationId"]
    await drain_jobs_async(stub_broker)
    nle_body = (await client.get(
        f"/api/operations/{op_id}", headers=auth_user["headers"],
    )).json()
    assert nle_body["status"] == "completed"
    assert nle_body["result"]["transcriptUsed"] is True

    # The transcriptId isn't exposed on NlePlanResult (we don't need it there),
    # but the cache reuse is observable by the analyses table having exactly
    # one row for this asset.
    # Verify indirectly: re-fetch filler detect's transcript_id; if NLE had
    # created a new row, a fresh detect would now return THAT new row instead.
    r3 = await client.post(
        f"/api/assets/{asset_id}/ai/detect-fillers",
        headers=auth_user["headers"], json={},
    )
    await drain_jobs_async(stub_broker)
    filler_body_2 = (await client.get(
        f"/api/operations/{r3.json()['operationId']}",
        headers=auth_user["headers"],
    )).json()
    assert filler_body_2["result"]["transcriptId"] == fillers_tx_id, (
        "NLE plan should have reused the transcript cache; instead it "
        "appears to have created a new analyses row."
    )
