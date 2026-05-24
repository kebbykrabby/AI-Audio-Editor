"""End-to-end test for the AI detect-fillers path.

Injects a `FakeTranscriptionProvider` with a hand-crafted transcript so we
never hit a real whisper model in CI. Covers:
- POST enqueue returns 202 + queued
- Worker drain produces `completed` with a populated `result.regions`
- Admission preflight rejects oversize inputs
- Cross-user poll on the AI operation returns 404 (IDOR guard)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import drain_jobs_async


pytestmark = pytest.mark.asyncio


def _install_fake_provider(transcript):
    """Replace the cached transcription provider with one returning `transcript`."""
    from app.providers.fake import FakeTranscriptionProvider
    from app.services import ai_service

    ai_service._provider = FakeTranscriptionProvider(transcript=transcript)


def _fake_transcript():
    from app.providers.transcription import TranscribedWord, WordLevelTranscript
    return WordLevelTranscript(
        language="en",
        duration_sec=2.0,
        words=[
            TranscribedWord(text="hello", start=0.0, end=0.35),
            TranscribedWord(text="um", start=0.40, end=0.55),
            TranscribedWord(text="this", start=0.60, end=0.85),
            TranscribedWord(text="is", start=0.90, end=1.05),
            TranscribedWord(text="uh", start=1.10, end=1.25),
            TranscribedWord(text="a", start=1.30, end=1.38),
            TranscribedWord(text="test", start=1.40, end=1.80),
        ],
        model_version="fake-v1",
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


async def test_detect_fillers_happy_path(
    client, stub_broker, auth_user, stereo_music_wav,
):
    _install_fake_provider(_fake_transcript())

    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/ai/detect-fillers",
        headers=auth_user["headers"],
        json={"confidence_threshold": 0.0},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    op_id = body["operationId"]

    await drain_jobs_async(stub_broker)

    r2 = await client.get(f"/api/operations/{op_id}", headers=auth_user["headers"])
    assert r2.status_code == 200
    body = r2.json()
    assert body["status"] == "completed", body
    result = body["result"]
    assert result["durationSec"] == 2.0
    assert result["language"] == "en"
    assert result["modelVersion"] == "fake-v1"
    cats = [r["category"] for r in result["regions"]]
    # Our fixture transcript has one "um" and one "uh"; both should be detected.
    assert "um" in cats
    assert "uh" in cats


async def test_detect_fillers_returns_transcript_id(
    client, stub_broker, auth_user, stereo_music_wav,
):
    _install_fake_provider(_fake_transcript())
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/ai/detect-fillers",
        headers=auth_user["headers"],
        json={},
    )
    op_id = r.json()["operationId"]
    await drain_jobs_async(stub_broker)
    body = (await client.get(f"/api/operations/{op_id}", headers=auth_user["headers"])).json()
    assert body["result"]["transcriptId"]


async def test_detect_fillers_on_non_ready_asset_returns_409(
    client, stub_broker, auth_user, stereo_music_wav, monkeypatch,
):
    _install_fake_provider(_fake_transcript())
    # Upload but do NOT drain — asset stays in 'processing'.
    with open(stereo_music_wav, "rb") as f:
        up = await client.post(
            "/api/assets/upload",
            headers=auth_user["headers"],
            files={"file": (stereo_music_wav.name, f, "audio/wav")},
        )
    asset_id = up.json()["assetId"]

    r = await client.post(
        f"/api/assets/{asset_id}/ai/detect-fillers",
        headers=auth_user["headers"],
        json={},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ASSET_NOT_READY"


async def test_detect_fillers_rejects_oversized_duration(
    client, stub_broker, auth_user, stereo_music_wav, monkeypatch,
):
    _install_fake_provider(_fake_transcript())
    # Force the duration cap lower than the fixture (~2 s).
    monkeypatch.setattr(
        "app.config.settings.AI_MAX_INPUT_DURATION_SEC", 1, raising=False,
    )
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/ai/detect-fillers",
        headers=auth_user["headers"],
        json={},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "AI_INPUT_TOO_LONG"


async def test_detect_fillers_cross_user_returns_404(
    client, stub_broker, auth_user, auth_user_b, stereo_music_wav,
):
    _install_fake_provider(_fake_transcript())
    # User A uploads an asset.
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)
    # User B attempts detect on A's asset.
    r = await client.post(
        f"/api/assets/{asset_id}/ai/detect-fillers",
        headers=auth_user_b["headers"],
        json={},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "ASSET_NOT_FOUND"


async def test_detect_fillers_cross_user_poll_returns_404(
    client, stub_broker, auth_user, auth_user_b, stereo_music_wav,
):
    _install_fake_provider(_fake_transcript())
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)
    r = await client.post(
        f"/api/assets/{asset_id}/ai/detect-fillers",
        headers=auth_user["headers"],
        json={},
    )
    op_id = r.json()["operationId"]
    await drain_jobs_async(stub_broker)

    # User B tries to poll A's completed AI operation.
    r2 = await client.get(f"/api/operations/{op_id}", headers=auth_user_b["headers"])
    assert r2.status_code == 404


async def test_transcript_cache_reused_across_detects(
    client, stub_broker, auth_user, stereo_music_wav,
):
    """Two sequential detect calls on the same asset should reuse the transcript.
    We count provider invocations by swapping to a counting Fake.
    """
    from app.providers.fake import FakeTranscriptionProvider
    from app.providers.transcription import WordLevelTranscript
    from app.services import ai_service

    call_count = {"n": 0}
    baseline = _fake_transcript()

    class CountingFake(FakeTranscriptionProvider):
        async def transcribe(self, audio_path, language="en") -> WordLevelTranscript:
            call_count["n"] += 1
            return baseline

    ai_service._provider = CountingFake()

    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    for _ in range(2):
        r = await client.post(
            f"/api/assets/{asset_id}/ai/detect-fillers",
            headers=auth_user["headers"],
            json={},
        )
        assert r.status_code == 202
        await drain_jobs_async(stub_broker)

    assert call_count["n"] == 1, (
        f"transcribe should be called exactly once across two detects; was {call_count['n']}"
    )
