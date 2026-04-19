"""Async export lifecycle tests.

Covers: enqueue -> drain -> poll completed shape; WAV @44.1 and MP3 @192 kbps
actually produce downloadable, well-formed audio.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import drain_jobs_async, ffprobe_info


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


async def _run_export_and_download(
    client, stub_broker, user, asset_id, payload, suffix, tmp_path
) -> Path:
    r = await client.post(
        f"/api/assets/{asset_id}/export",
        headers=user["headers"],
        json=payload,
    )
    assert r.status_code == 202, r.text
    export_id = r.json()["exportId"]
    await drain_jobs_async(stub_broker)

    r2 = await client.get(f"/api/exports/{export_id}", headers=user["headers"])
    assert r2.status_code == 200
    body = r2.json()
    assert body["status"] == "completed", body
    assert body["downloadUrl"], body

    # Fetch the file through the same ASGI client (LocalStorage signed_url
    # points at the /files mount).
    dl = await client.get(body["downloadUrl"])
    assert dl.status_code == 200, f"download failed: {dl.status_code} {dl.text[:200]}"
    out = tmp_path / f"export_out{suffix}"
    out.write_bytes(dl.content)
    return out


async def test_enqueue_and_poll_completes_with_download_url(
    client, stub_broker, auth_user, stereo_music_wav,
):
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/export",
        headers=auth_user["headers"],
        json={"format": "wav"},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["exportId"]
    assert body.get("downloadUrl") is None

    await drain_jobs_async(stub_broker)

    r2 = await client.get(f"/api/exports/{body['exportId']}", headers=auth_user["headers"])
    done = r2.json()
    assert done["status"] == "completed"
    assert done["downloadUrl"]
    assert done["format"] == "wav"


async def test_wav_44100_roundtrip(
    client, stub_broker, auth_user, stereo_music_wav, tmp_path,
):
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)
    out = await _run_export_and_download(
        client, stub_broker, auth_user, asset_id,
        {"format": "wav", "sample_rate": 44100}, ".wav", tmp_path,
    )
    info = ffprobe_info(out)
    assert info["sample_rate"] == 44100
    assert info["channels"] == 2
    assert info["duration_sec"] > 0.1


async def test_mp3_192_roundtrip(
    client, stub_broker, auth_user, stereo_music_wav, tmp_path,
):
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)
    out = await _run_export_and_download(
        client, stub_broker, auth_user, asset_id,
        {"format": "mp3", "bitrate_kbps": 192}, ".mp3", tmp_path,
    )
    info = ffprobe_info(out)
    # ffprobe reports MP3 duration; sample rate depends on encoder but should
    # be in a sane range.
    assert info["sample_rate"] in (22050, 32000, 44100, 48000)
    assert info["channels"] == 2
    assert info["duration_sec"] > 0.1
