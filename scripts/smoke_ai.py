"""End-to-end smoke test for the AI "Remove Filler Words" feature.

Exercises the full AI path: register → upload → detect-fillers (AI queue) →
poll result → remove_segments commit (DSP queue) → poll derived asset.

**Does not require a real transcription model.** Run the backend with
`TRANSCRIPTION_PROVIDER=fake` in `backend/.env` and the detect op will return
an empty regions list — the smoke still proves every HTTP + worker + storage
path. Flip to `local` (or `openai`) to exercise real ASR; the commit step uses
hand-picked intervals regardless.

Prereqs (run once, from project root):
    docker compose up -d postgres redis
    cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
    cd backend && .venv/Scripts/dramatiq.exe app.workers.entrypoint -Q uploads operations exports -p 1 -t 1
    cd backend && .venv/Scripts/dramatiq.exe app.workers.entrypoint -Q ai -p 1 -t 1

Run:
    cd backend && .venv/Scripts/python.exe ../scripts/smoke_ai.py

Expected output: one "[OK]" line per step, ending with "AI SMOKE PASSED".
"""
from __future__ import annotations

import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8000"
EMAIL = f"smoke-ai-{secrets.token_hex(4)}@example.com"
PASSWORD = "smoke-ai-test-password-123"


def _die(step: str, resp: httpx.Response) -> None:
    print(f"[FAIL] {step}: {resp.status_code} {resp.text[:400]}")
    sys.exit(1)


def _make_wav(path: Path) -> None:
    """3-second stereo sine — long enough that remove_segments has something to cut."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3:sample_rate=44100",
        "-ac", "2", "-c:a", "pcm_s16le",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=10)


def _poll(client: httpx.Client, url: str, terminal: set[str], label: str, timeout_s: int) -> dict:
    deadline = time.time() + timeout_s
    body: dict = {}
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
    tmp = Path("smoke_ai_fixture.wav")
    _make_wav(tmp)
    print(f"[OK] generated fixture {tmp} ({tmp.stat().st_size} bytes, ~3 s)")

    with httpx.Client(base_url=BASE, timeout=120.0) as client:
        # 1. Register
        r = client.post("/api/auth/register", json={
            "email": EMAIL, "password": PASSWORD, "display_name": "AI Smoke"
        })
        if r.status_code != 201:
            _die("register", r)
        client.headers["Authorization"] = f"Bearer {r.json()['accessToken']}"
        print(f"[OK] register {EMAIL}")

        # 2. Upload
        with tmp.open("rb") as f:
            r = client.post(
                "/api/assets/upload",
                files={"file": ("smoke_ai.wav", f, "audio/wav")},
            )
        if r.status_code != 202:
            _die("upload", r)
        asset_id = r.json()["assetId"]
        asset = _poll(client, f"/api/assets/{asset_id}", {"ready", "failed"}, "asset", timeout_s=30)
        if asset.get("status") != "ready":
            print(f"[FAIL] asset not ready: {asset}")
            sys.exit(1)
        print(f"[OK] asset ready -> {asset_id} ({asset['durationSec']:.2f}s, {asset['channels']}ch)")

        # 3. Detect fillers
        r = client.post(
            f"/api/assets/{asset_id}/ai/detect-fillers",
            json={"confidence_threshold": 0.0},
        )
        if r.status_code != 202:
            _die("enqueue detect", r)
        detect_op_id = r.json()["operationId"]
        print(f"[OK] detect enqueued -> {detect_op_id}")

        detect = _poll(
            client, f"/api/operations/{detect_op_id}",
            {"completed", "failed", "cancelled"}, "detect", timeout_s=120,
        )
        if detect["status"] != "completed":
            print(f"[FAIL] detect status={detect['status']}: {detect}")
            sys.exit(1)
        result = detect.get("result") or {}
        regions = result.get("regions") or []
        print(f"[OK] detect completed -> {len(regions)} regions, model={result.get('modelVersion')}")

        # 4. Transcript cache hit: second detect should be a no-op for the provider
        r = client.post(
            f"/api/assets/{asset_id}/ai/detect-fillers",
            json={"confidence_threshold": 0.0},
        )
        if r.status_code != 202:
            _die("enqueue second detect", r)
        detect2 = _poll(
            client, f"/api/operations/{r.json()['operationId']}",
            {"completed", "failed", "cancelled"}, "detect-2", timeout_s=60,
        )
        if detect2["status"] != "completed":
            print(f"[FAIL] cache-hit detect status={detect2['status']}")
            sys.exit(1)
        if (detect2["result"] or {}).get("transcriptId") != (result or {}).get("transcriptId"):
            print("[FAIL] transcript cache miss — transcriptIds differ between detects")
            sys.exit(1)
        print(f"[OK] transcript cache hit -> same transcriptId")

        # 5. remove_segments commit with hand-picked intervals
        r = client.post(
            f"/api/assets/{asset_id}/operations",
            json={
                "type": "remove_segments",
                "parameters": {
                    "intervals": [
                        {"start": 0.5, "end": 0.8},
                        {"start": 1.5, "end": 1.9},
                    ],
                    "crossfade_ms": 20.0,
                },
            },
        )
        if r.status_code != 202:
            _die("enqueue remove_segments", r)
        commit_op_id = r.json()["operationId"]
        print(f"[OK] remove_segments enqueued -> {commit_op_id}")

        commit = _poll(
            client, f"/api/operations/{commit_op_id}",
            {"completed", "failed", "cancelled"}, "commit", timeout_s=60,
        )
        if commit["status"] != "completed":
            print(f"[FAIL] commit status={commit['status']}: {commit}")
            sys.exit(1)
        derived_id = commit["asset"]["assetId"]
        derived_duration = commit["asset"]["durationSec"]
        if abs(derived_duration - (3.0 - 0.3 - 0.4)) > 0.2:  # input - cuts = ~2.3 s
            print(f"[FAIL] derived duration unexpected: {derived_duration}")
            sys.exit(1)
        print(f"[OK] commit completed -> {derived_id} ({derived_duration:.2f}s, {commit['asset']['channels']}ch)")

    print("AI SMOKE PASSED")


if __name__ == "__main__":
    try:
        main()
    finally:
        Path("smoke_ai_fixture.wav").unlink(missing_ok=True)
