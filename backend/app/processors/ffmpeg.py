import asyncio
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProcessingResult:
    success: bool
    warning: str | None = None


async def _run_ffmpeg(*args: str, timeout: float = 30) -> None:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {stderr.decode()[-500:]}")


async def _probe(path: Path) -> dict:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    return json.loads(stdout)


async def probe_audio(path: Path) -> dict:
    """Return {duration_sec, sample_rate, channels} for an audio file."""
    info = await _probe(path)
    stream = next(
        (s for s in info.get("streams", []) if s["codec_type"] == "audio"), None
    )
    if not stream:
        raise RuntimeError("No audio stream found")
    return {
        "duration_sec": float(info["format"]["duration"]),
        "sample_rate": int(stream["sample_rate"]),
        "channels": int(stream["channels"]),
    }


async def _detect_clipping(path: Path) -> bool:
    """Check if audio clips (peak > 0 dBFS) using FFmpeg astats."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", str(path),
        "-af", "astats=metadata=1:reset=0,ametadata=print:key=lavfi.astats.Overall.Peak_level",
        "-f", "null", "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    output = stderr.decode()
    for line in output.split("\n"):
        if "Peak_level" in line:
            try:
                val = float(line.split("=")[-1].strip())
                if val >= 0.0:
                    return True
            except ValueError:
                pass
    return False


async def trim(input_path: Path, output_path: Path, start_sec: float, end_sec: float) -> ProcessingResult:
    await _run_ffmpeg(
        "-i", str(input_path),
        "-af", f"atrim=start={start_sec}:end={end_sec},asetpts=N/SR/TB",
        str(output_path),
    )
    return ProcessingResult(success=True)


async def delete(input_path: Path, output_path: Path, start_sec: float, end_sec: float) -> ProcessingResult:
    # Keep [0, start) and [end, inf), concatenate
    if start_sec == 0:
        # Nothing before the cut — just keep [end, inf)
        await _run_ffmpeg(
            "-i", str(input_path),
            "-af", f"atrim=start={end_sec},asetpts=N/SR/TB",
            str(output_path),
        )
    else:
        # Probe duration to detect if end_sec reaches the file end
        info = await _probe(input_path)
        file_duration = float(info["format"]["duration"])
        if end_sec >= file_duration:
            # Nothing after the cut — just keep [0, start)
            await _run_ffmpeg(
                "-i", str(input_path),
                "-af", f"atrim=end={start_sec},asetpts=N/SR/TB",
                str(output_path),
            )
        else:
            await _run_ffmpeg(
                "-i", str(input_path),
                "-filter_complex",
                f"[0:a]atrim=end={start_sec},asetpts=N/SR/TB[a];"
                f"[0:a]atrim=start={end_sec},asetpts=N/SR/TB[b];"
                f"[a][b]concat=n=2:v=0:a=1[out]",
                "-map", "[out]",
                str(output_path),
            )
    return ProcessingResult(success=True)


async def fade_in(input_path: Path, output_path: Path, duration_sec: float, curve: str = "linear") -> ProcessingResult:
    curve_type = "exp" if curve == "exponential" else "tri"
    await _run_ffmpeg(
        "-i", str(input_path),
        "-af", f"afade=t=in:st=0:d={duration_sec}:curve={curve_type}",
        str(output_path),
    )
    return ProcessingResult(success=True)


async def fade_out(
    input_path: Path, output_path: Path,
    duration_sec: float, audio_duration: float, curve: str = "linear",
) -> ProcessingResult:
    start = audio_duration - duration_sec
    curve_type = "exp" if curve == "exponential" else "tri"
    await _run_ffmpeg(
        "-i", str(input_path),
        "-af", f"afade=t=out:st={start}:d={duration_sec}:curve={curve_type}",
        str(output_path),
    )
    return ProcessingResult(success=True)


async def gain(input_path: Path, output_path: Path, gain_db: float) -> ProcessingResult:
    await _run_ffmpeg(
        "-i", str(input_path),
        "-af", f"volume={gain_db}dB",
        str(output_path),
    )
    warning = None
    if await _detect_clipping(output_path):
        warning = "Output audio clips at 0 dBFS. Consider reducing gain."
    return ProcessingResult(success=True, warning=warning)


async def export_audio(
    input_path: Path, output_path: Path,
    fmt: str, sample_rate: int | None = None, bitrate_kbps: int | None = None,
) -> ProcessingResult:
    args = ["-i", str(input_path)]
    if sample_rate:
        args.extend(["-ar", str(sample_rate)])
    if fmt == "wav":
        args.extend(["-acodec", "pcm_s16le"])
    elif fmt == "mp3":
        args.extend(["-acodec", "libmp3lame"])
        if bitrate_kbps:
            args.extend(["-b:a", f"{bitrate_kbps}k"])
    args.append(str(output_path))
    await _run_ffmpeg(*args)
    return ProcessingResult(success=True)
