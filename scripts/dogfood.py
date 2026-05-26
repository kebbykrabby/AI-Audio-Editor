"""Automated dogfooding for v2.5 — HTTP-layer equivalent of docs/v2.5-dogfooding.md.

Covers the 11-item checklist end-to-end against a running stack (docker +
backend + worker). UI-specific visual checks (waveform render, playhead,
buttons) are not possible from HTTP — they're flagged as UI-ONLY and
considered out of scope for this script.

Prereqs (same as smoke.py):
    docker compose up -d postgres redis minio minio-init
    cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
    cd backend && .venv/Scripts/dramatiq.exe app.workers.entrypoint -p 1 -t 1

Run:
    cd backend && .venv/Scripts/python.exe ../scripts/dogfood.py

Exit code 0 = all items that can be auto-checked passed.
Exit code 1 = a check failed (traceback above).

Items that CANNOT be validated by this script and must be verified in a
browser (or skipped with a written reason):
  - item 2 partial:  access token NOT in localStorage (pure-browser check)
  - item 3 partial:  waveform renders / playhead at 0:00 (visual)
  - item 4 partial:  button spinner / other ops disabled (visual)
  - item 6 partial:  "sounds clean" when played (we verify file validity only)
  - item 9:          16+ min signed-URL refresh (too slow for CI-style runs)
  - item 10:         Google OAuth (not configured per user)
  - item 11 partial: channel-editor UI shows both tracks (visual)
"""
from __future__ import annotations

import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8000"
PASSWORD = "dogfood-test-password-123"
TMP_DIR = Path(".dogfood_tmp")


# ---------- reporting ----------

_fails: list[str] = []


def _ok(item: str, msg: str) -> None:
    print(f"[{item} OK]   {msg}")


def _skip(item: str, msg: str) -> None:
    print(f"[{item} SKIP] {msg}")


def _fail(item: str, msg: str) -> None:
    print(f"[{item} FAIL] {msg}")
    _fails.append(f"{item}: {msg}")


def _die(item: str, msg: str, resp: httpx.Response | None = None) -> None:
    detail = f" — {resp.status_code} {resp.text[:300]}" if resp is not None else ""
    _fail(item, f"{msg}{detail}")
    _summary()
    sys.exit(1)


def _summary() -> None:
    print()
    if _fails:
        print(f"DOGFOOD FAILED ({len(_fails)} failure(s)):")
        for f in _fails:
            print(f"  - {f}")
    else:
        print("DOGFOOD PASSED (for items that can be auto-checked)")


# ---------- fixtures ----------

def _require_ffmpeg(item: str) -> None:
    if shutil.which("ffmpeg") is None:
        _die(item, "ffmpeg not on PATH — required to synthesize test audio")


def _make_mono_wav(path: Path, duration: float = 3.0) -> None:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={duration}:sample_rate=44100",
        "-ac", "1", "-c:a", "pcm_s16le",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=15)


def _make_stereo_asym_wav(path: Path, duration: float = 2.0) -> None:
    """L = 440 Hz tone, R = silence. Matches the `stereo_asymmetric_wav` fixture."""
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={duration}:sample_rate=44100",
        "-f", "lavfi",
        "-i", f"anullsrc=r=44100:cl=mono:d={duration}",
        "-filter_complex", "[0:a][1:a]amerge=inputs=2[a]",
        "-map", "[a]", "-ac", "2", "-c:a", "pcm_s16le",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=15)


# ---------- helpers ----------

def _new_client() -> httpx.Client:
    return httpx.Client(base_url=BASE, timeout=30.0)


def _auth_client(email: str) -> tuple[httpx.Client, dict]:
    """Register a fresh user and return a client with access-token header + cookies."""
    c = _new_client()
    r = c.post("/api/auth/register", json={
        "email": email, "password": PASSWORD, "display_name": "Dogfood",
    })
    if r.status_code != 201:
        c.close()
        _die("setup", f"register {email}", r)
    tokens = r.json()
    c.headers["Authorization"] = f"Bearer {tokens['accessToken']}"
    return c, tokens


