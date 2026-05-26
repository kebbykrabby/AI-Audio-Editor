"""Guards the AI cost audit log line the worker writes on every successful detect.

Devil's Advocate flagged observability as a blind spot: without a structured
line per AI call, cost anomalies and stuck jobs are invisible. This test
pins the fields we promised: {op, user, duration, regions, cost, model}.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from .conftest import drain_jobs_async


pytestmark = pytest.mark.asyncio


def _install_fake():
    from app.providers.fake import FakeTranscriptionProvider
    from app.providers.transcription import TranscribedWord, WordLevelTranscript
    from app.services import ai_service

    ai_service._provider = FakeTranscriptionProvider(
        transcript=WordLevelTranscript(
            language="en",
            duration_sec=3.14,
            words=[
                TranscribedWord(text="um", start=0.1, end=0.25),
                TranscribedWord(text="hello", start=0.3, end=0.9),
            ],
            model_version="fake-audit",
            cost_usd=0.0,
        ),
    )


async def _upload_ready(client, stub_broker, user, wav: Path) -> str:
    with open(wav, "rb") as f:
        r = await client.post(
            "/api/assets/upload",
            headers=user["headers"],
            files={"file": (wav.name, f, "audio/wav")},
        )
    assert r.status_code == 202
    await drain_jobs_async(stub_broker)
    return r.json()["assetId"]


async def test_successful_detect_emits_structured_audit_line(
    client, stub_broker, auth_user, stereo_music_wav, caplog,
):
    _install_fake()
    asset_id = await _upload_ready(client, stub_broker, auth_user, stereo_music_wav)

    caplog.set_level(logging.INFO, logger="app.services.ai_service")

    r = await client.post(
        f"/api/assets/{asset_id}/ai/detect-fillers",
        headers=auth_user["headers"],
        json={},
    )
    op_id = r.json()["operationId"]
    await drain_jobs_async(stub_broker)

    # Find the audit record.
    audit = [
        rec for rec in caplog.records
        if "ai_detect_fillers done" in rec.getMessage()
    ]
    assert audit, "expected one 'ai_detect_fillers done' structured log line"
    line = audit[-1].getMessage()
    # Every promised field must appear.
    assert f"op={op_id}" in line
    assert f"user={auth_user['userId']}" in line
    assert "duration=3.1s" in line
    assert "regions=" in line
    assert "cost=" in line
    assert "model=fake-audit" in line
