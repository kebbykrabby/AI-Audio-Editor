"""Async operation lifecycle tests.

Covers the queued → running → completed|failed state machine, the polling
response shape, failure-path error propagation, and split_channels dual output.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import drain_jobs_async


pytestmark = pytest.mark.asyncio


async def _upload_and_ready(client, stub_broker, user, wav_path: Path) -> str:
    with open(wav_path, "rb") as f:
        res = await client.post(
            "/api/assets/upload",
            headers=user["headers"],
            files={"file": (wav_path.name, f, "audio/wav")},
        )
    assert res.status_code == 202
    await drain_jobs_async(stub_broker)
    asset_id = res.json()["assetId"]
    r = await client.get(f"/api/assets/{asset_id}", headers=user["headers"])
    assert r.json()["status"] == "ready"
    return asset_id


async def test_enqueue_returns_202_with_queued_status(
    client, stub_broker, auth_user, stereo_music_wav,
):
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/operations",
        headers=auth_user["headers"],
        json={"type": "trim", "parameters": {"start_sec": 0.1, "end_sec": 0.5}},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["operationId"]
    assert body.get("asset") is None  # no output yet


async def test_poll_before_drain_is_queued_or_running(
    client, stub_broker, auth_user, stereo_music_wav,
):
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)
    r = await client.post(
        f"/api/assets/{asset_id}/operations",
        headers=auth_user["headers"],
        json={"type": "trim", "parameters": {"start_sec": 0.1, "end_sec": 0.5}},
    )
    op_id = r.json()["operationId"]

    # Poll without draining — operation should still be queued
    r2 = await client.get(f"/api/operations/{op_id}", headers=auth_user["headers"])
    assert r2.status_code == 200
    assert r2.json()["status"] in ("queued", "running")
    assert r2.json().get("asset") is None


async def test_poll_after_drain_is_completed_with_asset(
    client, stub_broker, auth_user, stereo_music_wav,
):
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)
    r = await client.post(
        f"/api/assets/{asset_id}/operations",
        headers=auth_user["headers"],
        json={"type": "trim", "parameters": {"start_sec": 0.2, "end_sec": 0.7}},
    )
    op_id = r.json()["operationId"]
    await drain_jobs_async(stub_broker)

    r2 = await client.get(f"/api/operations/{op_id}", headers=auth_user["headers"])
    body = r2.json()
    assert body["status"] == "completed", body
    assert body["asset"]["parentAssetId"] == asset_id
    assert body["asset"]["status"] == "ready"
    assert abs(body["asset"]["durationSec"] - 0.5) < 0.1


async def test_injected_dsp_error_marks_operation_failed(
    client, stub_broker, auth_user, stereo_music_wav, monkeypatch,
):
    """Patch the trim processor to raise; the operation must land as `failed`
    with no output asset and the error surfaced in the polling response."""
    from app.processors import ffmpeg as ffmpeg_proc

    async def boom(*args, **kwargs):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(ffmpeg_proc, "trim", boom)

    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)
    r = await client.post(
        f"/api/assets/{asset_id}/operations",
        headers=auth_user["headers"],
        json={"type": "trim", "parameters": {"start_sec": 0.1, "end_sec": 0.5}},
    )
    op_id = r.json()["operationId"]
    await drain_jobs_async(stub_broker)

    r2 = await client.get(f"/api/operations/{op_id}", headers=auth_user["headers"])
    body = r2.json()
    assert body["status"] == "failed", body
    assert body.get("asset") is None
    assert body["error"]["code"]  # populated, any code is fine — we care that it exists


async def test_split_channels_returns_primary_and_secondary_assets(
    client, stub_broker, auth_user, stereo_music_wav,
):
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/operations",
        headers=auth_user["headers"],
        json={"type": "split_channels", "parameters": {}},
    )
    assert r.status_code == 202, r.text
    op_id = r.json()["operationId"]
    await drain_jobs_async(stub_broker)

    r2 = await client.get(f"/api/operations/{op_id}", headers=auth_user["headers"])
    body = r2.json()
    assert body["status"] == "completed", body
    assert body["asset"] is not None
    assert body["secondaryAsset"] is not None
    assert body["asset"]["assetId"] != body["secondaryAsset"]["assetId"]
    # Both land as mono derived from the stereo parent
    assert body["asset"]["channels"] == 1
    assert body["secondaryAsset"]["channels"] == 1


async def test_polling_is_idempotent(
    client, stub_broker, auth_user, stereo_music_wav,
):
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)
    r = await client.post(
        f"/api/assets/{asset_id}/operations",
        headers=auth_user["headers"],
        json={"type": "gain", "parameters": {"gain_db": 3.0}},
    )
    op_id = r.json()["operationId"]
    await drain_jobs_async(stub_broker)

    first = (await client.get(f"/api/operations/{op_id}", headers=auth_user["headers"])).json()
    second = (await client.get(f"/api/operations/{op_id}", headers=auth_user["headers"])).json()
    assert first["status"] == second["status"] == "completed"
    assert first["asset"]["assetId"] == second["asset"]["assetId"]
