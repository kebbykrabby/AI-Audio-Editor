import asyncio
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.models.asset import Asset
from app.models.operation import Operation
from app.models.user import User
from app.processors import analysis, ffmpeg as ffmpeg_proc
from app.processors.waveform import generate_waveform
from app.schemas.error import ErrorBody
from app.schemas.operation import OperationResponse
from app.services.asset_service import build_asset_response
from app.storage import Storage, get_storage
from app.storage.base import ObjectNotFound
from app.workers.recovery import worker_id

logger = logging.getLogger(__name__)


class OperationError(DomainError):
    def __init__(
        self,
        code: str,
        message: str,
        field: str | None = None,
        constraint: str | None = None,
        received: float | str | None = None,
    ) -> None:
        super().__init__(code, message)
        self.field = field
        self.constraint = constraint
        self.received = received


CHANNEL_STRICT_OPS = {"extract_channel", "swap_channels", "split_channels", "mono_mixdown"}


def _audio_key(user_id: str, asset_id: str) -> str:
    return f"users/{user_id}/assets/{asset_id}/audio.wav"


def _waveform_key(user_id: str, asset_id: str) -> str:
    return f"users/{user_id}/assets/{asset_id}/waveform.json"


# ---------- API side (async SQLAlchemy) ----------


async def enqueue_operation(
    db: AsyncSession,
    user: User,
    input_asset_id: str,
    op_type: str,
    parameters: dict,
) -> Operation:
    input_asset = await db.get(Asset, input_asset_id)
    if input_asset is None or input_asset.user_id != user.id:
        raise OperationError("ASSET_NOT_FOUND", f"Asset {input_asset_id} not found")
    if input_asset.status != "ready":
        raise OperationError("ASSET_NOT_READY", f"Asset {input_asset_id} is not ready")

    channels = input_asset.channels or 1
    if op_type in CHANNEL_STRICT_OPS and channels < 2:
        raise OperationError(
            "INVALID_PARAMETERS",
            f"{op_type} requires stereo audio (2 channels)",
            field="channels",
            constraint="must be >= 2",
            received=channels,
        )

    _validate_params(op_type, parameters, input_asset.duration_sec or 0)

    # For merge_channels, verify the right_asset is owned by the same user + ready.
    if op_type == "merge_channels":
        right_id = parameters.get("right_asset_id")
        right = await db.get(Asset, right_id) if right_id else None
        if right is None or right.user_id != user.id:
            raise OperationError("ASSET_NOT_FOUND", f"Right channel asset {right_id} not found")
        if right.status != "ready":
            raise OperationError("ASSET_NOT_READY", f"Right channel asset {right_id} is not ready")

    operation = Operation(
        user_id=user.id,
        type=op_type,
        input_asset_id=input_asset_id,
        parameters=parameters,
        status="queued",
    )
    db.add(operation)
    await db.commit()
    await db.refresh(operation)

    # Lazy import to avoid circular (services -> workers -> services).
    from app.workers.operation_worker import run_operation_actor
    run_operation_actor.send(operation.id)

    return operation


async def get_operation_for_user(
    db: AsyncSession, operation_id: str, user_id: str
) -> Operation | None:
    op = await db.get(Operation, operation_id)
    if op is None or op.user_id != user_id:
        return None
    return op


async def build_operation_response(
    db: AsyncSession, op: Operation
) -> OperationResponse:
    asset_resp = None
    secondary_resp = None
    if op.status == "completed":
        if op.output_asset_id:
            out = await db.get(Asset, op.output_asset_id)
            if out is not None:
                asset_resp = await build_asset_response(out)
        if op.secondary_output_asset_id:
            secondary = await db.get(Asset, op.secondary_output_asset_id)
            if secondary is not None:
                secondary_resp = await build_asset_response(secondary)

    error = None
    if op.status in ("failed", "cancelled") and op.error_code:
        error = ErrorBody(code=op.error_code, message=op.error_message or "Operation failed")

    return OperationResponse(
        operationId=op.id,
        status=op.status,
        warning=op.warning,
        asset=asset_resp,
        secondaryAsset=secondary_resp,
        error=error,
        result=op.result,
    )