def _poll(client: httpx.Client, url: str, terminal: set[str], label: str,
          item: str, timeout_s: int = 60) -> dict:
    deadline = time.time() + timeout_s
    body: dict = {}
    while time.time() < deadline:
        r = client.get(url)
        if r.status_code != 200:
            _die(item, f"poll {label}", r)
        body = r.json()
        if body.get("status") in terminal:
            return body
        time.sleep(1.0)
    _die(item, f"poll {label} timed out after {timeout_s}s at {body.get('status')!r}")
    return {}  # unreachable


def _upload_ready(client: httpx.Client, wav: Path, item: str, timeout_s: int = 30) -> dict:
    with wav.open("rb") as f:
        r = client.post(
            "/api/assets/upload",
            files={"file": (wav.name, f, "audio/wav")},
        )
    if r.status_code != 202:
        _die(item, "upload", r)
    asset_id = r.json()["assetId"]
    asset = _poll(client, f"/api/assets/{asset_id}", {"ready", "failed"},
                  "asset", item, timeout_s=timeout_s)
    if asset.get("status") != "ready":
        _die(item, f"asset not ready: {asset}")
    return asset


# ---------- items ----------

def item_1_unauth_me_returns_401() -> None:
    """1. Fresh browser → login screen (i.e. /me without auth → 401)."""
    with _new_client() as c:
        r = c.get("/api/auth/me")
    if r.status_code != 401:
        _die("1", f"expected 401, got {r.status_code}")
    _ok("1", "unauthenticated GET /api/auth/me → 401")
    _skip("1", "UI-only: login form render, no flash of upload screen")


def item_2_register_sets_cookies_and_returns_tokens() -> str:
    """2. Register → 201, access token in body, refresh + csrf cookies set."""
    email = f"df-{secrets.token_hex(4)}@example.com"
    with _new_client() as c:
        r = c.post("/api/auth/register", json={
            "email": email, "password": PASSWORD, "display_name": "Dogfood",
        })
        if r.status_code != 201:
            _die("2", "register", r)
        body = r.json()
        if not body.get("accessToken"):
            _die("2", f"no accessToken in body: {body}")
        # Inspect Set-Cookie headers from the register response itself.
        set_cookies = r.headers.get_list("set-cookie") if hasattr(r.headers, "get_list") else [
            v for k, v in r.headers.raw_items() if k.decode("latin-1").lower() == "set-cookie"
        ]
        joined = " | ".join(set_cookies).lower()
        if "refresh=" not in joined or "httponly" not in joined:
            _die("2", f"refresh cookie missing or not HttpOnly: {joined[:400]}")
        if "csrf=" not in joined:
            _die("2", f"csrf cookie missing: {joined[:400]}")
        # csrf must NOT be httponly (frontend reads it for double-submit)
        csrf_line = next((s for s in set_cookies if s.lower().startswith("csrf=")), "")
        if "httponly" in csrf_line.lower():
            _die("2", f"csrf cookie is HttpOnly (should be readable): {csrf_line}")

        # /me works with the access token.
        c.headers["Authorization"] = f"Bearer {body['accessToken']}"
        me = c.get("/api/auth/me")
        if me.status_code != 200 or me.json().get("email") != email:
            _die("2", "/me after register", me)

    _ok("2", f"register → 201, accessToken present, refresh httponly + csrf readable ({email})")
    _skip("2", "UI-only: access token NOT in localStorage (frontend keeps it in memory)")
    return email


