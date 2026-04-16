"""Shared fixtures for the V2 stabilization test suite.

Design goals:
- Skip cleanly if the `ffmpeg` binary isn't on PATH so the suite stays portable.
- Use a temp storage root + in-memory SQLite per-test so tests don't collide
  with the dev database / storage directory.
- Generate small deterministic WAV fixtures (stereo asymmetric + mono tone) on
  the fly via FFmpeg — avoids shipping binary fixtures.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Skip the entire package if ffmpeg isn't available. DSP tests cannot run without it.
if shutil.which("ffmpeg") is None:
    pytest.skip("ffmpeg not found on PATH; skipping DSP/integration tests", allow_module_level=True)


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped loop so async fixtures and clients share one loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture()
def tmp_storage(tmp_path, monkeypatch):
    """Redirect backend storage to a tmp dir and reset the singleton storage."""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    # Re-import modules that cached the old settings.
    # We intentionally do this by purging relevant modules from sys.modules and
    # letting fresh imports pick up the env vars.
    for mod in [m for m in list(sys.modules) if m.startswith("app.")]:
        sys.modules.pop(mod, None)
    return tmp_path


@pytest.fixture()
def stereo_asymmetric_wav(tmp_path) -> Path:
    """A 1-second 44.1kHz stereo WAV where L is loud (880 Hz) and R is silent.

    This is the key fixture for validating the waveform's max(|L|,|R|) semantics:
    a naive (L+R)/2 downmix would halve the reported peak for these windows.

    Note: FFmpeg's lavfi sine source outputs at ~-18 dB by default, so we boost
    with volume=8 to get a near-full-scale L channel (peak ≈ 0 dBFS). The pan
    filter then synthesizes stereo with a silent R channel.
    """
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
    """A 2-second 44.1kHz stereo WAV with audible content on both channels.

    Useful for tests that need a real stereo signal (speed, trim, etc.)
    where we care about output duration / channel preservation but not content.
    """
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
    """Synchronous ffprobe helper for tests."""
    import json
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
