"""DSP correctness tests for `censor_segments_with_beep`.

Asserts the Phase-1 contract for beep mode:
- output duration equals input duration (NOT shortened, unlike remove_segments)
- channel count + sample rate preserved
- the censored region carries the expected sine frequency (FFT check)
- the un-censored regions remain the original audio (low correlation with the beep)
- multi-region case
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


def _speech_like_wav(path: Path, *, duration_sec: float, sample_rate: int, channels: int) -> Path:
    """Generate a 440 Hz tone (mono) or 440+660 (stereo) — acts as 'speech' so the
    censored region's 1 kHz tone is distinguishable in an FFT check.
    """
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


def _dominant_freq(samples: np.ndarray, sample_rate: int) -> float:
    """Return the dominant frequency in a 1-D sample slice via FFT magnitude peak."""
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    samples = samples.astype(np.float64)
    n = len(samples)
    if n < 16:
        return 0.0
    # Hann window so the peak isn't smeared.
    window = np.hanning(n)
    spec = np.abs(np.fft.rfft(samples * window))
    # Skip DC bin (index 0).
    peak_idx = int(np.argmax(spec[1:])) + 1
    return peak_idx * sample_rate / n


# --- Happy path: single beep replaces middle region -------------------------

def test_single_beep_preserves_duration_and_format(tmp_path):
    inp = _speech_like_wav(tmp_path / "in.wav", duration_sec=2.0, sample_rate=48000, channels=2)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.censor_segments_with_beep(
        inp, out, intervals=[(0.8, 1.2)], duration_sec=2.0, beep_hz=1000,
    ))
    info_in = ffprobe_info(inp)
    info_out = ffprobe_info(out)
    # Duration unchanged: this is censorship, not removal.
    assert abs(info_out["duration_sec"] - info_in["duration_sec"]) < 0.05
    assert info_out["channels"] == info_in["channels"]
    assert info_out["sample_rate"] == info_in["sample_rate"]


def test_beep_replaces_audio_at_correct_frequency(tmp_path):
    """The censored region should be dominated by the chosen beep frequency."""
    inp = _speech_like_wav(tmp_path / "in.wav", duration_sec=2.0, sample_rate=44100, channels=1)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.censor_segments_with_beep(
        inp, out, intervals=[(0.5, 1.0)], duration_sec=2.0, beep_hz=1000,
    ))

    frames, sr, _ = _decode_samples(out)
    # Sample a chunk well inside the beep window to avoid the fade edges.
    start = int(0.65 * sr)
    end = int(0.85 * sr)
    beep_chunk = frames[start:end]
    dom = _dominant_freq(beep_chunk, sr)
    # Allow a generous tolerance (FFT bin width grows with chunk length).
    assert abs(dom - 1000) < 30, f"Beep dominant freq {dom} Hz != 1000 Hz"


def test_non_censored_region_keeps_original_freq(tmp_path):
    """Regions outside [start, end] must remain the original audio."""
    inp = _speech_like_wav(tmp_path / "in.wav", duration_sec=2.0, sample_rate=44100, channels=1)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.censor_segments_with_beep(
        inp, out, intervals=[(0.5, 1.0)], duration_sec=2.0, beep_hz=1000,
    ))

    frames, sr, _ = _decode_samples(out)
    # Sample 200 ms in — well before the censored window.
    start = int(0.05 * sr)
    end = int(0.30 * sr)
    pre_chunk = frames[start:end]
    dom = _dominant_freq(pre_chunk, sr)
    # Input was 440 Hz sine; the pre-beep region must still be ~440 Hz.
    assert abs(dom - 440) < 25, f"Pre-beep dominant freq {dom} Hz != 440 Hz"


# --- Multiple intervals -----------------------------------------------------

def test_multiple_intervals_all_carry_beep(tmp_path):
    inp = _speech_like_wav(tmp_path / "in.wav", duration_sec=3.0, sample_rate=44100, channels=1)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.censor_segments_with_beep(
        inp, out,
        intervals=[(0.4, 0.8), (1.4, 1.8), (2.2, 2.6)],
        duration_sec=3.0, beep_hz=1000,
    ))
    frames, sr, _ = _decode_samples(out)

    for center_sec in [0.6, 1.6, 2.4]:
        start = int((center_sec - 0.08) * sr)
        end = int((center_sec + 0.08) * sr)
        dom = _dominant_freq(frames[start:end], sr)
        assert abs(dom - 1000) < 40, f"Beep at ~{center_sec}s = {dom} Hz, expected ~1000 Hz"


# --- Custom frequency -------------------------------------------------------

@pytest.mark.parametrize("beep_hz", [500, 2000, 4000])
def test_custom_beep_frequency(tmp_path, beep_hz):
    inp = _speech_like_wav(tmp_path / "in.wav", duration_sec=2.0, sample_rate=48000, channels=1)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.censor_segments_with_beep(
        inp, out, intervals=[(0.5, 1.2)], duration_sec=2.0, beep_hz=beep_hz,
    ))
    frames, sr, _ = _decode_samples(out)
    start = int(0.7 * sr)
    end = int(1.0 * sr)
    dom = _dominant_freq(frames[start:end], sr)
    assert abs(dom - beep_hz) < 40, f"At {beep_hz} Hz target, got {dom} Hz"


# --- Boundary case: empty intervals raises ----------------------------------

def test_empty_intervals_raises(tmp_path):
    inp = _speech_like_wav(tmp_path / "in.wav", duration_sec=1.0, sample_rate=44100, channels=1)
    out = tmp_path / "out.wav"
    with pytest.raises(ValueError):
        _run(ffmpeg_proc.censor_segments_with_beep(
            inp, out, intervals=[], duration_sec=1.0,
        ))


# --- Boundary case: interval covers the whole file --------------------------

def test_full_file_beep(tmp_path):
    """Edge case where the entire file becomes beep — should still produce
    valid audio of the same duration."""
    inp = _speech_like_wav(tmp_path / "in.wav", duration_sec=1.0, sample_rate=44100, channels=1)
    out = tmp_path / "out.wav"
    _run(ffmpeg_proc.censor_segments_with_beep(
        inp, out, intervals=[(0.0, 1.0)], duration_sec=1.0, beep_hz=1000,
    ))
    info = ffprobe_info(out)
    assert abs(info["duration_sec"] - 1.0) < 0.05
