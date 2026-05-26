"""DSP correctness tests for `remove_segments_with_crossfade`.

Guards the DSP Chief's Hard Standards for this op:
- channel count preserved (mono in → mono out, stereo in → stereo out)
- sample rate preserved (no aresample in the filtergraph)
- no discontinuity > a tolerance at any cut boundary (the point of the crossfade)
- boundary cases: interval at t=0, interval at t=duration, single interval,
  many intervals (script-file fallback path)
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.processors import ffmpeg as ffmpeg_proc

from .conftest import ffprobe_info


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _sine_wav(path: Path, *, duration_sec: float, sample_rate: int, channels: int) -> Path:
    """Generate a clean mono or stereo sine at the given SR."""
    if channels == 1:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={duration_sec}:sample_rate={sample_rate}",
            "-af", "volume=8",
            "-c:a", "pcm_s16le",
            str(path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={duration_sec}:sample_rate={sample_rate}",
            "-f", "lavfi",
            "-i", f"sine=frequency=660:duration={duration_sec}:sample_rate={sample_rate}",
            "-filter_complex",
            "[0:a]volume=8[l];[1:a]volume=8[r];[l][r]join=inputs=2:channel_layout=stereo[a]",
            "-map", "[a]", "-c:a", "pcm_s16le",
            str(path),
        ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=20)
    return path


def _decode_samples(path: Path) -> tuple[np.ndarray, int, int]:
    frames, sr, channels = ffmpeg_proc._decode_pcm_sync(path)
    return frames, sr, channels


# --- Happy path: single interval in the middle ------------------------------

def test_single_interval_middle_preserves_stereo_and_rate(tmp_path):
    inp = _sine_wav(tmp_path / "in.wav", duration_sec=2.0, sample_rate=48000, channels=2)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.remove_segments_with_crossfade(
        inp, out, intervals=[(0.8, 1.2)], duration_sec=2.0,
    ))
    info_in = ffprobe_info(inp)
    info_out = ffprobe_info(out)
    assert info_out["channels"] == 2
    assert info_out["sample_rate"] == info_in["sample_rate"]
    # Expected duration = input - (1.2 - 0.8) = 1.6
    assert abs(info_out["duration_sec"] - 1.6) < 0.05


# --- Boundary: interval starts at t=0 ---------------------------------------

def test_interval_at_t0(tmp_path):
    inp = _sine_wav(tmp_path / "in.wav", duration_sec=2.0, sample_rate=44100, channels=1)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.remove_segments_with_crossfade(
        inp, out, intervals=[(0.0, 0.5)], duration_sec=2.0,
    ))
    info_out = ffprobe_info(out)
    assert info_out["channels"] == 1
    assert info_out["sample_rate"] == 44100
    assert abs(info_out["duration_sec"] - 1.5) < 0.05


# --- Boundary: interval ends at duration ------------------------------------

def test_interval_at_end(tmp_path):
    inp = _sine_wav(tmp_path / "in.wav", duration_sec=2.0, sample_rate=44100, channels=2)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.remove_segments_with_crossfade(
        inp, out, intervals=[(1.5, 2.0)], duration_sec=2.0,
    ))
    info_out = ffprobe_info(out)
    assert info_out["channels"] == 2
    assert abs(info_out["duration_sec"] - 1.5) < 0.05


# --- Multi-interval happy path ---------------------------------------------

def test_multiple_intervals(tmp_path):
    inp = _sine_wav(tmp_path / "in.wav", duration_sec=4.0, sample_rate=44100, channels=2)
    out = tmp_path / "out.wav"
    intervals = [(0.5, 0.7), (1.2, 1.4), (2.5, 2.9)]
    _run(ffmpeg_proc.remove_segments_with_crossfade(
        inp, out, intervals=intervals, duration_sec=4.0,
    ))
    info_out = ffprobe_info(out)
    removed = sum(e - s for s, e in intervals)  # 0.8
    assert abs(info_out["duration_sec"] - (4.0 - removed)) < 0.05
    assert info_out["channels"] == 2


# --- Crossfade smoothness (DSP Chief's property) ----------------------------

def test_cut_boundary_has_no_audible_step(tmp_path):
    """After a cut, adjacent samples at the splice should not jump by more than
    a small fraction of full scale. Validates that the equal-power crossfade
    actually flattens the boundary.

    Uses a DC-offset signal: left-half at +0.6, right-half at -0.6. A hard
    splice of those would produce a 1.2 peak-to-peak step. With a 20 ms
    crossfade, max frame-to-frame delta should be well below 0.1.
    """
    sr = 44100
    duration = 1.0
    inp = tmp_path / "offset.wav"
    half = int(sr * 0.5)
    samples = np.concatenate([
        np.full(half, int(0.6 * 32767), dtype=np.int16),
        np.full(sr - half, int(-0.6 * 32767), dtype=np.int16),
    ])
    # Wrap as mono WAV via ffmpeg (easier than writing a header)
    raw = tmp_path / "offset.raw"
    raw.write_bytes(samples.tobytes())
    subprocess.run(
        ["ffmpeg", "-y", "-f", "s16le", "-ar", str(sr), "-ac", "1",
         "-i", str(raw), "-c:a", "pcm_s16le", str(inp)],
        check=True, capture_output=True, timeout=10,
    )

    out = tmp_path / "crossfaded.wav"
    # Cut across the step so the crossfade has to bridge it.
    _run(ffmpeg_proc.remove_segments_with_crossfade(
        inp, out, intervals=[(0.48, 0.52)], duration_sec=duration,
    ))

    samples_out, _sr_out, _ch = _decode_samples(out)
    flat = samples_out.flatten().astype(np.float32) / 32768.0
    # Frame-to-frame delta (sample_{n+1} - sample_n) — bounded by crossfade smoothness.
    deltas = np.abs(np.diff(flat))
    max_delta = float(deltas.max())
    # A hard splice at the DC step would give max_delta ~1.2. 20 ms equal-power
    # crossfade flattens it well below 0.1.
    assert max_delta < 0.1, f"unexpected step at cut boundary: {max_delta}"


# --- Filtergraph-script fallback ---------------------------------------------

def test_script_fallback_for_many_intervals(tmp_path, monkeypatch):
    """Force the -filter_complex_script path by lowering the inline threshold.

    Guards the fallback machinery without needing a 500-interval case.
    """
    monkeypatch.setattr(ffmpeg_proc, "_FILTERGRAPH_INLINE_MAX", 50)
    inp = _sine_wav(tmp_path / "in.wav", duration_sec=2.0, sample_rate=44100, channels=1)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.remove_segments_with_crossfade(
        inp, out, intervals=[(0.5, 0.7), (1.0, 1.2), (1.5, 1.6)], duration_sec=2.0,
    ))
    assert out.exists() and out.stat().st_size > 0


# --- Sample-rate preservation across SRs ------------------------------------

@pytest.mark.parametrize("sr", [22050, 44100, 48000])
def test_sample_rate_preserved(tmp_path, sr):
    inp = _sine_wav(tmp_path / "in.wav", duration_sec=2.0, sample_rate=sr, channels=2)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.remove_segments_with_crossfade(
        inp, out, intervals=[(0.5, 1.0)], duration_sec=2.0,
    ))
    assert ffprobe_info(out)["sample_rate"] == sr


# --- Zero-crossing snap helper (unit) ---------------------------------------

def test_snap_picks_low_energy_sample():
    """Given a stereo signal with an obvious quiet sample inside the window,
    the snap should pick it (not the target-time sample)."""
    sr = 48000
    n = sr  # 1 sec
    # Mostly loud, with a dip at the 0.5 s mark
    frames = np.full((n, 2), 20000, dtype=np.int16)
    dip_idx = sr // 2
    for k in range(-50, 51):
        frames[dip_idx + k] = [k * 10, k * 10]  # near-zero energy in this window

    snapped = ffmpeg_proc._snap_boundaries(frames, sr, [0.5005], window_ms=5.0)
    # 5 ms window at 48k = 240 samples. The dip is well within it.
    snapped_sample = int(round(snapped[0] * sr))
    assert abs(snapped_sample - dip_idx) <= 50


def test_snap_respects_bounds():
    sr = 44100
    frames = np.full((100, 1), 1000, dtype=np.int16)
    # Time way beyond the buffer: should still return a valid time without raising
    out = ffmpeg_proc._snap_boundaries(frames, sr, [10.0], window_ms=5.0)
    assert out[0] >= 0


def test_snap_disabled_returns_input():
    frames = np.full((100, 2), 1000, dtype=np.int16)
    times = [0.1, 0.2, 0.3]
    assert ffmpeg_proc._snap_boundaries(frames, 44100, times, window_ms=0) == times
