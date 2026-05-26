import asyncio
import subprocess
from pathlib import Path


async def detect_peak_db(audio_path: Path) -> float:
    """Detect peak amplitude in dBFS using FFmpeg astats filter.

    Uses stream processing — does not load the full file into memory.
    Returns peak level in dBFS (0.0 = full scale, negative = below).
    """
    def _run():
        return subprocess.run(
            ["ffmpeg", "-i", str(audio_path),
             "-af", "astats=metadata=0",
             "-f", "null", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run)
    output = result.stderr.decode()

    for line in output.split("\n"):
        if "Peak level dB" in line:
            try:
                val = float(line.split(":")[-1].strip())
                if val == float("-inf"):
                    return -60.0
                return val
            except ValueError:
                pass

    return -60.0
