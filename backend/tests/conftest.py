"""Shared fixtures for the v2.5 test suite.

Design goals:
- Zero Docker prereq for the common-path suite. Tests use:
    * SQLite (aiosqlite for API, pysqlite for worker jobs) in a per-test tmp file
    * Dramatiq StubBroker (TESTING=1 flag in app.workers.broker picks this up)
    * LocalStorage under a per-test tmp dir
  Tests that require real Postgres or MinIO use @pytest.mark.pg / @pytest.mark.s3
  and are skipped unless the relevant env var is set.
- Skip cleanly if the `ffmpeg` binary isn't on PATH — DSP tests can't run.
- Purge `app.*` module cache per test so fresh config picks up monkey-patched env.
- Helpers for auth: register_user(), login_user(), auth_headers().
- A drain_jobs() helper that inspects the StubBroker's queues and invokes actor
  functions directly — avoids the SQLite-over-multiple-connections headache that
  a background Dramatiq Worker would cause with in-process SQLite.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio

# Skip the entire package if ffmpeg isn't available. DSP tests cannot run without it.
if shutil.which("ffmpeg") is None:
    pytest.skip("ffmpeg not found on PATH; skipping DSP/integration tests", allow_module_level=True)


# These must be set BEFORE any `app.*` module is imported anywhere in the suite.
# Individual fixtures below override DATABASE_URL and STORAGE_ROOT per test.
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
os.environ.setdefault("STORAGE_BACKEND", "local")


# =============================================================================
# Session-scoped loop
# =============================================================================

@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped loop so async fixtures and clients share one loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# =============================================================================
# Per-test env wiring
# =============================================================================

@pytest.fixture()
def test_env(tmp_path, monkeypatch):
    """Point DATABASE_URL, STORAGE_ROOT, and the JWT secret at per-test resources.

    Also purges `app.*` module cache so a fresh `Settings()` (and downstream
    singletons like the Dramatiq broker) pick up the new env.
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JWT_SECRET", "test-secret-" + "x" * 40)

    for name in list(sys.modules):
        if name.startswith("app."):
            sys.modules.pop(name, None)
    return tmp_path


# Backwards-compatible alias for tests written against the v2-stabilization suite.
@pytest.fixture()
def tmp_storage(test_env):
    return test_env


# =============================================================================
# Database
# =============================================================================

@pytest_asyncio.fixture()
async def db(test_env):
    """Async db session with the full v2.5 schema created."""
    from app.database import Base, async_session, engine
    from app.models import asset, export, operation, user  # noqa: F401 — register models

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        yield session

    await engine.dispose()


# =============================================================================
# Dramatiq StubBroker (replaces Redis)
# =============================================================================

@pytest.fixture()
def stub_broker(test_env):
    """The global Dramatiq broker is a StubBroker when TESTING=1 (see broker.py).

    This fixture imports the worker entrypoint (which registers actors against
    the stub) and flushes any messages from prior tests.
    """
    import dramatiq
    from app.workers import entrypoint  # noqa: F401 — side-effect: register actors

    broker = dramatiq.get_broker()
    # Flush in case the broker is carried over (shouldn't be, given test_env purges)
    try:
        broker.flush_all()
    except Exception:
        pass
    return broker


# =============================================================================
# HTTP client
# =============================================================================

@pytest_asyncio.fixture()
async def client(test_env, db, stub_broker):
    """httpx AsyncClient against the FastAPI app.

    Ordering matters: `db` fixture creates tables; `stub_broker` ensures actors
    are registered against the stub. Both run before app.main is imported here.
    """
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        # Trigger lifespan so startup sweeps run (noop in a fresh DB)
        async with app.router.lifespan_context(app):
            yield c


# Sync TestClient variant for legacy tests that use fastapi.testclient.TestClient.
# The test_api.py/test_export_errors.py rewrites use the async client above.
@pytest.fixture()
def sync_client(test_env, db, stub_broker):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


# =============================================================================
# Auth helpers
# =============================================================================

async def register_user(
    client,
    email: str | None = None,
    password: str = "test-password-12345",
    display_name: str = "Tester",
    verify_email: bool = True,
) -> dict:
    """Register a fresh user. Returns {email, password, userId, accessToken, headers}.

    By default the returned user is email-verified (via a direct DB stamp),
    because most integration tests don't care about the verification flow but
    DO care about post-signup features (export, etc.) that gate on it. Pass
    verify_email=False when the test wants to exercise the gate itself.
    """
    email = email or f"test-{secrets.token_hex(4)}@example.com"
    r = await client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "display_name": display_name},
    )
    assert r.status_code == 201, f"register failed: {r.status_code} {r.text}"
    data = r.json()
    user_id = data["user"]["userId"]

    if verify_email:
        from datetime import datetime

        from app.database import async_session
        from app.models.user import User

        async with async_session() as db:
            u = await db.get(User, user_id)
            u.email_verified_at = datetime.utcnow()
            await db.commit()

    return {
        "email": email,
        "password": password,
        "userId": user_id,
        "accessToken": data["accessToken"],
        "headers": {"Authorization": f"Bearer {data['accessToken']}"},
    }


async def login_user(client, email: str, password: str) -> dict:
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    data = r.json()
    return {
        "accessToken": data["accessToken"],
        "headers": {"Authorization": f"Bearer {data['accessToken']}"},
    }


