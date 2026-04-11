import asyncio
import logging
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.operation import Operation
from app.processors import analysis, ffmpeg as ffmpeg_proc
from app.processors.waveform import generate_waveform
from app.storage.local import storage

logger = logging.getLogger(__name__)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class OperationError(Exception):
    def __init__(self, code: str, message: str, field: str | None = None):
        self.code = code
        self.message = message
        self.field = field


async def execute_operation(
    db: AsyncSession, op_type: str, input_asset_id: str, parameters: dict,
) -> tuple[Operation, Asset]:
    # 1. Fetch and validate input asset
    input_asset = await db.get(Asset, input_asset_id)
    if not input_asset:
        raise OperationError("ASSET_NOT_FOUND", f"Asset {input_asset_id} not found")
    if input_asset.status != "ready":
        raise OperationError("ASSET_NOT_READY", f"Asset {input_asset_id} is not ready")

    duration = input_asset.duration_sec or 0

    # 2. Cross-field validation
    _validate_params(op_type, parameters, duration)

    # 3. Resolve input audio path
    input_path = storage.get_audio_path(input_asset_id)
    if not input_path or not input_path.exists():
        input_path = storage.get_original_path(input_asset_id)
    if not input_path:
        raise OperationError("PROCESSING_FAILED", "Input audio file not found")

    # 4. Prepare output
    output_asset_id = _new_id("ast")
    op_id = _new_id("op")
    output_dir = Path(storage.root) / output_asset_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "audio.wav"

    # 5. Execute processor with 30s timeout
    try:
        result = await asyncio.wait_for(
            _dispatch(op_type, input_path, output_path, parameters, duration),
            timeout=30,
        )
    except asyncio.TimeoutError:
        raise OperationError("PROCESSING_TIMEOUT", "Operation exceeded 30 second timeout")
    except RuntimeError as e:
        raise OperationError("PROCESSING_FAILED", str(e))

    # 6. Generate waveform for output
    await generate_waveform(output_path)

    # 7. Probe output for metadata
    out_info = await ffmpeg_proc.probe_audio(output_path)

    # 8. Create DB records
    output_asset = Asset(
        id=output_asset_id,
        type="derived",
        status="ready",
        parent_asset_id=input_asset_id,
        filename=input_asset.filename,
        duration_sec=out_info["duration_sec"],
        sample_rate=out_info["sample_rate"],
        channels=out_info["channels"],
    )
    operation = Operation(
        id=op_id,
        type=op_type,
        input_asset_id=input_asset_id,
        output_asset_id=output_asset_id,
        parameters=parameters,
        status="completed",
        warning=result.warning,
    )
    db.add(output_asset)
    db.add(operation)
    await db.commit()
    await db.refresh(output_asset)
    await db.refresh(operation)

    return operation, output_asset


async def _dispatch(
    op_type: str, input_path: Path, output_path: Path,
    params: dict, duration: float,
) -> ffmpeg_proc.ProcessingResult:
    if op_type == "trim":
        return await ffmpeg_proc.trim(input_path, output_path, params["start_sec"], params["end_sec"])
    elif op_type == "delete":
        return await ffmpeg_proc.delete(input_path, output_path, params["start_sec"], params["end_sec"])
    elif op_type == "fade_in":
        return await ffmpeg_proc.fade_in(input_path, output_path, params["duration_sec"], params.get("curve", "linear"))
    elif op_type == "fade_out":
        return await ffmpeg_proc.fade_out(input_path, output_path, params["duration_sec"], duration, params.get("curve", "linear"))
    elif op_type == "gain":
        return await ffmpeg_proc.gain(input_path, output_path, params["gain_db"])
    elif op_type == "normalize":
        # Peak detection via FFmpeg astats, then apply gain
        peak_db = await analysis.detect_peak_db(input_path)
        needed_gain = params["target_db"] - peak_db
        return await ffmpeg_proc.gain(input_path, output_path, needed_gain)
    else:
        raise OperationError("INVALID_OPERATION", f"Unknown operation: {op_type}")


def _validate_params(op_type: str, params: dict, duration: float) -> None:
    if op_type in ("trim", "delete"):
        start = params["start_sec"]
        end = params["end_sec"]
        if start >= end:
            raise OperationError("INVALID_PARAMETERS", "start_sec must be less than end_sec", "start_sec")
        if start >= duration:
            raise OperationError("INVALID_PARAMETERS", "start_sec exceeds audio duration", "start_sec")
        if end > duration:
            raise OperationError("INVALID_PARAMETERS", "end_sec exceeds audio duration", "end_sec")
        if op_type == "delete" and start <= 0 and end >= duration:
            raise OperationError("INVALID_PARAMETERS", "delete range covers entire file; output would be empty", "end_sec")

    elif op_type in ("fade_in", "fade_out"):
        if params["duration_sec"] > duration:
            raise OperationError("INVALID_PARAMETERS", "fade duration exceeds audio duration", "duration_sec")
