"""API integration tests covering the V2 review's contract-shape concerns.

Uses FastAPI's sync TestClient for simplicity — ASGI under the hood so the
async endpoints still execute normally. Storage is redirected to a tmp dir
via the `tmp_storage` fixture.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest


@pytest.fixture()
def client(tmp_storage):
    """Build a fresh app + TestClient against the tmp storage/db."""
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


# --- Happy path (upload → poll → trim → export) ---------------------------

def test_happy_path_upload_trim_export(client, stereo_music_wav):
    # Upload
    with open(stereo_music_wav, "rb") as f:
        res = client.post(
            "/api/assets/upload",
            files={"file": ("in.wav", f, "audio/wav")},
        )
    assert res.status_code == 202
    body = res.json()
    assert body["status"] == "processing"
    asset_id = body["assetId"]

    # Poll for ready (upload processing is async; generous 10s budget)
    deadline = time.time() + 10
    status = "processing"
    while time.time() < deadline and status == "processing":
        r = client.get(f"/api/assets/{asset_id}")
        assert r.status_code == 200
        status = r.json()["status"]
        if status == "processing":
            time.sleep(0.5)
    assert status == "ready", f"asset never became ready (final status: {status})"

    ready_body = r.json()
    assert ready_body["channels"] == 2
    assert ready_body["sampleRate"] == 44100
    # error field must NOT be present on a ready response (contract compliance)
    assert "error" not in ready_body, (
        f"error field leaked onto non-failed response: {ready_body}"
    )

    # Trim (in-spec operation)
    r = client.post(
        f"/api/assets/{asset_id}/operations",
        json={"type": "trim", "parameters": {"start_sec": 0.2, "end_sec": 0.8}},
    )
    assert r.status_code == 200, r.text
    op_body = r.json()
    assert op_body["status"] == "completed"
    assert op_body["asset"]["channels"] == 2
    assert abs(op_body["asset"]["durationSec"] - 0.6) < 0.1
    derived_id = op_body["asset"]["assetId"]
    assert op_body["asset"]["parentAssetId"] == asset_id

    # Export
    r = client.post(
        f"/api/assets/{derived_id}/export",
        json={"format": "wav"},
    )
    assert r.status_code == 200, r.text
    exp_body = r.json()
    assert exp_body["format"] == "wav"
    assert exp_body["channels"] == 2


# --- Error shape conformance (report §3.6, §3.7) --------------------------

def test_asset_not_found_uses_standard_error_shape(client):
    r = client.get("/api/assets/ast_does_not_exist")
    assert r.status_code == 404
    body = r.json()
    # Must be {"error": {"code": ..., "message": ...}}, not FastAPI's {"detail": ...}
    assert "error" in body, f"expected standard error shape, got {body}"
    assert body["error"]["code"] == "ASSET_NOT_FOUND"
    assert "message" in body["error"]
    assert "detail" not in body, "detail field indicates HTTPException leak"


def test_audio_stream_not_found_uses_standard_error_shape(client):
    r = client.get("/api/assets/ast_does_not_exist/audio")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "ASSET_NOT_FOUND"


# --- Validation richness (report §3.7) ------------------------------------

def test_validation_error_includes_field_constraint_received(client, stereo_music_wav):
    # Upload a file first so we have a real asset to operate on
    with open(stereo_music_wav, "rb") as f:
        up = client.post(
            "/api/assets/upload",
            files={"file": ("in.wav", f, "audio/wav")},
        )
    asset_id = up.json()["assetId"]

    # Wait for ready
    for _ in range(20):
        r = client.get(f"/api/assets/{asset_id}")
        if r.json()["status"] == "ready":
            break
        time.sleep(0.5)

    # Trim with start >= end — should fail validation with rich details
    r = client.post(
        f"/api/assets/{asset_id}/operations",
        json={"type": "trim", "parameters": {"start_sec": 5.0, "end_sec": 2.0}},
    )
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "INVALID_PARAMETERS"
    # Contract promises details.{field, constraint, received}
    assert "details" in err, f"validation error missing details: {err}"
    assert err["details"]["field"] == "start_sec"
    assert "constraint" in err["details"]
    assert err["details"]["received"] == 5.0


# --- Speed factor boundary (report §3.9) ----------------------------------

def test_speed_factor_boundary_inclusive(client, stereo_music_wav):
    """The contract says 0.25 <= factor; the Pydantic schema must agree.

    We don't need to run FFmpeg — we just need to confirm the schema accepts
    0.25 and rejects 0.249.
    """
    # Upload a file first
    with open(stereo_music_wav, "rb") as f:
        up = client.post(
            "/api/assets/upload",
            files={"file": ("in.wav", f, "audio/wav")},
        )
    asset_id = up.json()["assetId"]
    for _ in range(20):
        r = client.get(f"/api/assets/{asset_id}")
        if r.json()["status"] == "ready":
            break
        time.sleep(0.5)

    # 0.249 must be rejected by schema validation (before we hit FFmpeg)
    r = client.post(
        f"/api/assets/{asset_id}/operations",
        json={"type": "speed", "parameters": {"factor": 0.249}},
    )
    assert r.status_code == 422

    # 0.25 should be accepted by schema (actual processing is tested in test_dsp)
    # We don't need to let it run to completion here — we only care that validation
    # passes, so if it gets to processing (200) or times out, schema acceptance is proven.
    r = client.post(
        f"/api/assets/{asset_id}/operations",
        json={"type": "speed", "parameters": {"factor": 0.25}},
    )
    # Accepts either completed OR a downstream error that is NOT schema validation.
    # We only guard against a 422 from the schema itself.
    if r.status_code == 422:
        # If it did 422, it must be for a *non-schema* reason (e.g. nothing we'd expect here)
        err = r.json()["error"]
        # fail the test explicitly — factor=0.25 should pass the schema
        pytest.fail(f"factor=0.25 rejected at schema level: {err}")