# ---------- Worker side (sync SQLAlchemy) ----------


def run_operation_job(db: Session, operation_id: str) -> None:
    asyncio.run(_run_operation_job_async(db, operation_id))


async def _run_operation_job_async(db: Session, operation_id: str) -> None:
    # Optimistic transition queued -> running (avoids duplicate runs).
    now = datetime.utcnow()
    wid = worker_id()
    res = db.execute(
        update(Operation)
        .where(
            Operation.id == operation_id,
            Operation.status.in_(["queued", "running"]),
        )
        .values(
            status="running",
            started_at=now,
            worker_id=wid,
            attempt_count=Operation.attempt_count + 1,
            updated_at=now,
        )
    )
    db.commit()
    if (res.rowcount or 0) == 0:
        logger.info("Operation %s already in terminal state; skipping", operation_id)
        return

    op = db.get(Operation, operation_id)
    if op is None:
        return

    storage = get_storage()
    work_dir = Path(tempfile.mkdtemp(prefix=f"op_{operation_id[:8]}_"))
    try:
        input_asset = db.get(Asset, op.input_asset_id)
        if input_asset is None:
            raise OperationError("ASSET_NOT_FOUND", "Input asset not found")
        if input_asset.storage_key is None:
            raise OperationError("ASSET_NOT_READY", "Input asset has no storage key")

        ext = Path(input_asset.storage_key).suffix or ".wav"
        input_path = work_dir / f"input{ext}"
        try:
            await storage.download_to_path(input_asset.storage_key, input_path)
        except ObjectNotFound:
            raise OperationError("PROCESSING_FAILED", "Input audio missing in storage")

        duration = input_asset.duration_sec or 0.0

        if op.type == "split_channels":
            await _run_split(db, op, input_asset, input_path, work_dir, storage)
        elif op.type == "merge_channels":
            await _run_merge(db, op, input_asset, input_path, work_dir, storage)
        else:
            await _run_single_output(db, op, input_asset, input_path, work_dir, storage, duration)
    except OperationError as e:
        db.rollback()
        op = db.get(Operation, operation_id)
        if op is not None:
            op.status = "failed"
            op.error_code = e.code
            op.error_message = e.message[:500]
            op.completed_at = datetime.utcnow()
            op.updated_at = op.completed_at
            db.commit()
    except DomainError as e:
        db.rollback()
        op = db.get(Operation, operation_id)
        if op is not None:
            op.status = "failed"
            op.error_code = e.code
            op.error_message = e.message[:500]
            op.completed_at = datetime.utcnow()
            op.updated_at = op.completed_at
            db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("Operation %s crashed", operation_id)
        op = db.get(Operation, operation_id)
        if op is not None:
            op.status = "failed"
            op.error_code = "PROCESSING_FAILED"
            op.error_message = str(e)[:500]
            op.completed_at = datetime.utcnow()
            op.updated_at = op.completed_at
            db.commit()
        raise  # surface to Dramatiq so transient errors are retried
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def _run_single_output(
    db: Session,
    op: Operation,
    input_asset: Asset,
    input_path: Path,
    work_dir: Path,
    storage: Storage,
    duration: float,
) -> None:
    output_path = work_dir / "output.wav"
    result = await _dispatch_async(op.type, input_path, output_path, op.parameters, duration)

    await generate_waveform(output_path)
    wf_local = output_path.parent / "waveform.json"
    if not wf_local.exists():
        candidates = list(output_path.parent.glob("*.json"))
        if candidates:
            wf_local = candidates[0]

    info = await ffmpeg_proc.probe_audio(output_path)

    output_asset = Asset(
        user_id=op.user_id,
        type="derived",
        status="ready",
        parent_asset_id=input_asset.id,
        filename=input_asset.filename,
        mime_type="audio/wav",
        duration_sec=info["duration_sec"],
        sample_rate=info["sample_rate"],
        channels=info["channels"],
    )
    db.add(output_asset)
    db.flush()

    audio_key = _audio_key(op.user_id, output_asset.id)
    wf_key = _waveform_key(op.user_id, output_asset.id)
    await storage.put_file(audio_key, output_path, "audio/wav")
    await storage.put_file(wf_key, wf_local, "application/json")

    output_asset.storage_key = audio_key
    output_asset.waveform_key = wf_key

    op.status = "completed"
    op.output_asset_id = output_asset.id
    op.warning = result.warning
    op.completed_at = datetime.utcnow()
    op.updated_at = op.completed_at
    db.commit()


