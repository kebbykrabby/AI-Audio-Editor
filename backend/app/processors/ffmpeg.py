import asyncio
import json
import subprocess
from dataclasses import dataclass
from functools import partial
from pathlib import Path


@dataclass
class ProcessingResult:
    success: bool
    warning: str | None = None


def _run_ffmpeg_sync(*args: str, timeout: float = 30) -> None:
    result = subprocess.run(
        ["ffmpeg", "-y", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {result.stderr.decode()[-500:]}")


async def _run_ffmpeg(*args: str, timeout: float = 30) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, partial(_run_ffmpeg_sync, *args, timeout=timeout))


def _probe_sync(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    return json.loads(result.stdout)


async def _probe(path: Path) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _probe_sync, path)


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
    def _run():
        return subprocess.run(
            ["ffmpeg", "-i", str(path),
             "-af", "astats=metadata=1:reset=0,ametadata=print:key=lavfi.astats.Overall.Peak_level",
             "-f", "null", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run)
    output = result.stderr.decode()
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


async def reverse(input_path: Path, output_path: Path) -> ProcessingResult:
    await _run_ffmpeg(
        "-i", str(input_path),
        "-af", "areverse",
        str(output_path),
    )
    return ProcessingResult(success=True)


async def remove_silence(
    input_path: Path, output_path: Path,
    threshold_db: float = -40, min_silence_sec: float = 0.5,
) -> ProcessingResult:
    af = (
        f"silenceremove="
        f"start_periods=1:start_duration={min_silence_sec}:start_threshold={threshold_db}dB:"
        f"stop_periods=-1:stop_duration={min_silence_sec}:stop_threshold={threshold_db}dB"
    )
    await _run_ffmpeg(
        "-i", str(input_path),
        "-af", af,
        str(output_path),
    )
    return ProcessingResult(success=True)


async def extract_channel(input_path: Path, output_path: Path, channel: str) -> ProcessingResult:
    pan_filter = "pan=mono|c0=c0" if channel == "left" else "pan=mono|c0=c1"
    await _run_ffmpeg(
        "-i", str(input_path),
        "-af", pan_filter,
        str(output_path),
    )
    return ProcessingResult(success=True)


async def swap_channels(input_path: Path, output_path: Path) -> ProcessingResult:
    await _run_ffmpeg(
        "-i", str(input_path),
        "-af", "pan=stereo|c0=c1|c1=c0",
        str(output_path),
    )
    return ProcessingResult(success=True)


async def mono_mixdown(input_path: Path, output_path: Path) -> ProcessingResult:
    await _run_ffmpeg(
        "-i", str(input_path),
        "-ac", "1",
        str(output_path),
    )
    return ProcessingResult(success=True)


async def speed(input_path: Path, output_path: Path, factor: float) -> ProcessingResult:
    # FFmpeg atempo accepts [0.5, 2.0]. Chain filters for factors outside this range.
    parts: list[str] = []
    remaining = factor
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    parts.append(f"atempo={remaining}")
    af = ",".join(parts)
    await _run_ffmpeg(
        "-i", str(input_path),
        "-af", af,
        str(output_path),
    )
    return ProcessingResult(success=True)


async def split_channels(
    input_path: Path, left_output: Path, right_output: Path,
) -> ProcessingResult:
    await _run_ffmpeg(
        "-i", str(input_path),
        "-af", "pan=mono|c0=c0",
        str(left_output),
    )
    await _run_ffmpeg(
        "-i", str(input_path),
        "-af", "pan=mono|c0=c1",
        str(right_output),
    )
    return ProcessingResult(success=True)


async def merge_channels(
    left_path: Path, right_path: Path, output_path: Path,
) -> ProcessingResult:
    await _run_ffmpeg(
        "-i", str(left_path),
        "-i", str(right_path),
        "-filter_complex", "[0:a][1:a]join=inputs=2:channel_layout=stereo[out]",
        "-map", "[out]",
        str(output_path),
    )
    return ProcessingResult(success=True)
