import asyncio
import json
import subprocess
import tempfile
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np


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


# ============================================================================
# Multi-segment removal with equal-power crossfades
# ----------------------------------------------------------------------------
# DSP Chief's policy: 20 ms equal-power (curve=hsin) crossfade at each cut
# boundary, ±5 ms zero-crossing snap, adjacent-interval merging handled by the
# caller. Filtergraph is the combination of existing primitives (atrim, afade,
# concat) — no new DSP. See docs/ai-integration-context.md §9.
# ============================================================================

# Maximum filtergraph size (bytes) passed directly as a CLI arg. Above this we
# write to a temp file and use -filter_complex_script to sidestep shell limits.
_FILTERGRAPH_INLINE_MAX = 4000


def _build_apply_to_range_filtergraph(
    start_sec: float,
    end_sec: float,
    duration_sec: float,
    range_filter: str,
) -> str:
    """Filtergraph that splits the input audio into [0..start, start..end,
    end..duration], applies `range_filter` to the middle, and concats
    everything back. Output duration equals input duration.

    `range_filter` is a comma-separated FFmpeg filter expression applied to
    just the middle range (no leading/trailing commas), e.g., "areverse" or
    "volume=3dB".

    Edge cases handled:
    - start_sec == 0    → no pre section
    - end_sec   == duration_sec → no post section
    - both → equivalent to applying `range_filter` to the whole asset
    """
    parts: list[str] = []
    labels: list[str] = []

    if start_sec > 0:
        parts.append(f"[0:a]atrim=0:{start_sec},asetpts=N/SR/TB[pre]")
        labels.append("[pre]")

    parts.append(
        f"[0:a]atrim={start_sec}:{end_sec},asetpts=N/SR/TB,{range_filter}[mid]"
    )
    labels.append("[mid]")

    if end_sec < duration_sec:
        parts.append(f"[0:a]atrim={end_sec},asetpts=N/SR/TB[post]")
        labels.append("[post]")

    concat = "".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]"
    return ";".join(parts + [concat])


async def reverse_range(
    input_path: Path,
    output_path: Path,
    start_sec: float,
    end_sec: float,
    duration_sec: float,
) -> ProcessingResult:
    """Reverse just the audio in [start_sec, end_sec]; leave the rest unchanged.
    Output duration equals input duration.

    Contract (caller-enforced): 0 <= start_sec < end_sec <= duration_sec.
    """
    fg = _build_apply_to_range_filtergraph(
        start_sec, end_sec, duration_sec, "areverse",
    )
    await _run_ffmpeg(
        "-i", str(input_path),
        "-filter_complex", fg,
        "-map", "[out]",
        str(output_path),
        timeout=600,
    )
    return ProcessingResult(success=True)


async def gain_range(
    input_path: Path,
    output_path: Path,
    start_sec: float,
    end_sec: float,
    gain_db: float,
    duration_sec: float,
) -> ProcessingResult:
    """Adjust volume by gain_db only in [start_sec, end_sec]; leave the rest
    unchanged. Output duration equals input duration.

    Contract (caller-enforced): 0 <= start_sec < end_sec <= duration_sec.
    """
    fg = _build_apply_to_range_filtergraph(
        start_sec, end_sec, duration_sec, f"volume={gain_db}dB",
    )
    await _run_ffmpeg(
        "-i", str(input_path),
        "-filter_complex", fg,
        "-map", "[out]",
        str(output_path),
        timeout=600,
    )
    return ProcessingResult(success=True)


