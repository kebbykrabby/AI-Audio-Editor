import asyncio
import json
import subprocess
from pathlib import Path

import numpy as np


async def generate_waveform(audio_path: Path, num_peaks: int = 1800) -> Path:
    """Generate waveform peaks from audio using FFmpeg.

    Decodes audio to raw PCM via FFmpeg, then computes peaks.
    For stereo: max(abs(L), abs(R)) per window.
    Saves as JSON array of floats (0.0 to 1.0).
    """
    waveform_path = audio_path.parent / "waveform.json"

    def _decode():
        return subprocess.run(
            ["ffmpeg", "-i", str(audio_path),
             "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1",
             "-ar", "22050", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _decode)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg waveform decode failed: {result.stderr.decode()}")

    raw_data = result.stdout

    if not raw_data:
        waveform_path.write_text(json.dumps([]))
        return waveform_path

    # Convert raw bytes to numpy array of int16
    samples = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32)

    # Compute peaks
    window_size = max(1, len(samples) // num_peaks)
    peaks = []
    for i in range(0, len(samples), window_size):
        window = samples[i : i + window_size]
        peak = float(np.max(np.abs(window))) / 32768.0
        peaks.append(round(peak, 4))

    # Trim to exact num_peaks
    peaks = peaks[:num_peaks]

    waveform_path.write_text(json.dumps(peaks))
    return waveform_path
