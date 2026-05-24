"""Boot the full v2.5 dev stack in a single terminal.

Starts:
  - Docker services (postgres, redis, minio, minio-init) via `docker compose up -d --wait`
  - Backend API (uvicorn)   on :8000
  - DSP worker  (Dramatiq, -Q uploads operations exports)
  - AI worker   (Dramatiq, -Q ai) — separate pool so transcription latency
                                     never blocks a DSP op
  - Frontend Vite dev server on :5173

Output from each service is streamed with a colored label prefix.
Ctrl+C stops everything (Windows uses `taskkill /F /T`, POSIX uses SIGTERM).

Prereqs (one-time):
  - Docker Desktop running
  - backend/.venv present with deps installed
  - backend/.env present   (cp backend/env.example backend/.env)
  - DB tables created      (backend/.venv/Scripts/python.exe scripts/init_db.py)
  - frontend/node_modules  (cd frontend && npm install)

Usage:
  python scripts/dev_up.py
  python scripts/dev_up.py --no-docker     # stack already up
  python scripts/dev_up.py --no-frontend   # backend only
  python scripts/dev_up.py --no-worker
  python scripts/dev_up.py --no-api
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IS_WIN = os.name == "nt"

COLORS = {
    "cyan":    "\033[36m",
    "magenta": "\033[35m",
    "green":   "\033[32m",
    "yellow":  "\033[33m",
    "red":     "\033[31m",
    "blue":    "\033[34m",
    "reset":   "\033[0m",
}

# Enable ANSI escape processing on Windows consoles.
if IS_WIN:
    try:
        os.system("")
    except Exception:
        pass


def _backend_python() -> str:
    p = ROOT / "backend" / (".venv/Scripts/python.exe" if IS_WIN else ".venv/bin/python")
    if not p.exists():
        sys.stderr.write(f"[FATAL] backend venv python not found at {p}\n")
        sys.exit(2)
    return str(p)


def _dramatiq_exe() -> str:
    p = ROOT / "backend" / (".venv/Scripts/dramatiq.exe" if IS_WIN else ".venv/bin/dramatiq")
    if not p.exists():
        sys.stderr.write(f"[FATAL] dramatiq not found at {p}\n")
        sys.exit(2)
    return str(p)


def _log(label: str, color: str, line: str) -> None:
    if not line.endswith("\n"):
        line += "\n"
    sys.stdout.write(f"{COLORS[color]}[{label:>7}]{COLORS['reset']} {line}")
    sys.stdout.flush()


def _pump(proc: subprocess.Popen, label: str, color: str) -> None:
    try:
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            sys.stdout.write(f"{COLORS[color]}[{label:>7}]{COLORS['reset']} {line}")
            sys.stdout.flush()
    except Exception as e:
        _log(label, "red", f"<pump error: {e}>")


def _spawn(label: str, color: str, cmd: list[str] | str, cwd: Path,
           shell: bool = False) -> subprocess.Popen:
    kwargs: dict = {
        "cwd": str(cwd),
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "bufsize": 1,
        "shell": shell,
    }
    if IS_WIN:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(cmd, **kwargs)
    t = threading.Thread(target=_pump, args=(proc, label, color), daemon=True)
    t.start()
    shown = cmd if isinstance(cmd, str) else " ".join(cmd)
    _log(label, color, f"started (pid={proc.pid}): {shown}")
    return proc


def _docker_up() -> None:
    # Step 1: bring up long-running services and wait for health.
    # minio-init is intentionally excluded — it's a one-shot that exits 0 after
    # creating buckets, and `--wait` would flag its exit as a failure.
    _log("docker", "yellow", "docker compose up -d --wait postgres redis minio …")
    r = subprocess.run(
        ["docker", "compose", "up", "-d", "--wait", "postgres", "redis", "minio"],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        _log("docker", "red", f"compose up failed: rc={r.returncode}")
        sys.exit(2)

    # Step 2: run minio-init (no --wait; it exits 0 once buckets exist).
    # `mc mb --ignore-existing` makes this idempotent on reruns.
    _log("docker", "yellow", "docker compose up -d minio-init (one-shot) …")
    r = subprocess.run(
        ["docker", "compose", "up", "-d", "minio-init"],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        _log("docker", "red", f"minio-init failed: rc={r.returncode}")
        sys.exit(2)
    _log("docker", "yellow", "services healthy")


def _stop(entries: list[tuple[str, subprocess.Popen]]) -> None:
    for label, p in entries:
        if p.poll() is not None:
            continue
        _log(label, "yellow", f"stopping pid={p.pid}")
        try:
            if IS_WIN:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(p.pid)],
                    capture_output=True,
                )
            else:
                p.terminate()
        except Exception as e:
            _log(label, "red", f"stop error: {e}")
    for label, p in entries:
        try:
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-docker", action="store_true", help="Skip `docker compose up`")
    ap.add_argument("--no-api", action="store_true")
    ap.add_argument("--no-worker", action="store_true")
    ap.add_argument("--no-frontend", action="store_true")
    args = ap.parse_args()

    if not args.no_docker:
        _docker_up()

    backend_dir = ROOT / "backend"
    frontend_dir = ROOT / "frontend"
    procs: list[tuple[str, subprocess.Popen]] = []

    try:
        if not args.no_api:
            procs.append(("api", _spawn(
                "api", "cyan",
                [_backend_python(), "-m", "uvicorn", "app.main:app", "--reload",
                 "--host", "0.0.0.0", "--port", "8000"],
                cwd=backend_dir,
            )))

        if not args.no_worker:
            # Two pools so AI transcription (slow, network/CPU-bound) never
            # blocks a DSP op (fast, FFmpeg-bound). Single process + single
            # thread each — dev profile; scale with -p/-t in production.
            procs.append(("dsp", _spawn(
                "dsp", "magenta",
                [_dramatiq_exe(), "app.workers.entrypoint",
                 "-Q", "uploads", "operations", "exports",
                 "-p", "1", "-t", "1"],
                cwd=backend_dir,
            )))
            procs.append(("ai", _spawn(
                "ai", "blue",
                [_dramatiq_exe(), "app.workers.entrypoint",
                 "-Q", "ai",
                 "-p", "1", "-t", "1"],
                cwd=backend_dir,
            )))

        if not args.no_frontend:
            # On Windows, npm is npm.cmd — let the shell resolve it.
            cmd: list[str] | str = "npm run dev" if IS_WIN else ["npm", "run", "dev"]
            procs.append(("vite", _spawn(
                "vite", "green",
                cmd, cwd=frontend_dir, shell=IS_WIN,
            )))

        _log("main", "yellow",
             f"{len(procs)} service(s) running — http://localhost:5173  (Ctrl+C to stop)")

        # Block until Ctrl+C or any child exits unexpectedly.
        while True:
            time.sleep(0.5)
            for label, p in procs:
                rc = p.poll()
                if rc is not None:
                    _log("main", "red",
                         f"{label} exited rc={rc} — tearing down other services")
                    return rc or 1
    except KeyboardInterrupt:
        _log("main", "yellow", "Ctrl+C received — stopping services")
        return 0
    finally:
        _stop(procs)
        _log("main", "yellow", "all stopped")


if __name__ == "__main__":
    sys.exit(main())