def _decode_pcm_sync(input_path: Path) -> tuple[np.ndarray, int, int]:
    """Decode the full audio stream to interleaved s16le PCM at native SR and
    channel count. Returns (samples_as_2D[frames, channels], sample_rate, channels).
    """
    # Probe first so we decode at the input's native parameters.
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", str(input_path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
    )
    info = json.loads(probe.stdout)
    stream = next(s for s in info["streams"] if s["codec_type"] == "audio")
    sample_rate = int(stream["sample_rate"])
    channels = int(stream["channels"])

    result = subprocess.run(
        ["ffmpeg", "-i", str(input_path),
         "-f", "s16le", "-acodec", "pcm_s16le",
         "-ar", str(sample_rate), "-ac", str(channels),
         "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"PCM decode failed: {result.stderr.decode()[-500:]}")

    raw = np.frombuffer(result.stdout, dtype=np.int16)
    usable = len(raw) - (len(raw) % channels)
    frames = raw[:usable].reshape(-1, channels)
    return frames, sample_rate, channels


def _snap_boundaries(
    frames: np.ndarray, sample_rate: int, times_sec: list[float], window_ms: float
) -> list[float]:
    """For each time, return the nearest sample within ±window_ms whose summed
    absolute amplitude across channels is minimal. Equivalent to a zero-crossing
    search in the multi-channel sense (DSP Auditor's spec: argmin(|L|+|R|)).

    A zero-amplitude crossing isn't always present; falling back to argmin
    guarantees a valid choice and still minimizes the residual step at the cut.
    """
    if window_ms <= 0 or len(frames) == 0:
        return list(times_sec)

    total_frames = frames.shape[0]
    window_half = int(round(window_ms * 1e-3 * sample_rate))
    # Pre-compute energy per frame once — avoids repeated np.abs for dense intervals.
    energy = np.abs(frames).sum(axis=1) if frames.ndim == 2 else np.abs(frames)

    snapped: list[float] = []
    for t in times_sec:
        center = int(round(t * sample_rate))
        lo = max(0, center - window_half)
        hi = min(total_frames, center + window_half + 1)
        if hi <= lo:
            snapped.append(t)
            continue
        rel = int(np.argmin(energy[lo:hi]))
        snapped.append((lo + rel) / sample_rate)
    return snapped


def _build_remove_segments_filtergraph(
    keepers: list[tuple[float, float, bool, bool]], crossfade_sec: float
) -> str:
    """Build the `-filter_complex` expression for a list of keeper segments.

    Each keeper is (start_sec, end_sec, fade_in, fade_out). fade_in is True when
    a cut immediately precedes the segment; fade_out is True when a cut
    immediately follows it.
    """
    parts: list[str] = []
    labels: list[str] = []
    for i, (a, b, fi, fo) in enumerate(keepers):
        seg_duration = b - a
        chain = [f"[0:a]atrim=start={a}:end={b}", "asetpts=N/SR/TB"]
        if fi:
            chain.append(f"afade=t=in:st=0:d={crossfade_sec}:curve=hsin")
        if fo:
            fade_out_start = max(0.0, seg_duration - crossfade_sec)
            chain.append(f"afade=t=out:st={fade_out_start}:d={crossfade_sec}:curve=hsin")
        label = f"[seg{i}]"
        labels.append(label)
        parts.append(",".join(chain) + label)
    concat = "".join(labels) + f"concat=n={len(keepers)}:v=0:a=1[out]"
    return ";".join(parts + [concat])


def _build_censor_beep_filtergraph(
    intervals: list[tuple[float, float]],
    duration_sec: float,
    beep_hz: int,
    channels: int,
    sample_rate: int,
    edge_fade_sec: float = 0.005,
    volume_db: float = -6.0,
) -> str:
    """Filtergraph that replaces each interval with a sine beep of the same
    duration; output duration equals input duration.

    Sine source is shaped to match the input's channel count and sample rate
    so the concat doesn't need format coercion downstream. A tiny equal-power
    fade-in/out (5 ms by default) on each beep edge prevents audible clicks
    at the boundary with the surrounding speech.
    """
    parts: list[str] = []
    labels: list[str] = []
    channel_layout = "stereo" if channels >= 2 else "mono"

    cursor = 0.0
    for i, (s, e) in enumerate(intervals):
        if s > cursor:
            label = f"[orig{i}]"
            parts.append(f"[0:a]atrim=start={cursor}:end={s},asetpts=N/SR/TB{label}")
            labels.append(label)
        beep_label = f"[beep{i}]"
        beep_dur = e - s
        fade_out_start = max(0.0, beep_dur - edge_fade_sec)
        sine_chain = (
            f"sine=frequency={beep_hz}:sample_rate={sample_rate}:duration={beep_dur},"
            f"aformat=channel_layouts={channel_layout},"
            f"volume={volume_db}dB,"
            f"afade=t=in:st=0:d={edge_fade_sec}:curve=hsin,"
            f"afade=t=out:st={fade_out_start}:d={edge_fade_sec}:curve=hsin"
        )
        parts.append(f"{sine_chain}{beep_label}")
        labels.append(beep_label)
        cursor = e

    if cursor < duration_sec:
        label = "[orig_end]"
        parts.append(f"[0:a]atrim=start={cursor},asetpts=N/SR/TB{label}")
        labels.append(label)

    concat = "".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]"
    return ";".join(parts + [concat])


def _build_censor_mute_filtergraph(
    intervals: list[tuple[float, float]],
    edge_fade_sec: float = 0.005,
) -> str:
    """Filtergraph that mutes each interval to silence; output duration unchanged.

    A tiny equal-power fade on each boundary prevents the abrupt amplitude
    discontinuity that would otherwise pop. The fades are inward (eat 5 ms off
    each end of the muted region) — the listener loses 10 ms of speech around
    each cut, which is inaudible at this scale.
    """
    if not intervals:
        return "anull"
    # Chain a volume=enable filter per interval with a hard mute, plus inward
    # afade at each boundary so the click is shaped instead of stepped.
    parts: list[str] = []
    for s, e in intervals:
        # Hard mute window
        parts.append(f"volume=enable='between(t,{s},{e})':volume=0")
        # Fade-out into the muted region (last 5 ms before s)
        fo_start = max(0.0, s - edge_fade_sec)
        parts.append(
            f"afade=enable='between(t,{fo_start},{s})':"
            f"t=out:st={fo_start}:d={edge_fade_sec}:curve=hsin"
        )
        # Fade-in out of the muted region (first 5 ms after e)
        parts.append(
            f"afade=enable='between(t,{e},{e + edge_fade_sec})':"
            f"t=in:st={e}:d={edge_fade_sec}:curve=hsin"
        )
    return ",".join(parts)


async def censor_segments_with_mute(
    input_path: Path,
    output_path: Path,
    intervals: list[tuple[float, float]],
    duration_sec: float,
) -> ProcessingResult:
    """Replace each interval with silence; output duration unchanged.

    Contract (caller-enforced): intervals sorted, non-overlapping, within
    [0, duration_sec], len(intervals) >= 1.
    """
    if not intervals:
        raise ValueError("intervals must be non-empty")
    _ = duration_sec  # signature parity with the other censor modes
    filtergraph = _build_censor_mute_filtergraph(intervals)
    await _run_ffmpeg(
        "-i", str(input_path),
        "-af", filtergraph,
        str(output_path),
        timeout=600,
    )
    return ProcessingResult(success=True)


def _build_censor_reverse_pitch_filtergraph(
    intervals: list[tuple[float, float]],
    duration_sec: float,
    channels: int,
    pitch_factor: float = 0.85,
    edge_fade_sec: float = 0.005,
) -> str:
    """Filtergraph that reverses + pitch-shifts each interval; output duration
    unchanged.

    The trick: `asetrate=SR*F,aresample=SR` shifts pitch by factor F while
    changing duration by 1/F. `atempo=1/F` then compensates the duration so
    the per-region output stays the same length as the input. Combined with
    `areverse`, the censored word becomes a brief unintelligible sweep.
    """
    parts: list[str] = []
    labels: list[str] = []
    channel_layout = "stereo" if channels >= 2 else "mono"
    duration_comp = 1.0 / pitch_factor

    cursor = 0.0
    for i, (s, e) in enumerate(intervals):
        if s > cursor:
            label = f"[orig{i}]"
            parts.append(f"[0:a]atrim=start={cursor}:end={s},asetpts=N/SR/TB{label}")
            labels.append(label)
        rp_label = f"[rp{i}]"
        seg_dur = e - s
        fade_out_start = max(0.0, seg_dur - edge_fade_sec)
        # Reverse + asetrate shifts pitch (and duration); atempo restores duration.
        # The final aformat coerces channel layout so the concat doesn't barf
        # if asetrate altered the layout description.
        rp_chain = (
            f"[0:a]atrim=start={s}:end={e},asetpts=N/SR/TB,"
            f"areverse,"
            f"asetrate=44100*{pitch_factor},aresample=44100,"
            f"atempo={duration_comp:.6f},"
            f"aformat=channel_layouts={channel_layout},"
            f"afade=t=in:st=0:d={edge_fade_sec}:curve=hsin,"
            f"afade=t=out:st={fade_out_start}:d={edge_fade_sec}:curve=hsin"
        )
        parts.append(f"{rp_chain}{rp_label}")
        labels.append(rp_label)
        cursor = e

    if cursor < duration_sec:
        label = "[orig_end]"
        parts.append(f"[0:a]atrim=start={cursor},asetpts=N/SR/TB{label}")
        labels.append(label)

    concat = "".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]"
    return ";".join(parts + [concat])


