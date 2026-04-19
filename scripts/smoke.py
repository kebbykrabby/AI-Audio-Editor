"""End-to-end smoke test for Stage A of the v2.5 migration plan.

Exercises: register -> login -> upload -> operation (trim) -> export, polling
the async endpoints until terminal state.

Prereqs (run these once):
    docker compose up -d postgres redis
    cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
    cd backend && .venv/Scripts/dramatiq.exe app.workers.entrypoint -p 1 -t 1

Run:
    cd backend && .venv/Scripts/python.exe ../scripts/smoke.py

Expected output: one "[OK]" line per step, ending with "SMOKE PASSED".
Any non-zero exit = a stage failed. Read the traceback.

This script is intentionally dependency-light (httpx only) so it can be
invoked from any venv that has httpx available.
"""
from __future__ import annotations

import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8000"
EMAIL = f"smoke-{secrets.token_hex(4)}@example.com"
PASSWORD = "smoke-test-password-123"


def _die(step: str, resp: httpx.Response) -> None:
    print(f"[FAIL] {step}: {resp.status_code} {resp.text[:400]}")
    sys.exit(1)


def _make_wav(path: Path) -> None:
    """Generate a 1-second stereo sine WAV via ffmpeg."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1:sample_rate=44100",
        "-ac", "2", "-c:a", "pcm_s16le",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=10)


def _poll(client: httpx.Client, url: str, terminal: set[str], label: str, timeout_s: int = 60) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = client.get(url)
        if r.status_code != 200:
            _die(f"poll {label}", r)
        body = r.json()
        if body.get("status") in terminal:
            return body
        time.sleep(1.0)
    print(f"[FAIL] {label}: timed out after {timeout_s}s at {body.get('status')!r}")
    sys.exit(1)


def main() -> None:
    tmp = Path("smoke_fixture.wav")
    _make_wav(tmp)
    print(f"[OK] generated fixture {tmp} ({tmp.stat().st_size} bytes)")

    with httpx.Client(base_url=BASE, timeout=30.0) as client:
        # 1. Register
        r = client.post("/api/auth/register", json={
            "email": EMAIL, "password": PASSWORD, "display_name": "Smoke"
        })
        if r.status_code != 201:
            _die("register", r)
        access = r.json()["accessToken"]
        client.headers["Authorization"] = f"Bearer {access}"
        print(f"[OK] register {EMAIL}")

        # 2. /me
        r = client.get("/api/auth/me")
        if r.status_code != 200 or r.json()["email"] != EMAIL:
            _die("me", r)
        print(f"[OK] me -> {r.json()['userId']}")

        # 3. Upload
        with tmp.open("rb") as f:
            r = client.post(
                "/api/assets/upload",
                files={"file": ("smoke.wav", f, "audio/wav")},
            )
        if r.status_code != 202:
            _die("upload", r)
        asset_id = r.json()["assetId"]
        print(f"[OK] upload -> asset {asset_id}")

        # 4. Poll asset until ready
        asset = _poll(
            client, f"/api/assets/{asset_id}", {"ready", "failed"},
            "asset", timeout_s=30,
        )
        if asset.get("status") != "ready":
            print(f"[FAIL] asset not ready: {asset}")
            sys.exit(1)
        print(f"[OK] asset ready ({asset.get('durationSec'):.2f}s, {asset.get('channels')}ch)")

        # 5. Operation (trim 0.2-0.8)
        r = client.post(
            f"/api/assets/{asset_id}/operations",
            json={"type": "trim", "parameters": {"start_sec": 0.2, "end_sec": 0.8}},
        )
        if r.status_code != 202:
            _die("enqueue operation", r)
        op_id = r.json()["operationId"]
        print(f"[OK] operation enqueued -> {op_id}")

        op = _poll(
            client, f"/api/operations/{op_id}", {"completed", "failed", "cancelled"},
            "operation", timeout_s=60,
        )
        if op["status"] != "completed":
            print(f"[FAIL] operation status={op['status']}: {op}")
            sys.exit(1)
        derived_id = op["asset"]["assetId"]
        print(f"[OK] operation completed -> derived asset {derived_id}")

        # 6. Export the derived asset
        r = client.post(
            f"/api/assets/{derived_id}/export",
            json={"format": "wav", "sample_rate": 44100},
        )
        if r.status_code != 202:
            _die("enqueue export", r)
        export_id = r.json()["exportId"]
        print(f"[OK] export enqueued -> {export_id}")

        exp = _poll(
            client, f"/api/exports/{export_id}", {"completed", "failed"},
            "export", timeout_s=60,
        )
        if exp["status"] != "completed" or not exp.get("downloadUrl"):
            print(f"[FAIL] export status={exp['status']}: {exp}")
            sys.exit(1)
        print(f"[OK] export completed -> {exp['downloadUrl'][:80]}")

    print("SMOKE PASSED")


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            Path("smoke_fixture.wav").unlink(missing_ok=True)
        except Exception:
            pass