async def _run_split(
    db: Session,
    op: Operation,
    input_asset: Asset,
    input_path: Path,
    work_dir: Path,
    storage: Storage,
) -> None:
    left_path = work_dir / "left.wav"
    right_path = work_dir / "right.wav"
    result = await ffmpeg_proc.split_channels(input_path, left_path, right_path)

    await generate_waveform(left_path)
    await generate_waveform(right_path)
    left_info = await ffmpeg_proc.probe_audio(left_path)
    right_info = await ffmpeg_proc.probe_audio(right_path)

    left_asset = Asset(
        user_id=op.user_id,
        type="derived",
        status="ready",
        parent_asset_id=input_asset.id,
        filename=input_asset.filename,
        mime_type="audio/wav",
        duration_sec=left_info["duration_sec"],
        sample_rate=left_info["sample_rate"],
        channels=left_info["channels"],
    )
    right_asset = Asset(
        user_id=op.user_id,
        type="derived",
        status="ready",
        parent_asset_id=input_asset.id,
        filename=input_asset.filename,
        mime_type="audio/wav",
        duration_sec=right_info["duration_sec"],
        sample_rate=right_info["sample_rate"],
        channels=right_info["channels"],
    )
    db.add_all([left_asset, right_asset])
    db.flush()

    l_audio = _audio_key(op.user_id, left_asset.id)
    r_audio = _audio_key(op.user_id, right_asset.id)
    l_wf = _waveform_key(op.user_id, left_asset.id)
    r_wf = _waveform_key(op.user_id, right_asset.id)
    l_wf_local = left_path.parent / (left_path.stem + ".waveform.json")
    r_wf_local = right_path.parent / (right_path.stem + ".waveform.json")
    if not l_wf_local.exists():
        l_wf_local = left_path.parent / "waveform.json"
    if not r_wf_local.exists():
        r_wf_local = right_path.parent / "waveform.json"

    await storage.put_file(l_audio, left_path, "audio/wav")
    await storage.put_file(r_audio, right_path, "audio/wav")
    if l_wf_local.exists():
        await storage.put_file(l_wf, l_wf_local, "application/json")
    if r_wf_local.exists():
        await storage.put_file(r_wf, r_wf_local, "application/json")

    left_asset.storage_key = l_audio
    left_asset.waveform_key = l_wf
    right_asset.storage_key = r_audio
    right_asset.waveform_key = r_wf

    op.status = "completed"
    op.output_asset_id = left_asset.id
    op.secondary_output_asset_id = right_asset.id
    op.warning = result.warning
    op.completed_at = datetime.utcnow()
    op.updated_at = op.completed_at
    db.commit()