async def censor_segments_with_reverse_pitch(
    input_path: Path,
    output_path: Path,
    intervals: list[tuple[float, float]],
    duration_sec: float,
    pitch_factor: float = 0.85,
) -> ProcessingResult:
    """Reverse + pitch-shift each interval; output duration unchanged.

    Contract (caller-enforced): intervals sorted, non-overlapping, within
    [0, duration_sec], len(intervals) >= 1.
    """
    if not intervals:
        raise ValueError("intervals must be non-empty")
    if pitch_factor <= 0:
        raise ValueError("pitch_factor must be positive")

    info = await _probe(input_path)
    audio_stream = next(
        (s for s in info.get("streams", []) if s["codec_type"] == "audio"), None,
    )
    if audio_stream is None:
        raise RuntimeError("No audio stream in input")
    channels = int(audio_stream["channels"])

    filtergraph = _build_censor_reverse_pitch_filtergraph(
        intervals, duration_sec, channels, pitch_factor=pitch_factor,
    )

    if len(filtergraph) <= _FILTERGRAPH_INLINE_MAX:
        await _run_ffmpeg(
            "-i", str(input_path),
            "-filter_complex", filtergraph,
            "-map", "[out]",
            str(output_path),
            timeout=600,
        )
    else:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".ffconcat", delete=False, encoding="utf-8",
        ) as fh:
            fh.write(filtergraph)
            script_path = fh.name
        try:
            await _run_ffmpeg(
                "-i", str(input_path),
                "-filter_complex_script", script_path,
                "-map", "[out]",
                str(output_path),
                timeout=600,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

    return ProcessingResult(success=True)


async def censor_segments_with_beep(
    input_path: Path,
    output_path: Path,
    intervals: list[tuple[float, float]],
    duration_sec: float,
    beep_hz: int = 1000,
) -> ProcessingResult:
    """Replace each interval with a sine beep; output duration unchanged.

    Contract (caller-enforced; this function assumes it):
    - intervals sorted, non-overlapping, within [0, duration_sec]
    - len(intervals) >= 1
    """
    if not intervals:
        raise ValueError("intervals must be non-empty")

    info = await _probe(input_path)
    audio_stream = next(
        (s for s in info.get("streams", []) if s["codec_type"] == "audio"), None,
    )
    if audio_stream is None:
        raise RuntimeError("No audio stream in input")
    channels = int(audio_stream["channels"])
    sample_rate = int(audio_stream["sample_rate"])

    filtergraph = _build_censor_beep_filtergraph(
        intervals, duration_sec, beep_hz, channels, sample_rate,
    )

    if len(filtergraph) <= _FILTERGRAPH_INLINE_MAX:
        await _run_ffmpeg(
            "-i", str(input_path),
            "-filter_complex", filtergraph,
            "-map", "[out]",
            str(output_path),
            timeout=600,
        )
    else:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".ffconcat", delete=False, encoding="utf-8",
        ) as fh:
            fh.write(filtergraph)
            script_path = fh.name
        try:
            await _run_ffmpeg(
                "-i", str(input_path),
                "-filter_complex_script", script_path,
                "-map", "[out]",
                str(output_path),
                timeout=600,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

    return ProcessingResult(success=True)


async def remove_segments_with_crossfade(
    input_path: Path,
    output_path: Path,
    intervals: list[tuple[float, float]],
    duration_sec: float,
    crossfade_ms: float = 20.0,
    snap_window_ms: float = 5.0,
) -> ProcessingResult:
    """Delete multiple time ranges and splice the keepers with equal-power
    crossfades at every cut boundary.

    Contract (enforced by the caller; this function assumes it):
    - intervals is sorted, non-overlapping, within [0, duration_sec]
    - adjacent intervals whose gap is < 2 * crossfade_ms have already been merged
    - len(intervals) >= 1 and the result leaves at least one keeper segment
    """
    if not intervals:
        raise ValueError("intervals must be non-empty")

    crossfade_sec = crossfade_ms / 1000.0

    # Snap boundaries to the nearest minimum-energy sample. One decode pass,
    # reused for all boundaries; cost is roughly one FFmpeg call amortized.
    if snap_window_ms > 0:
        loop = asyncio.get_event_loop()
        frames, sr, _chan = await loop.run_in_executor(None, _decode_pcm_sync, input_path)
        flat_times = [t for interval in intervals for t in interval]
        snapped = _snap_boundaries(frames, sr, flat_times, snap_window_ms)
        snapped_intervals = [(snapped[2 * i], snapped[2 * i + 1]) for i in range(len(intervals))]
    else:
        snapped_intervals = list(intervals)

    # Compute keeper segments.
    keepers: list[tuple[float, float, bool, bool]] = []
    cursor = 0.0
    for s, e in snapped_intervals:
        if s > cursor:
            keepers.append((cursor, s, cursor > 0.0, True))
        cursor = e
    if cursor < duration_sec:
        keepers.append((cursor, duration_sec, cursor > 0.0, False))

    if not keepers:
        raise ValueError("remove_segments would produce an empty output")

    filtergraph = _build_remove_segments_filtergraph(keepers, crossfade_sec)

    if len(filtergraph) <= _FILTERGRAPH_INLINE_MAX:
        await _run_ffmpeg(
            "-i", str(input_path),
            "-filter_complex", filtergraph,
            "-map", "[out]",
            str(output_path),
            timeout=600,
        )
    else:
        # Large filtergraphs blow past shell-arg limits on Windows. The
        # `-filter_complex_script` flag reads the expression from a file.
        with tempfile.NamedTemporaryFile(
            "w", suffix=".ffconcat", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(filtergraph)
            script_path = fh.name
        try:
            await _run_ffmpeg(
                "-i", str(input_path),
                "-filter_complex_script", script_path,
                "-map", "[out]",
                str(output_path),
                timeout=600,
            )
        finally:
            Path(script_path).unlink(missing_ok=True)

    return ProcessingResult(success=True)
