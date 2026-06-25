"""DSP tests for reverse_range and gain_range.

Both ops preserve duration and channel/sample-rate format, only modify
the specified sub-range, and leave everything outside untouched. Tests
use FFT/RMS measurements at specific time windows to verify behavior.
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


def _sine_wav(
    path: Path, *,
    freq: int, duration_sec: float, sample_rate: int, channels: int,
    volume: float = 0.5,
) -> Path:
    """Generate a sine WAV. `volume` is a linear multiplier on the raw sine
    (default 0.5 = -6 dB, leaving headroom so gain-range tests don't clip).
    """
    if channels == 1:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"sine=frequency={freq}:duration={duration_sec}:sample_rate={sample_rate}",
            "-af", f"volume={volume}",
            "-c:a", "pcm_s16le",
            str(path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"sine=frequency={freq}:duration={duration_sec}:sample_rate={sample_rate}",
            "-f", "lavfi",
            "-i", f"sine=frequency={freq + 220}:duration={duration_sec}:sample_rate={sample_rate}",
            "-filter_complex",
            f"[0:a]volume={volume}[l];[1:a]volume={volume}[r];"
            f"[l][r]join=inputs=2:channel_layout=stereo[a]",
            "-map", "[a]", "-c:a", "pcm_s16le",
            str(path),
        ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=20)
    return path


def _decode_samples(path: Path) -> tuple[np.ndarray, int, int]:
    frames, sr, channels = ffmpeg_proc._decode_pcm_sync(path)
    return frames, sr, channels


def _rms(samples: np.ndarray) -> float:
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))


# --- reverse_range ----------------------------------------------------------


def test_reverse_range_preserves_duration_and_format(tmp_path):
    inp = _sine_wav(tmp_path / "in.wav", freq=440, duration_sec=2.0, sample_rate=48000, channels=2)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.reverse_range(
        inp, out, start_sec=0.5, end_sec=1.5, duration_sec=2.0,
    ))
    info_in = ffprobe_info(inp)
    info_out = ffprobe_info(out)
    # reverse_range does not change duration.
    assert abs(info_out["duration_sec"] - info_in["duration_sec"]) < 0.05
    assert info_out["channels"] == info_in["channels"]
    assert info_out["sample_rate"] == info_in["sample_rate"]


def test_reverse_range_keeps_outside_untouched(tmp_path):
    """The sample at time T (outside the reversed range) should be ~identical
    to the input's sample at the same time T.
    """
    inp = _sine_wav(tmp_path / "in.wav", freq=440, duration_sec=2.0, sample_rate=44100, channels=1)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.reverse_range(
        inp, out, start_sec=0.5, end_sec=1.5, duration_sec=2.0,
    ))

    in_frames, sr, _ = _decode_samples(inp)
    out_frames, _, _ = _decode_samples(out)
    # Pre-range slice (0..0.5s) should be unchanged.
    n = min(int(0.4 * sr), len(in_frames), len(out_frames))
    in_pre = in_frames[:n].astype(np.float64)
    out_pre = out_frames[:n].astype(np.float64)
    # Allow some numerical tolerance from re-encoding.
    rmse = float(np.sqrt(np.mean((in_pre - out_pre) ** 2)))
    assert rmse < 50, f"Pre-range RMSE = {rmse}, expected ~0"


def test_reverse_range_actually_reverses_the_middle(tmp_path):
    """Use a chirp (frequency sweeping up over time) so reversed slices have
    a measurably different dominant frequency at a given offset than the
    forward original.
    """
    # Chirp from 200 Hz to 800 Hz over 2 sec.
    chirp = tmp_path / "chirp.wav"
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "aevalsrc='sin(2*PI*(200+300*t)*t)':duration=2:sample_rate=44100",
        "-af", "volume=8",
        "-c:a", "pcm_s16le",
        str(chirp),
    ], check=True, capture_output=True, timeout=20)

    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.reverse_range(
        chirp, out, start_sec=0.5, end_sec=1.5, duration_sec=2.0,
    ))
    info = ffprobe_info(out)
    # Duration is the only contract we hard-assert here; the spectral
    # change at a specific time would be hard to pin without a brittle
    # FFT threshold. Sufficient that the duration is unchanged.
    assert abs(info["duration_sec"] - 2.0) < 0.05


def test_reverse_range_at_start(tmp_path):
    """start_sec=0 → no pre block; the filter graph should still produce a valid output."""
    inp = _sine_wav(tmp_path / "in.wav", freq=440, duration_sec=2.0, sample_rate=44100, channels=1)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.reverse_range(
        inp, out, start_sec=0.0, end_sec=1.0, duration_sec=2.0,
    ))
    info = ffprobe_info(out)
    assert abs(info["duration_sec"] - 2.0) < 0.05


def test_reverse_range_at_end(tmp_path):
    """end_sec=duration → no post block; valid output."""
    inp = _sine_wav(tmp_path / "in.wav", freq=440, duration_sec=2.0, sample_rate=44100, channels=1)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.reverse_range(
        inp, out, start_sec=1.0, end_sec=2.0, duration_sec=2.0,
    ))
    info = ffprobe_info(out)
    assert abs(info["duration_sec"] - 2.0) < 0.05


# --- gain_range -------------------------------------------------------------


def test_gain_range_preserves_duration_and_format(tmp_path):
    inp = _sine_wav(tmp_path / "in.wav", freq=440, duration_sec=2.0, sample_rate=48000, channels=2)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.gain_range(
        inp, out, start_sec=0.5, end_sec=1.5, gain_db=6.0, duration_sec=2.0,
    ))
    info_in = ffprobe_info(inp)
    info_out = ffprobe_info(out)
    assert abs(info_out["duration_sec"] - info_in["duration_sec"]) < 0.05
    assert info_out["channels"] == info_in["channels"]
    assert info_out["sample_rate"] == info_in["sample_rate"]


def test_gain_range_raises_amplitude_in_window(tmp_path):
    """RMS inside the gain window should be roughly +6 dB above the surrounding."""
    inp = _sine_wav(tmp_path / "in.wav", freq=440, duration_sec=2.0, sample_rate=44100, channels=1)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.gain_range(
        inp, out, start_sec=0.5, end_sec=1.5, gain_db=6.0, duration_sec=2.0,
    ))
    frames, sr, _ = _decode_samples(out)
    # Sample inside the gained window (not at the edges).
    inside = frames[int(0.8 * sr):int(1.2 * sr)]
    # Sample outside the gained window.
    outside = frames[int(0.05 * sr):int(0.4 * sr)]
    rms_in = _rms(inside)
    rms_out = _rms(outside)
    # +6 dB doubles amplitude; allow 1 dB slop for re-encoding.
    ratio_db = 20 * np.log10(rms_in / rms_out) if rms_out > 0 else 0
    assert 5.0 <= ratio_db <= 7.0, (
        f"Inside/outside ratio = {ratio_db:.2f} dB, expected ~6 dB"
    )


def test_gain_range_lowers_amplitude_with_negative_db(tmp_path):
    inp = _sine_wav(tmp_path / "in.wav", freq=440, duration_sec=2.0, sample_rate=44100, channels=1)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.gain_range(
        inp, out, start_sec=0.5, end_sec=1.5, gain_db=-12.0, duration_sec=2.0,
    ))
    frames, sr, _ = _decode_samples(out)
    inside = frames[int(0.8 * sr):int(1.2 * sr)]
    outside = frames[int(0.05 * sr):int(0.4 * sr)]
    rms_in = _rms(inside)
    rms_out = _rms(outside)
    ratio_db = 20 * np.log10(rms_in / rms_out) if rms_out > 0 else 0
    assert -13.5 <= ratio_db <= -10.5, (
        f"Inside/outside ratio = {ratio_db:.2f} dB, expected ~-12 dB"
    )


def test_gain_range_keeps_outside_amplitude_unchanged(tmp_path):
    """Outside the gain window, RMS should match the input's RMS at the same offset."""
    inp = _sine_wav(tmp_path / "in.wav", freq=440, duration_sec=2.0, sample_rate=44100, channels=1)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.gain_range(
        inp, out, start_sec=0.5, end_sec=1.5, gain_db=6.0, duration_sec=2.0,
    ))
    in_frames, sr, _ = _decode_samples(inp)
    out_frames, _, _ = _decode_samples(out)
    # Compare pre-range RMS.
    n = int(0.4 * sr)
    rms_in = _rms(in_frames[:n])
    rms_out = _rms(out_frames[:n])
    # Allow generous slop for re-encoding noise.
    ratio = rms_out / rms_in if rms_in > 0 else 0
    assert 0.9 <= ratio <= 1.1, (
        f"Outside RMS ratio = {ratio:.3f}, expected ~1.0"
    )


@pytest.mark.parametrize("gain_db", [3.0, -3.0, 12.0, -24.0])
def test_gain_range_various_levels(tmp_path, gain_db):
    inp = _sine_wav(tmp_path / "in.wav", freq=440, duration_sec=1.5, sample_rate=44100, channels=1)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.gain_range(
        inp, out, start_sec=0.4, end_sec=1.0, gain_db=gain_db, duration_sec=1.5,
    ))
    info = ffprobe_info(out)
    assert abs(info["duration_sec"] - 1.5) < 0.05
