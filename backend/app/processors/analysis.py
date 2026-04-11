import asyncio
from pathlib import Path


async def detect_peak_db(audio_path: Path) -> float:
    """Detect peak amplitude in dBFS using FFmpeg astats filter.

    Uses stream processing — does not load the full file into memory.
    Returns peak level in dBFS (0.0 = full scale, negative = below).
    """
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", str(audio_path),
        "-af", "astats=metadata=0",
        "-f", "null", "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    output = stderr.decode()

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
