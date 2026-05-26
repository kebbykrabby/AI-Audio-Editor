"""End-to-end tests for POST /api/assets/{id}/ai/detect-profanity.

Mirrors test_ai_detect_fillers.py — uses FakeTranscriptionProvider so CI
never loads a real Whisper model. Covers the happy path, ASSET_NOT_READY
short-circuit, oversize-input admission gate, and the IDOR guard.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import drain_jobs_async


pytestmark = pytest.mark.asyncio


def _install_fake_provider(transcript):
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
            TranscribedWord(text="shit", start=0.40, end=0.55),
            TranscribedWord(text="this", start=0.60, end=0.85),
            TranscribedWord(text="is", start=0.90, end=1.05),
            TranscribedWord(text="damn", start=1.10, end=1.30),
            TranscribedWord(text="cool", start=1.35, end=1.80),
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


async def test_detect_profanity_happy_path(
    client, stub_broker, auth_user, stereo_music_wav,
):
    _install_fake_provider(_fake_transcript())
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/ai/detect-profanity",
        headers=auth_user["headers"],
        json={},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    op_id = body["operationId"]

    await drain_jobs_async(stub_broker)

    poll = await client.get(f"/api/operations/{op_id}", headers=auth_user["headers"])
    assert poll.status_code == 200
    body = poll.json()
    assert body["status"] == "completed", body
    result = body["result"]
    assert result["language"] == "en"
    assert result["modelVersion"] == "fake-v1"
    assert result["durationSec"] == 2.0
    texts = sorted(r["text"] for r in result["regions"])
    # Our fixture has "shit" and "damn" — both must be flagged.
    assert texts == ["damn", "shit"]
    # Every region tagged with the matcher that caught it.
    assert {r["matchedBy"] for r in result["regions"]} == {"exact"}
    assert all(r["category"] == "profanity" for r in result["regions"])


async def test_detect_profanity_returns_transcript_id(
    client, stub_broker, auth_user, stereo_music_wav,
):
    _install_fake_provider(_fake_transcript())
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/ai/detect-profanity",
        headers=auth_user["headers"],
        json={},
    )
    op_id = r.json()["operationId"]
    await drain_jobs_async(stub_broker)
    body = (await client.get(f"/api/operations/{op_id}", headers=auth_user["headers"])).json()
    assert body["result"]["transcriptId"]


async def test_detect_profanity_on_non_ready_asset_returns_409(
    client, stub_broker, auth_user, stereo_music_wav,
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
        f"/api/assets/{asset_id}/ai/detect-profanity",
        headers=auth_user["headers"],
        json={},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "ASSET_NOT_READY"


async def test_detect_profanity_rejects_oversized_duration(
    client, stub_broker, auth_user, stereo_music_wav, monkeypatch,
):
    _install_fake_provider(_fake_transcript())
    monkeypatch.setattr(
        "app.config.settings.AI_MAX_INPUT_DURATION_SEC", 1, raising=False,
    )
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/ai/detect-profanity",
        headers=auth_user["headers"],
        json={},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "AI_INPUT_TOO_LONG"


async def test_detect_profanity_cross_user_returns_404(
    client, stub_broker, auth_user, auth_user_b, stereo_music_wav,
):
    _install_fake_provider(_fake_transcript())
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)
    r = await client.post(
        f"/api/assets/{asset_id}/ai/detect-profanity",
        headers=auth_user_b["headers"],
        json={},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "ASSET_NOT_FOUND"


async def test_detect_profanity_cross_user_poll_returns_404(
    client, stub_broker, auth_user, auth_user_b, stereo_music_wav,
):
    _install_fake_provider(_fake_transcript())
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)
    r = await client.post(
        f"/api/assets/{asset_id}/ai/detect-profanity",
        headers=auth_user["headers"],
        json={},
    )
    op_id = r.json()["operationId"]
    await drain_jobs_async(stub_broker)

    poll = await client.get(
        f"/api/operations/{op_id}",
        headers=auth_user_b["headers"],
    )
    assert poll.status_code == 404


async def test_detect_profanity_non_english_returns_no_regions(
    client, stub_broker, auth_user, stereo_music_wav,
):
    """Per D3: English-only MVP. Non-en transcript without user overrides → 0 regions."""
    from app.providers.transcription import TranscribedWord, WordLevelTranscript

    _install_fake_provider(WordLevelTranscript(
        language="es",
        duration_sec=2.0,
        # Even if the word would match an English builtin, language gate fires first.
        words=[TranscribedWord(text="shit", start=0.0, end=0.3)],
        model_version="fake-es",
        cost_usd=0.0,
    ))
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/ai/detect-profanity",
        headers=auth_user["headers"], json={},
    )
    op_id = r.json()["operationId"]
    await drain_jobs_async(stub_broker)
    body = (await client.get(f"/api/operations/{op_id}", headers=auth_user["headers"])).json()
    assert body["status"] == "completed"
    assert body["result"]["regions"] == []


async def test_detect_profanity_shares_transcript_cache_with_fillers(
    client, stub_broker, auth_user, stereo_music_wav,
):
    """Per D5: filler-detect and profanity-detect share the analyses cache row.

    Second call should reuse the transcript row — same transcriptId across both ops.
    """
    _install_fake_provider(_fake_transcript())
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    # First: filler detect (writes the transcript row).
    r1 = await client.post(
        f"/api/assets/{asset_id}/ai/detect-fillers",
        headers=auth_user["headers"], json={},
    )
    await drain_jobs_async(stub_broker)
    fillers_body = (await client.get(
        f"/api/operations/{r1.json()['operationId']}",
        headers=auth_user["headers"],
    )).json()
    fillers_transcript_id = fillers_body["result"]["transcriptId"]

    # Second: profanity detect (must reuse the cached row).
    r2 = await client.post(
        f"/api/assets/{asset_id}/ai/detect-profanity",
        headers=auth_user["headers"], json={},
    )
    await drain_jobs_async(stub_broker)
    profanity_body = (await client.get(
        f"/api/operations/{r2.json()['operationId']}",
        headers=auth_user["headers"],
    )).json()
    profanity_transcript_id = profanity_body["result"]["transcriptId"]

    assert fillers_transcript_id == profanity_transcript_id, (
        "filler-detect and profanity-detect must share the analyses cache row"
    )