async def _run_merge(
    db: Session,
    op: Operation,
    left_asset: Asset,
    left_path: Path,
    work_dir: Path,
    storage: Storage,
) -> None:
    right_id = op.parameters.get("right_asset_id")
    right_asset = db.get(Asset, right_id) if right_id else None
    if right_asset is None or right_asset.user_id != op.user_id:
        raise OperationError("ASSET_NOT_FOUND", "Right channel asset not found")
    if right_asset.status != "ready" or right_asset.storage_key is None:
        raise OperationError("ASSET_NOT_READY", "Right channel asset is not ready")

    right_path = work_dir / f"right{Path(right_asset.storage_key).suffix or '.wav'}"
    try:
        await storage.download_to_path(right_asset.storage_key, right_path)
    except ObjectNotFound:
        raise OperationError("PROCESSING_FAILED", "Right channel audio missing in storage")

    output_path = work_dir / "output.wav"
    result = await ffmpeg_proc.merge_channels(left_path, right_path, output_path)

    await generate_waveform(output_path)
    wf_local = output_path.parent / "waveform.json"
    info = await ffmpeg_proc.probe_audio(output_path)

    output_asset = Asset(
        user_id=op.user_id,
        type="derived",
        status="ready",
        parent_asset_id=left_asset.id,
        filename=left_asset.filename,
        mime_type="audio/wav",
        duration_sec=info["duration_sec"],
        sample_rate=info["sample_rate"],
        channels=info["channels"],
    )
    db.add(output_asset)
    db.flush()

    audio_key = _audio_key(op.user_id, output_asset.id)
    wf_key = _waveform_key(op.user_id, output_asset.id)
    await storage.put_file(audio_key, output_path, "audio/wav")
    if wf_local.exists():
        await storage.put_file(wf_key, wf_local, "application/json")

    output_asset.storage_key = audio_key
    output_asset.waveform_key = wf_key

    op.status = "completed"
    op.output_asset_id = output_asset.id
    op.warning = result.warning
    op.completed_at = datetime.utcnow()
    op.updated_at = op.completed_at
    db.commit()


async def _dispatch_async(
    op_type: str,
    input_path: Path,
    output_path: Path,
    params: dict,
    duration: float,
):
    if op_type == "trim":
        return await ffmpeg_proc.trim(input_path, output_path, params["start_sec"], params["end_sec"])
    if op_type == "delete":
        return await ffmpeg_proc.delete(input_path, output_path, params["start_sec"], params["end_sec"])
    if op_type == "fade_in":
        return await ffmpeg_proc.fade_in(input_path, output_path, params["duration_sec"], params.get("curve", "linear"))
    if op_type == "fade_out":
        return await ffmpeg_proc.fade_out(input_path, output_path, params["duration_sec"], duration, params.get("curve", "linear"))
    if op_type == "gain":
        return await ffmpeg_proc.gain(input_path, output_path, params["gain_db"])
    if op_type == "normalize":
        peak_db = await analysis.detect_peak_db(input_path)
        needed_gain = params["target_db"] - peak_db
        return await ffmpeg_proc.gain(input_path, output_path, needed_gain)
    if op_type == "reverse":
        return await ffmpeg_proc.reverse(input_path, output_path)
    if op_type == "remove_silence":
        return await ffmpeg_proc.remove_silence(
            input_path,
            output_path,
            params.get("threshold_db", -40),
            params.get("min_silence_sec", 0.5),
        )
    if op_type == "extract_channel":
        return await ffmpeg_proc.extract_channel(input_path, output_path, params["channel"])
    if op_type == "swap_channels":
        return await ffmpeg_proc.swap_channels(input_path, output_path)
    if op_type == "mono_mixdown":
        return await ffmpeg_proc.mono_mixdown(input_path, output_path)
    if op_type == "speed":
        return await ffmpeg_proc.speed(input_path, output_path, params["factor"])
    if op_type == "remove_segments":
        intervals_raw = params["intervals"]
        intervals = [(float(iv["start"]), float(iv["end"])) for iv in intervals_raw]
        crossfade_ms = float(params.get("crossfade_ms", 20.0))
        merged = _merge_adjacent(intervals, gap_threshold_sec=2 * crossfade_ms / 1000.0)
        return await ffmpeg_proc.remove_segments_with_crossfade(
            input_path, output_path,
            intervals=merged, duration_sec=duration, crossfade_ms=crossfade_ms,
        )
    if op_type == "censor_segments":
        intervals_raw = params["intervals"]
        intervals = [(float(iv["start"]), float(iv["end"])) for iv in intervals_raw]
        mode = params.get("mode", "beep")
        beep_hz = int(params.get("beep_hz", 1000))
        if mode == "beep":
            return await ffmpeg_proc.censor_segments_with_beep(
                input_path, output_path,
                intervals=intervals, duration_sec=duration, beep_hz=beep_hz,
            )
        # Phase 2 will add mute / cut / reverse_pitch. The schema-level Literal
        # already rejects them at request parse time; this guard catches a
        # mismatched schema-vs-dispatch drift if it ever happens.
        raise OperationError(
            "INVALID_PARAMETERS",
            f"Censor mode {mode!r} not supported (Phase 1 = beep only)",
            field="mode", constraint="must be 'beep'", received=mode,
        )
    raise OperationError("INVALID_OPERATION", f"Unknown operation: {op_type}")