@pytest_asyncio.fixture()
async def auth_user(client):
    """A ready-to-use registered user. Most integration tests want this."""
    return await register_user(client)


@pytest_asyncio.fixture()
async def auth_user_b(client):
    """A second user for cross-user (IDOR) tests."""
    return await register_user(client, email=f"other-{secrets.token_hex(4)}@example.com")


# =============================================================================
# Broker drain (in-process worker substitute)
# =============================================================================

async def _drain_jobs_async(broker, *, max_loops: int = 10) -> int:
    """Internal: await each actor's async implementation directly so we don't
    trip asyncio.run() (which run_*_job uses in production) while inside
    pytest-asyncio's event loop.
    """
    from dramatiq import Message

    from app.services.ai_service import (
        _run_ai_detect_fillers_job_async,
        _run_ai_detect_profanity_job_async,
    )
    from app.services.asset_service import _run_upload_job_async
    from app.services.export_service import _run_export_job_async
    from app.services.nle_service import _run_ai_nle_plan_job_async
    from app.services.operation_service import _run_operation_job_async
    from app.workers.db import SyncSession

    handlers = {
        "run_upload_actor": _run_upload_job_async,
        "run_operation_actor": _run_operation_job_async,
        "run_export_actor": _run_export_job_async,
        "run_ai_detect_fillers_actor": _run_ai_detect_fillers_job_async,
        "run_ai_detect_profanity_actor": _run_ai_detect_profanity_job_async,
        "run_ai_nle_plan_actor": _run_ai_nle_plan_job_async,
    }

    processed = 0
    for _ in range(max_loops):
        drained_this_pass = 0
        for queue_name, queue in list(broker.queues.items()):
            while True:
                try:
                    msg_bytes = queue.get(block=False)
                except Exception:
                    break
                msg = Message.decode(msg_bytes)
                handler = handlers.get(msg.actor_name)
                if handler is None:
                    queue.task_done()
                    continue
                arg = msg.args[0] if msg.args else next(iter(msg.kwargs.values()))
                db = SyncSession()
                try:
                    try:
                        await handler(db, arg)
                    except Exception:
                        # Real Dramatiq absorbs actor exceptions via the Retries
                        # middleware; the DB row is already marked failed by the
                        # service before re-raise. Tests care about terminal DB
                        # state, not whether the actor raised.
                        pass
                finally:
                    db.close()
                    queue.task_done()
                processed += 1
                drained_this_pass += 1
        if drained_this_pass == 0:
            break
    return processed


def drain_jobs(broker, *, max_loops: int = 10) -> int:
    """Consume every queued message by invoking the actor's async implementation
    directly. Returns the number of messages processed.

    Running a real Dramatiq Worker in-process would open a second connection
    pool to SQLite and risk deadlocks; this helper treats the stub broker as
    a queue we manually drain.

    Designed to be called from both sync and async tests. When called from an
    async test, it re-enters the running loop via a nested task.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        # Called from inside an async test: schedule on the same loop via a
        # new task + run it to completion. `asyncio.run_coroutine_threadsafe`
        # would require a different thread, so we use `loop.create_task` +
        # waiting for completion via `await` — but callers expect a sync
        # return. Best compromise: raise if misused.
        raise RuntimeError(
            "drain_jobs() called from a running event loop; use "
            "`await drain_jobs_async(broker)` in async tests instead."
        )
    return asyncio.run(_drain_jobs_async(broker, max_loops=max_loops))


async def drain_jobs_async(broker, *, max_loops: int = 10) -> int:
    """Async variant of drain_jobs for use inside pytest-asyncio tests."""
    return await _drain_jobs_async(broker, max_loops=max_loops)


# =============================================================================
# Audio fixtures (unchanged from the v2-stabilization suite)
# =============================================================================

@pytest.fixture()
def stereo_asymmetric_wav(tmp_path) -> Path:
    """1s stereo WAV: L=880Hz full-amplitude, R=silent. Exposes (L+R)/2 downmix bugs."""
    path = tmp_path / "stereo_asymmetric.wav"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "sine=frequency=880:duration=1:sample_rate=44100",
        "-af", "volume=8,pan=stereo|c0=c0|c1=0*c0",
        "-c:a", "pcm_s16le",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=20)
    return path


@pytest.fixture()
def stereo_music_wav(tmp_path) -> Path:
    """2s 44.1kHz stereo WAV with audible content on both channels."""
    path = tmp_path / "stereo_music.wav"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2:sample_rate=44100",
        "-f", "lavfi", "-i", "sine=frequency=660:duration=2:sample_rate=44100",
        "-filter_complex",
        "[0:a]volume=8[l];[1:a]volume=8[r];[l][r]join=inputs=2:channel_layout=stereo[a]",
        "-map", "[a]", "-c:a", "pcm_s16le",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=20)
    return path


def ffprobe_info(path: Path) -> dict:
    """Synchronous ffprobe helper for DSP tests."""
    res = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        check=True, capture_output=True, timeout=10,
    )
    info = json.loads(res.stdout)
    stream = next(s for s in info["streams"] if s["codec_type"] == "audio")
    return {
        "duration_sec": float(info["format"]["duration"]),
        "sample_rate": int(stream["sample_rate"]),
        "channels": int(stream["channels"]),
    }