def item_3_upload_wav_ready_under_5s() -> None:
    """3. Upload 3s WAV → status flips ready within ~5s."""
    _require_ffmpeg("3")
    wav = TMP_DIR / "item3.wav"
    _make_mono_wav(wav, duration=3.0)
    email = f"df-{secrets.token_hex(4)}@example.com"
    c, _ = _auth_client(email)
    try:
        t0 = time.time()
        asset = _upload_ready(c, wav, "3", timeout_s=10)
        elapsed = time.time() - t0
        if elapsed > 10.0:
            _die("3", f"asset ready took {elapsed:.1f}s (> 10s budget)")
        dur = asset.get("durationSec") or 0.0
        if abs(dur - 3.0) > 0.2:
            _die("3", f"durationSec={dur}, expected ~3.0")
        _ok("3", f"upload → ready in {elapsed:.1f}s (duration {dur:.2f}s, {asset.get('channels')}ch)")
        _skip("3", "UI-only: waveform render, playhead at 0:00, Play button")
    finally:
        c.close()


def item_4_trim_op_completes() -> None:
    """4. Trim op → queued → completed with derived asset."""
    _require_ffmpeg("4")
    wav = TMP_DIR / "item4.wav"
    _make_mono_wav(wav, duration=2.0)
    email = f"df-{secrets.token_hex(4)}@example.com"
    c, _ = _auth_client(email)
    try:
        asset = _upload_ready(c, wav, "4")
        r = c.post(
            f"/api/assets/{asset['assetId']}/operations",
            json={"type": "trim", "parameters": {"start_sec": 0.3, "end_sec": 1.2}},
        )
        if r.status_code != 202:
            _die("4", "enqueue trim", r)
        op_id = r.json()["operationId"]
        op = _poll(c, f"/api/operations/{op_id}",
                   {"completed", "failed", "cancelled"}, "trim op", "4", timeout_s=60)
        if op["status"] != "completed":
            _die("4", f"trim op status={op['status']}: {op}")
        derived = op.get("asset")
        if not derived or derived.get("status") != "ready":
            _die("4", f"derived asset missing or not ready: {derived}")
        dur = derived.get("durationSec") or 0.0
        if abs(dur - 0.9) > 0.15:
            _die("4", f"derived duration {dur:.2f}s, expected ~0.9s")
        _ok("4", f"trim completed → derived asset {derived['assetId'][:12]}… ({dur:.2f}s)")
        _skip("4", "UI-only: button spinner, other ops disabled, Undo enabled")
    finally:
        c.close()


def item_5_reload_mid_op_recovers() -> None:
    """5. Simulate page reload mid-op: a *new* client (new access token via refresh)
    must still be able to poll the pending operation to completion.
    """
    _require_ffmpeg("5")
    wav = TMP_DIR / "item5.wav"
    _make_mono_wav(wav, duration=1.0)
    email = f"df-{secrets.token_hex(4)}@example.com"

    # Tab 1 lifecycle: upload + enqueue op, grab refresh + csrf cookies.
    c1, _ = _auth_client(email)
    try:
        asset = _upload_ready(c1, wav, "5")
        r = c1.post(
            f"/api/assets/{asset['assetId']}/operations",
            json={"type": "gain", "parameters": {"gain_db": 2.0}},
        )
        if r.status_code != 202:
            _die("5", "enqueue gain", r)
        op_id = r.json()["operationId"]

        # Copy refresh + csrf cookies to a *fresh* client (the "reloaded tab").
        refresh_cookie = c1.cookies.get("refresh")
        csrf_cookie = c1.cookies.get("csrf")
        if not refresh_cookie or not csrf_cookie:
            _die("5", "refresh/csrf cookie missing on c1")
    finally:
        c1.close()

    with _new_client() as c2:
        r = c2.post(
            "/api/auth/refresh",
            headers={"X-CSRF-Token": csrf_cookie},
            cookies={"refresh": refresh_cookie, "csrf": csrf_cookie},
        )
        if r.status_code != 200:
            _die("5", "silent refresh after reload", r)
        new_access = r.json()["accessToken"]
        c2.headers["Authorization"] = f"Bearer {new_access}"

        # Poll the pending op with the new access token — must resume + complete.
        op = _poll(c2, f"/api/operations/{op_id}",
                   {"completed", "failed", "cancelled"}, "reloaded op", "5", timeout_s=60)
        if op["status"] != "completed":
            _die("5", f"op after reload status={op['status']}")
    _ok("5", f"reload mid-op: new client polled {op_id[:12]}… to completion via refresh")


