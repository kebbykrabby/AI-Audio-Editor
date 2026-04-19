"""Export error-shape tests for the v2.5 contract.

Exports are now async: POST /assets/{id}/export returns 202 with exportId,
polling GET /exports/{id} yields status. Validation errors (unknown asset,
asset not ready, invalid format) are synchronous and use the standard
{error: {code, message}} envelope.
"""
from __future__ import annotations

import pytest

from .conftest import drain_jobs_async


pytestmark = pytest.mark.asyncio


async def test_export_on_unknown_asset_returns_standard_error(client, auth_user):
    r = await client.post(
        "/api/assets/ast_missing/export",
        headers=auth_user["headers"],
        json={"format": "wav"},
    )
    assert r.status_code == 404
    body = r.json()
    assert "error" in body
    assert body["error"]["code"] == "ASSET_NOT_FOUND"
    assert "detail" not in body


async def test_export_on_processing_asset_returns_not_ready(
    client, stub_broker, auth_user, stereo_music_wav
):
    """If the asset is still processing (upload not drained), export must be
    rejected synchronously with ASSET_NOT_READY (409)."""
    with open(stereo_music_wav, "rb") as f:
        up = await client.post(
            "/api/assets/upload",
            headers=auth_user["headers"],
            files={"file": ("in.wav", f, "audio/wav")},
        )
    asset_id = up.json()["assetId"]

    # Don't drain — asset is in "processing" state.
    r = await client.post(
        f"/api/assets/{asset_id}/export",
        headers=auth_user["headers"],
        json={"format": "wav"},
    )
    assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["error"]["code"] == "ASSET_NOT_READY"
    assert "detail" not in body


async def test_export_invalid_format_returns_422_from_schema(
    client, stub_broker, auth_user, stereo_music_wav
):
    """format='ogg' is outside Literal['wav', 'mp3'] → 422 at Pydantic layer."""
    with open(stereo_music_wav, "rb") as f:
        up = await client.post(
            "/api/assets/upload",
            headers=auth_user["headers"],
            files={"file": ("in.wav", f, "audio/wav")},
        )
    asset_id = up.json()["assetId"]
    await drain_jobs_async(stub_broker)

    r = await client.post(
        f"/api/assets/{asset_id}/export",
        headers=auth_user["headers"],
        json={"format": "ogg"},
    )
    assert r.status_code == 422