def _merge_adjacent(
    intervals: list[tuple[float, float]], *, gap_threshold_sec: float
) -> list[tuple[float, float]]:
    """Merge intervals whose gap falls under the crossfade width so the
    crossfade windows don't overlap. Caller has already sorted + validated
    non-overlap; this only collapses near-adjacent ranges.
    """
    if not intervals:
        return []
    merged = [intervals[0]]
    for s, e in intervals[1:]:
        last_s, last_e = merged[-1]
        if s - last_e < gap_threshold_sec:
            merged[-1] = (last_s, max(last_e, e))
        else:
            merged.append((s, e))
    return merged


def _validate_params(op_type: str, params: dict, duration: float) -> None:
    if op_type in ("trim", "delete"):
        start = params["start_sec"]
        end = params["end_sec"]
        if start >= end:
            raise OperationError(
                "INVALID_PARAMETERS", "start_sec must be less than end_sec",
                field="start_sec", constraint="must be < end_sec", received=start,
            )
        if start >= duration:
            raise OperationError(
                "INVALID_PARAMETERS", "start_sec exceeds audio duration",
                field="start_sec", constraint=f"must be < {duration}", received=start,
            )
        if end > duration:
            raise OperationError(
                "INVALID_PARAMETERS", "end_sec exceeds audio duration",
                field="end_sec", constraint=f"must be <= {duration}", received=end,
            )
        if op_type == "delete" and start <= 0 and end >= duration:
            raise OperationError(
                "INVALID_PARAMETERS", "delete range covers entire file; output would be empty",
                field="end_sec", constraint="range must not cover entire file", received=end,
            )
    elif op_type in ("fade_in", "fade_out"):
        if params["duration_sec"] > duration:
            raise OperationError(
                "INVALID_PARAMETERS", "fade duration exceeds audio duration",
                field="duration_sec", constraint=f"must be <= {duration}",
                received=params["duration_sec"],
            )
    elif op_type in ("remove_segments", "censor_segments"):
        intervals = params.get("intervals") or []
        if not intervals:
            raise OperationError(
                "INVALID_PARAMETERS", "intervals must not be empty",
                field="intervals", constraint="min_length=1", received=0,
            )
        # Sort by start and enforce non-overlap + bounds. Pydantic has already
        # range-checked each interval's fields; we validate the relationship.
        sorted_intervals = sorted(intervals, key=lambda iv: iv["start"])
        prev_end = -1.0
        for iv in sorted_intervals:
            s, e = float(iv["start"]), float(iv["end"])
            if s >= e:
                raise OperationError(
                    "INVALID_PARAMETERS", "interval.start must be < interval.end",
                    field="intervals", constraint="start < end", received=s,
                )
            if e > duration:
                raise OperationError(
                    "INVALID_PARAMETERS", "interval.end exceeds audio duration",
                    field="intervals", constraint=f"end must be <= {duration}", received=e,
                )
            if s < prev_end:
                raise OperationError(
                    "INVALID_PARAMETERS", "intervals must not overlap",
                    field="intervals", constraint="non-overlapping", received=s,
                )
            prev_end = e
        # Ensure at least one keeper segment survives.
        total_cut = sum(float(iv["end"]) - float(iv["start"]) for iv in sorted_intervals)
        if total_cut >= duration:
            raise OperationError(
                "INVALID_PARAMETERS", "removing all intervals would leave an empty output",
                field="intervals", constraint="total coverage must be < duration", received=total_cut,
            )
        # Replace caller-supplied order with the sorted form so the worker
        # can trust it.
        params["intervals"] = sorted_intervals
