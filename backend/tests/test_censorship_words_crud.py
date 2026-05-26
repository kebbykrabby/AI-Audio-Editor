"""CRUD + behavior tests for the per-user censorship word list (Phase 3).

Covers:
- GET returns built-in + empty user state for a fresh user
- PUT add → next GET reflects the added words (normalized)
- PUT remove → next GET reflects removals (only valid built-ins survive)
- PUT add then PUT remove → both fields persist (no clobbering on partial update)
- User-added words are caught by detect_profanity
- User-removed built-ins are NOT caught by detect_profanity
- Unauthenticated GET/PUT returns 401
- One user's overrides don't leak to another
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


def _transcript(words: list[tuple[str, float, float]], language: str = "en"):
    from app.providers.transcription import TranscribedWord, WordLevelTranscript
    return WordLevelTranscript(
        language=language,
        duration_sec=5.0,
        words=[TranscribedWord(text=t, start=s, end=e) for t, s, e in words],
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


# --- GET --------------------------------------------------------------------


async def test_get_returns_builtin_and_empty_overrides_for_fresh_user(
    client, auth_user,
):
    r = await client.get(
        "/api/users/me/censorship-words", headers=auth_user["headers"],
    )
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["builtIn"], list)
    assert len(body["builtIn"]) > 0
    # Known built-in (the service exports BUILT_IN; pick one that won't change)
    from app.services.censorship_service import BUILT_IN
    assert next(iter(BUILT_IN)) in body["builtIn"]
    assert body["added"] == []
    assert body["removed"] == []


async def test_get_requires_auth(client):
    r = await client.get("/api/users/me/censorship-words")
    assert r.status_code == 401


# --- PUT --------------------------------------------------------------------


async def test_put_normalizes_added_words(client, auth_user):
    r = await client.put(
        "/api/users/me/censorship-words",
        headers=auth_user["headers"],
        json={"added": ["Banana", "BANANA", "  cherry!  ", "", "  "]},
    )
    assert r.status_code == 200
    body = r.json()
    # Dedupe + lowercase + strip punct; preserve order.
    assert body["added"] == ["banana", "cherry"]


async def test_put_removed_drops_unknown_words(client, auth_user):
    """User-supplied removals that aren't actual built-ins should be discarded
    (otherwise the removed list would grow with no effect).
    """
    r = await client.put(
        "/api/users/me/censorship-words",
        headers=auth_user["headers"],
        json={"removed": ["shit", "not-a-real-builtin"]},
    )
    body = r.json()
    assert "shit" in body["removed"]
    assert "not-a-real-builtin" not in body["removed"]


async def test_put_partial_update_preserves_other_field(client, auth_user):
    # First add a custom word.
    r1 = await client.put(
        "/api/users/me/censorship-words",
        headers=auth_user["headers"],
        json={"added": ["banana"]},
    )
    assert r1.status_code == 200

    # Then remove a built-in WITHOUT touching `added` — the banana must survive.
    r2 = await client.put(
        "/api/users/me/censorship-words",
        headers=auth_user["headers"],
        json={"removed": ["shit"]},
    )
    body = r2.json()
    assert body["added"] == ["banana"]
    assert "shit" in body["removed"]


async def test_put_requires_auth(client):
    r = await client.put(
        "/api/users/me/censorship-words", json={"added": ["banana"]},
    )
    assert r.status_code == 401


# --- IDOR ------------------------------------------------------------------


async def test_users_overrides_isolated(client, auth_user, auth_user_b):
    """User A's overrides must not appear on user B's GET response."""
    await client.put(
        "/api/users/me/censorship-words",
        headers=auth_user["headers"],
        json={"added": ["banana"]},
    )
    r_b = await client.get(
        "/api/users/me/censorship-words", headers=auth_user_b["headers"],
    )
    assert r_b.status_code == 200
    assert "banana" not in r_b.json()["added"]


# --- Detection respects overrides ------------------------------------------


async def test_detect_catches_user_added_word(
    client, stub_broker, auth_user, stereo_music_wav,
):
    """User adds 'banana'; the detector flags it on a transcript containing the word."""
    _install_fake_provider(_transcript([
        ("hello", 0.0, 0.3),
        ("banana", 0.4, 0.7),
        ("world", 0.8, 1.1),
    ]))

    # First: add the custom word.
    await client.put(
        "/api/users/me/censorship-words",
        headers=auth_user["headers"],
        json={"added": ["banana"]},
    )

    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)
    r = await client.post(
        f"/api/assets/{asset_id}/ai/detect-profanity",
        headers=auth_user["headers"], json={},
    )
    op_id = r.json()["operationId"]
    await drain_jobs_async(stub_broker)
    body = (await client.get(
        f"/api/operations/{op_id}", headers=auth_user["headers"],
    )).json()
    texts = [r["text"] for r in body["result"]["regions"]]
    assert "banana" in texts


async def test_detect_skips_user_removed_builtin(
    client, stub_broker, auth_user, stereo_music_wav,
):
    """User removes 'shit' from the builtin list; transcript containing it
    should yield zero regions."""
    _install_fake_provider(_transcript([
        ("hello", 0.0, 0.3),
        ("shit", 0.4, 0.7),
        ("world", 0.8, 1.1),
    ]))

    await client.put(
        "/api/users/me/censorship-words",
        headers=auth_user["headers"],
        json={"removed": ["shit"]},
    )

    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)
    r = await client.post(
        f"/api/assets/{asset_id}/ai/detect-profanity",
        headers=auth_user["headers"], json={},
    )
    op_id = r.json()["operationId"]
    await drain_jobs_async(stub_broker)
    body = (await client.get(
        f"/api/operations/{op_id}", headers=auth_user["headers"],
    )).json()
    texts = [r["text"] for r in body["result"]["regions"]]
    assert "shit" not in texts
    # No other profanity in the fixture; should be empty.
    assert texts == []