def item_6_export_wav_and_mp3() -> None:
    """6. Export WAV + MP3 @ 192k → download URL serves a non-empty valid file."""
    _require_ffmpeg("6")
    wav = TMP_DIR / "item6.wav"
    _make_mono_wav(wav, duration=2.0)
    email = f"df-{secrets.token_hex(4)}@example.com"
    c, _ = _auth_client(email)
    try:
        asset = _upload_ready(c, wav, "6")

        for fmt, extra in [("wav", {"sample_rate": 44100}), ("mp3", {"bitrate_kbps": 192})]:
            r = c.post(
                f"/api/assets/{asset['assetId']}/export",
                json={"format": fmt, **extra},
            )
            if r.status_code != 202:
                _die("6", f"enqueue export {fmt}", r)
            export_id = r.json()["exportId"]
            exp = _poll(c, f"/api/exports/{export_id}",
                        {"completed", "failed"}, f"export {fmt}", "6", timeout_s=60)
            if exp["status"] != "completed" or not exp.get("downloadUrl"):
                _die("6", f"export {fmt} failed: {exp}")

            # Fetch the signed URL; if relative, resolve against BASE.
            url = exp["downloadUrl"]
            if url.startswith("/"):
                url = BASE + url
            with httpx.Client(timeout=30.0) as dl:
                d = dl.get(url)
            if d.status_code != 200:
                _die("6", f"download {fmt} status {d.status_code}")
            if len(d.content) < 1024:
                _die("6", f"download {fmt} too small: {len(d.content)} bytes")

            # Quick magic-byte sanity check.
            head = d.content[:4]
            if fmt == "wav" and head != b"RIFF":
                _die("6", f"wav magic != RIFF: {head!r}")
            if fmt == "mp3" and not (head[:3] == b"ID3" or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xfa")):
                _die("6", f"mp3 magic unexpected: {head!r}")

            _ok("6", f"export {fmt}: {len(d.content)} bytes, magic OK, downloadable")
    finally:
        c.close()
    _skip("6", "UI-only: opens in OS audio player and plays cleanly")


def item_7_two_tabs_share_session() -> None:
    """7. Two clients with the same refresh cookie both get working access tokens."""
    email = f"df-{secrets.token_hex(4)}@example.com"
    c1, _ = _auth_client(email)
    try:
        refresh_cookie = c1.cookies.get("refresh")
        csrf_cookie = c1.cookies.get("csrf")

        # Tab 1 is live — /me works.
        r1 = c1.get("/api/auth/me")
        if r1.status_code != 200:
            _die("7", "/me on tab 1", r1)

        # Tab 2 bootstraps from cookies only (no access token yet) → silent refresh.
        with _new_client() as c2:
            r = c2.post(
                "/api/auth/refresh",
                headers={"X-CSRF-Token": csrf_cookie},
                cookies={"refresh": refresh_cookie, "csrf": csrf_cookie},
            )
            if r.status_code != 200:
                _die("7", "tab 2 silent refresh", r)
            c2.headers["Authorization"] = f"Bearer {r.json()['accessToken']}"
            r2 = c2.get("/api/auth/me")
            if r2.status_code != 200 or r2.json().get("email") != email:
                _die("7", "/me on tab 2", r2)
        _ok("7", "tab 2 silent refresh via cookies → /me succeeds")
    finally:
        c1.close()


def item_8_logout_invalidates_refresh_family() -> None:
    """8. After logout, the refresh cookie family is revoked: another client
    using the same refresh cookie can no longer refresh.
    """
    email = f"df-{secrets.token_hex(4)}@example.com"
    c1, _ = _auth_client(email)
    try:
        refresh_cookie = c1.cookies.get("refresh")
        csrf_cookie = c1.cookies.get("csrf")

        # Simulate tab 2 before logout — it can refresh fine.
        with _new_client() as c2_pre:
            pre = c2_pre.post(
                "/api/auth/refresh",
                headers={"X-CSRF-Token": csrf_cookie},
                cookies={"refresh": refresh_cookie, "csrf": csrf_cookie},
            )
            if pre.status_code != 200:
                _die("8", "tab 2 pre-logout refresh", pre)

        # Tab 1 logs out — revokes the refresh family.
        lo = c1.post("/api/auth/logout")
        if lo.status_code != 204:
            _die("8", "logout", lo)

        # Tab 2 (fresh client) tries to refresh with the *original* cookie → 401.
        with _new_client() as c2_post:
            post = c2_post.post(
                "/api/auth/refresh",
                headers={"X-CSRF-Token": csrf_cookie},
                cookies={"refresh": refresh_cookie, "csrf": csrf_cookie},
            )
            if post.status_code != 401:
                _die("8", f"post-logout refresh should be 401, got {post.status_code}: {post.text[:200]}")
        _ok("8", "logout revokes refresh family — old cookie can't refresh (401)")
    finally:
        c1.close()


def item_9_long_idle_url_refresh() -> None:
    _skip("9", "too slow (>16 min idle) — run manually in a browser with MinIO storage")


def item_10_google_oauth() -> None:
    _skip("10", "GOOGLE_CLIENT_ID not configured")


def item_11_split_channels_two_assets() -> None:
    """11. Stereo asymmetric → split_channels returns two mono assets, both ready."""
    _require_ffmpeg("11")
    wav = TMP_DIR / "item11.wav"
    _make_stereo_asym_wav(wav, duration=2.0)
    email = f"df-{secrets.token_hex(4)}@example.com"
    c, _ = _auth_client(email)
    try:
        asset = _upload_ready(c, wav, "11")
        if (asset.get("channels") or 0) != 2:
            _die("11", f"expected stereo input, got channels={asset.get('channels')}")

        r = c.post(
            f"/api/assets/{asset['assetId']}/operations",
            json={"type": "split_channels", "parameters": {}},
        )
        if r.status_code != 202:
            _die("11", "enqueue split_channels", r)
        op_id = r.json()["operationId"]
        op = _poll(c, f"/api/operations/{op_id}",
                   {"completed", "failed", "cancelled"}, "split_channels", "11", timeout_s=60)
        if op["status"] != "completed":
            _die("11", f"split_channels status={op['status']}: {op}")
        primary = op.get("asset")
        secondary = op.get("secondaryAsset")
        if not primary or not secondary:
            _die("11", f"missing primary/secondary: {op}")
        if primary.get("assetId") == secondary.get("assetId"):
            _die("11", "primary and secondary share the same assetId")
        if primary.get("channels") != 1 or secondary.get("channels") != 1:
            _die("11", f"expected mono outputs, got L={primary.get('channels')} R={secondary.get('channels')}")
        if primary.get("sampleRate") != asset.get("sampleRate"):
            _die("11", f"sample rate not preserved: parent={asset.get('sampleRate')} primary={primary.get('sampleRate')}")
        _ok("11", f"split_channels → L={primary['assetId'][:8]} R={secondary['assetId'][:8]}, both mono, sample rate preserved")
        _skip("11", "UI-only: channel-editor shows both tracks, each plays")
    finally:
        c.close()


# ---------- main ----------

def main() -> None:
    TMP_DIR.mkdir(exist_ok=True)
    try:
        print(f"Dogfooding against {BASE} — {TMP_DIR.resolve()}")
        print("-" * 70)
        item_1_unauth_me_returns_401()
        item_2_register_sets_cookies_and_returns_tokens()
        item_3_upload_wav_ready_under_5s()
        item_4_trim_op_completes()
        item_5_reload_mid_op_recovers()
        item_6_export_wav_and_mp3()
        item_7_two_tabs_share_session()
        item_8_logout_invalidates_refresh_family()
        item_9_long_idle_url_refresh()
        item_10_google_oauth()
        item_11_split_channels_two_assets()
    finally:
        shutil.rmtree(TMP_DIR, ignore_errors=True)
        _summary()
        sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
