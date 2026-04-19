"""API integration tests for the v2.5 contract.

Covers:
- happy path (upload -> operation -> export) via async + StubBroker drain
- error-shape conformance (always {"error": {...}}, never FastAPI's {"detail": ...})
- validation richness ({field, constraint, received} in INVALID_PARAMETERS details)
- schema boundary acceptance (speed factor = 0.25)
"""
from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import drain_jobs_async


pytestmark = pytest.mark.asyncio


async def _upload_and_ready(client, stub_broker, auth_user, wav_path: Path) -> str:
    """Upload a file, drain the upload worker, return the ready asset id."""
    with open(wav_path, "rb") as f:
        res = await client.post(
            "/api/assets/upload",
            headers=auth_user["headers"],
            files={"file": (wav_path.name, f, "audio/wav")},
        )
    assert res.status_code == 202, f"upload failed: {res.status_code} {res.text}"
    asset_id = res.json()["assetId"]

    drained = await drain_jobs_async(stub_broker)
    assert drained >= 1, "upload worker did not run"

    r = await client.get(f"/api/assets/{asset_id}", headers=auth_user["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready", f"asset never became ready: {body}"
    return asset_id


# --- Happy path -----------------------------------------------------------

async def test_happy_path_upload_trim_export(client, stub_broker, auth_user, stereo_music_wav):
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    # Asset shape after ready
    r = await client.get(f"/api/assets/{asset_id}", headers=auth_user["headers"])
    ready_body = r.json()
    assert ready_body["channels"] == 2
    assert ready_body["sampleRate"] == 44100
    # Contract: no `error` key on a non-failed response.
    assert ready_body.get("error") is None

    # Enqueue trim
    r = await client.post(
        f"/api/assets/{asset_id}/operations",
        headers=auth_user["headers"],
        json={"type": "trim", "parameters": {"start_sec": 0.2, "end_sec": 0.8}},
    )
    assert r.status_code == 202, r.text
    op_body = r.json()
    assert op_body["status"] == "queued"
    op_id = op_body["operationId"]

    await drain_jobs_async(stub_broker)

    r = await client.get(f"/api/operations/{op_id}", headers=auth_user["headers"])
    assert r.status_code == 200
    op_body = r.json()
    assert op_body["status"] == "completed", op_body
    assert op_body["asset"]["channels"] == 2
    assert abs(op_body["asset"]["durationSec"] - 0.6) < 0.1
    derived_id = op_body["asset"]["assetId"]
    assert op_body["asset"]["parentAssetId"] == asset_id

    # Enqueue export
    r = await client.post(
        f"/api/assets/{derived_id}/export",
        headers=auth_user["headers"],
        json={"format": "wav"},
    )
    assert r.status_code == 202, r.text
    export_id = r.json()["exportId"]

    await drain_jobs_async(stub_broker)

    r = await client.get(f"/api/exports/{export_id}", headers=auth_user["headers"])
    assert r.status_code == 200
    exp_body = r.json()
    assert exp_body["status"] == "completed"
    assert exp_body["format"] == "wav"
    assert exp_body.get("downloadUrl"), f"no downloadUrl on completed export: {exp_body}"


# --- Error-shape conformance ---------------------------------------------

async def test_asset_not_found_uses_standard_error_shape(client, auth_user):
    r = await client.get("/api/assets/ast_does_not_exist", headers=auth_user["headers"])
    assert r.status_code == 404
    body = r.json()
    assert "error" in body, f"expected standard error shape, got {body}"
    assert body["error"]["code"] == "ASSET_NOT_FOUND"
    assert "message" in body["error"]
    assert "detail" not in body, "detail field indicates HTTPException leak"


async def test_unauthenticated_asset_request_is_401(client):
    r = await client.get("/api/assets/any-id")
    assert r.status_code == 401


async def test_pydantic_validation_uses_standard_error_envelope(client):
    """FastAPI's default 422 shape is {"detail": [...]}; we override so every
    error response is {"error": {"code", "message", "details"}} for contract
    consistency."""
    r = await client.post(
        "/api/auth/register",
        json={"email": "not-an-email", "password": "short"},
    )
    assert r.status_code == 422
    body = r.json()
    assert "error" in body, f"expected envelope, got {body}"
    assert body["error"]["code"] == "INVALID_PARAMETERS"
    assert body["error"].get("details"), "validation details should be populated"
    assert "detail" not in body


# --- Validation richness --------------------------------------------------

async def test_validation_error_includes_field_constraint_received(
    client, stub_broker, auth_user, stereo_music_wav
):
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    # Trim with start >= end — cross-field validation should fire at enqueue
    # with rich details (INVALID_PARAMETERS).
    r = await client.post(
        f"/api/assets/{asset_id}/operations",
        headers=auth_user["headers"],
        json={"type": "trim", "parameters": {"start_sec": 5.0, "end_sec": 2.0}},
    )
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "INVALID_PARAMETERS"
    assert "details" in err, f"validation error missing details: {err}"
    # The exact field name depends on how the service raises it — must be
    # one of the offending fields, with both constraint and received populated.
    assert err["details"].get("field") in {"start_sec", "end_sec"}
    assert err["details"].get("constraint")
    assert err["details"].get("received") is not None


# --- Schema boundary ------------------------------------------------------

async def test_speed_factor_boundary_inclusive(client, stub_broker, auth_user, stereo_music_wav):
    """factor=0.25 must pass schema; factor=0.249 must fail schema."""
    asset_id = await _upload_and_ready(client, stub_broker, auth_user, stereo_music_wav)

    r = await client.post(
        f"/api/assets/{asset_id}/operations",
        headers=auth_user["headers"],
        json={"type": "speed", "parameters": {"factor": 0.249}},
    )
    assert r.status_code == 422, f"0.249 should fail: {r.text}"

    r = await client.post(
        f"/api/assets/{asset_id}/operations",
        headers=auth_user["headers"],
        json={"type": "speed", "parameters": {"factor": 0.25}},
    )
    assert r.status_code == 202, f"0.25 should enqueue: {r.status_code} {r.text}"
