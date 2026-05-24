"""End-to-end test for the `remove_segments` operation type.

Goes through the standard /operations endpoint so the Pydantic discriminated
union and the service-layer validation are both exercised. The DSP itself is
already unit-tested in test_remove_segments.py; here we verify the HTTP glue.
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
    return res.json()["assetId"]


async def test_remove_segments_happy_path(
    client, stub_broker, auth_user, stereo_music_wav,
):
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/operations",
        headers=auth_user["headers"],
        json={
            "type": "remove_segments",
            "parameters": {
                "intervals": [
                    {"start": 0.2, "end": 0.4},
                    {"start": 1.0, "end": 1.2},
                ],
                "crossfade_ms": 20.0,
            },
        },
    )
    assert r.status_code == 202, r.text
    op_id = r.json()["operationId"]

    await drain_jobs_async(stub_broker)

    r2 = await client.get(f"/api/operations/{op_id}", headers=auth_user["headers"])
    body = r2.json()
    assert body["status"] == "completed", body
    # Expected: input 2s - (0.2+0.2) cut = ~1.6s
    assert abs(body["asset"]["durationSec"] - 1.6) < 0.1
    assert body["asset"]["channels"] == 2
    assert body["asset"]["parentAssetId"] == asset_id


async def test_remove_segments_rejects_overlapping_intervals(
    client, stub_broker, auth_user, stereo_music_wav,
):
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/operations",
        headers=auth_user["headers"],
        json={
            "type": "remove_segments",
            "parameters": {
                "intervals": [
                    {"start": 0.2, "end": 0.8},
                    {"start": 0.5, "end": 1.0},  # overlaps prior
                ],
            },
        },
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_PARAMETERS"


async def test_remove_segments_rejects_out_of_range(
    client, stub_broker, auth_user, stereo_music_wav,
):
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/operations",
        headers=auth_user["headers"],
        json={
            "type": "remove_segments",
            "parameters": {
                "intervals": [{"start": 0.2, "end": 999.0}],  # > duration
            },
        },
    )
    assert r.status_code == 422


async def test_remove_segments_rejects_empty_intervals(
    client, stub_broker, auth_user, stereo_music_wav,
):
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)
    r = await client.post(
        f"/api/assets/{asset_id}/operations",
        headers=auth_user["headers"],
        json={"type": "remove_segments", "parameters": {"intervals": []}},
    )
    # Pydantic min_length=1 → 422
    assert r.status_code == 422


async def test_remove_segments_rejects_total_cut_equals_duration(
    client, stub_broker, auth_user, stereo_music_wav,
):
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)
    r = await client.post(
        f"/api/assets/{asset_id}/operations",
        headers=auth_user["headers"],
        json={
            "type": "remove_segments",
            "parameters": {"intervals": [{"start": 0.0, "end": 2.0}]},
        },
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_PARAMETERS"
