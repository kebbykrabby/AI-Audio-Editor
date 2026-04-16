"""DSP correctness tests targeting the V2 review's flagged risks.

Each test here guards a specific bug class the team identified:
- speed chaining for factors in [0.26, 0.49] used to crash FFmpeg
- stereo waveform used (L+R)/2 downmix instead of max(|L|,|R|)
- ops must preserve channel count and sample rate unless explicitly stated
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.processors import ffmpeg as ffmpeg_proc
from app.processors.waveform import generate_waveform

from .conftest import ffprobe_info


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Speed chaining regression (report §3 DSP + §5.1) ---------------------

@pytest.mark.parametrize("factor", [0.3, 0.4])
def test_speed_slow_factor_below_half_does_not_crash(stereo_music_wav, tmp_path, factor):
    """Factors 0.26–0.49 previously failed because atempo only accepts [0.5, 2.0].

    Chained decomposition (atempo=0.5,atempo=N) must produce a valid output of
    duration ≈ input / factor, with stereo preserved.
    """
    out = tmp_path / f"speed_{factor}.wav"
    _run(ffmpeg_proc.speed(stereo_music_wav, out, factor))

    assert out.exists() and out.stat().st_size > 0
    info_in = ffprobe_info(stereo_music_wav)
    info_out = ffprobe_info(out)
    expected_duration = info_in["duration_sec"] / factor
    # atempo isn't perfectly exact; ±5% is generous but catches order-of-magnitude bugs.
    assert abs(info_out["duration_sec"] - expected_duration) / expected_duration < 0.05
    # Stereo preservation
    assert info_out["channels"] == 2
    assert info_out["sample_rate"] == info_in["sample_rate"]


def test_speed_boundary_inclusive(stereo_music_wav, tmp_path):
    """factor=0.25 must be accepted (contract says 0.25 <= factor <= 4.0)."""
    out = tmp_path / "speed_quarter.wav"
    _run(ffmpeg_proc.speed(stereo_music_wav, out, 0.25))
    assert out.exists() and out.stat().st_size > 0


# --- Waveform stereo semantics (report §3 + §5.3) -------------------------

def test_waveform_stereo_uses_max_not_downmix(stereo_asymmetric_wav, tmp_path):
    """Stereo waveform should reflect max(|L|,|R|) per window.

    Fixture has L=880Hz full-amplitude, R=silent. A correct max() implementation
    yields high peaks. A naive (L+R)/2 downmix would halve them.
    """
    # Move fixture into a dir so waveform.json lands next to it (as in production)
    audio_dir = tmp_path / "ast_test"
    audio_dir.mkdir()
    audio_path = audio_dir / "audio.wav"
    audio_path.write_bytes(stereo_asymmetric_wav.read_bytes())

    waveform_path = _run(generate_waveform(audio_path, num_peaks=100))
    peaks = json.loads(Path(waveform_path).read_text())

    assert len(peaks) > 0
    peak_max = max(peaks)
    # A full-amplitude sine on one channel yields a peak near 1.0.
    # With the old (L+R)/2 bug it would be near 0.5.
    # Set the threshold at 0.7 — comfortably distinguishes the two regimes.
    assert peak_max > 0.7, (
        f"Expected peak > 0.7 (max(|L|,|R|) semantics); got {peak_max}. "
        "This suggests stereo downmix via (L+R)/2."
    )


def test_waveform_mono_works(tmp_path):
    """Sanity: mono input should still produce a peak array without channel-reshape errors.

    Boost the sine source with volume=8 because lavfi sine outputs at ~-18 dB by default.
    """
    import subprocess
    mono_path = tmp_path / "ast_mono" / "audio.wav"
    mono_path.parent.mkdir()
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=1:sample_rate=22050",
         "-af", "volume=8",
         "-c:a", "pcm_s16le", str(mono_path)],
        check=True, capture_output=True, timeout=10,
    )
    waveform_path = _run(generate_waveform(mono_path, num_peaks=50))
    peaks = json.loads(Path(waveform_path).read_text())
    assert len(peaks) > 0
    assert max(peaks) > 0.5


# --- Channel & sample-rate preservation property (DSP Auditor requirement) ---

@pytest.mark.parametrize("op_name", ["reverse", "gain", "fade_in"])
def test_ops_preserve_channels_and_sample_rate(stereo_music_wav, tmp_path, op_name):
    """Non-channel-changing ops must preserve channel count and sample rate.

    Guards against silent mono downmix or sample-rate drift via FFmpeg defaults.
    """
    out = tmp_path / f"{op_name}_out.wav"
    if op_name == "reverse":
        _run(ffmpeg_proc.reverse(stereo_music_wav, out))
    elif op_name == "gain":
        _run(ffmpeg_proc.gain(stereo_music_wav, out, 0))  # 0 dB: should be identity
    elif op_name == "fade_in":
        _run(ffmpeg_proc.fade_in(stereo_music_wav, out, 0.1, "linear"))

    info_in = ffprobe_info(stereo_music_wav)
    info_out = ffprobe_info(out)
    assert info_out["channels"] == info_in["channels"], f"{op_name} changed channel count"
    assert info_out["sample_rate"] == info_in["sample_rate"], f"{op_name} changed sample rate"
