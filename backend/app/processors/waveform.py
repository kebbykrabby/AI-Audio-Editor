import asyncio
import json
import subprocess
from pathlib import Path

import numpy as np


async def generate_waveform(audio_path: Path, num_peaks: int = 1800) -> Path:
    """Generate waveform peaks from audio using FFmpeg.

    Decodes audio to raw PCM via FFmpeg, then computes peaks.
    For stereo: max(abs(L), abs(R)) per window.
    For mono: abs per window.
    Saves as JSON array of floats (0.0 to 1.0).
    """
    waveform_path = audio_path.parent / "waveform.json"

    # Probe channel count so we can decode at native channel layout
    def _probe_channels():
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", str(audio_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        info = json.loads(result.stdout)
        for s in info.get("streams", []):
            if s.get("codec_type") == "audio":
                return int(s.get("channels", 1))
        return 1

    loop = asyncio.get_event_loop()
    channels = await loop.run_in_executor(None, _probe_channels)

    def _decode():
        return subprocess.run(
            ["ffmpeg", "-i", str(audio_path),
             "-f", "s16le", "-acodec", "pcm_s16le",
             "-ar", "22050", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )

    result = await loop.run_in_executor(None, _decode)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg waveform decode failed: {result.stderr.decode()}")

    raw_data = result.stdout

    if not raw_data:
        waveform_path.write_text(json.dumps([]))
        return waveform_path

    # Convert raw bytes to numpy array of int16
    samples = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32)

    if channels >= 2:
        # Interleaved s16le: [L0, R0, L1, R1, ...]. Reshape to (frames, channels).
        usable = len(samples) - (len(samples) % channels)
        samples = samples[:usable]
        frames = samples.reshape(-1, channels)
        # max(abs(L), abs(R)) per frame — single combined envelope
        samples = np.max(np.abs(frames), axis=1)
    else:
        samples = np.abs(samples)

    # Compute peaks per window
    window_size = max(1, len(samples) // num_peaks)
    peaks = []
    for i in range(0, len(samples), window_size):
        window = samples[i : i + window_size]
        peak = float(np.max(window)) / 32768.0
        peaks.append(round(peak, 4))

    # Trim to exact num_peaks
    peaks = peaks[:num_peaks]

    waveform_path.write_text(json.dumps(peaks))
    return waveform_path
