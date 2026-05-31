"""NLE plan orchestration.

API-side: validate the request, enforce quota, enqueue the worker.
Worker-side: download audio metadata + transcript, call the LLM, validate
each proposed tool call against the existing operation schemas, persist
an `NlePlanResult` onto the operation row.

Provider selection mirrors `ai_service.get_transcription_provider`:
a module-level singleton keyed off `settings.LLM_PROVIDER`.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import DomainError
from app.models.asset import Asset
from app.models.operation import Operation
from app.models.user import User
from app.providers.fake_llm import FakeLLMProvider
from app.providers.llm import (
    LLMProvider,
    LLMProviderError,
    LlmPlanResponse,
    ToolCall,
)
from app.providers.transcription import TranscriptionError
from app.schemas.nle import NlePlanResult, NlePlanStep
from app.schemas.operation import (
    DeleteParams,
    ExtractChannelParams,
    FadeInParams,
    FadeOutParams,
    GainParams,
    MonoMixdownParams,
    NormalizeParams,
    RemoveSilenceParams,
    ReverseParams,
    SpeedParams,
    SwapChannelsParams,
    TrimParams,
)
from app.services import analyses_service
from app.services.ai_quota import enforce_ai_quota
from app.services.ai_service import (
    _error_code_for as _ai_error_code_for,
    get_transcription_provider,
)
from app.services.nle_prompts import build_system_prompt, build_tool_catalog
from app.services.operation_service import OperationError
from app.storage import get_storage
from app.storage.base import ObjectNotFound
from app.workers.recovery import worker_id

logger = logging.getLogger(__name__)


# --- LLM provider factory (singleton per process) ---------------------------

_llm_provider: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    """Return the configured LLM provider, instantiating lazily.

    Default is the fake provider so a missing/incomplete config never
    silently calls a real (paying) API.
    """
    global _llm_provider
    if _llm_provider is not None:
        return _llm_provider

    name = settings.LLM_PROVIDER
    if name == "fake":
        _llm_provider = FakeLLMProvider()
    elif name == "gemini":
        # Phase 3 will land app.providers.gemini_llm.GeminiLLMProvider;
        # until then, configuring LLM_PROVIDER=gemini falls back loudly.
        try:
            from app.providers.gemini_llm import GeminiLLMProvider  # type: ignore[import-not-found]
        except ImportError:
            raise LLMProviderError(
                "provider_unavailable",
                "Gemini provider not yet implemented (Phase 3). "
                "Use LLM_PROVIDER=fake until it ships.",
            )
        _llm_provider = GeminiLLMProvider(
            api_key=settings.GEMINI_API_KEY or "",
            model=settings.GEMINI_MODEL,
        )
    elif name == "anthropic":
        try:
            from app.providers.anthropic_llm import AnthropicLLMProvider  # type: ignore[import-not-found]
        except ImportError:
            raise LLMProviderError(
                "provider_unavailable",
                "Anthropic provider not yet implemented (Phase 5).",
            )
        _llm_provider = AnthropicLLMProvider(
            api_key=settings.ANTHROPIC_API_KEY or "",
            model=settings.ANTHROPIC_MODEL,
        )
    elif name == "openai":
        try:
            from app.providers.openai_llm import OpenAILLMProvider  # type: ignore[import-not-found]
        except ImportError:
            raise LLMProviderError(
                "provider_unavailable",
                "OpenAI LLM provider not yet implemented (Phase 5).",
            )
        _llm_provider = OpenAILLMProvider(
            api_key=settings.OPENAI_API_KEY or "",
            model=settings.OPENAI_LLM_MODEL,
        )
    else:
        raise LLMProviderError(
            "provider_unavailable", f"Unknown LLM_PROVIDER: {name}",
        )
    return _llm_provider


def reset_llm_provider() -> None:
    """Test hook: clear the cached provider so fixtures can re-inject."""
    global _llm_provider
    _llm_provider = None


# --- Tool-call validation ---------------------------------------------------

# Maps tool name (matches operation type) → Pydantic schema class.
_VALIDATORS: dict[str, type] = {
    "trim": TrimParams,
    "delete": DeleteParams,
    "fade_in": FadeInParams,
    "fade_out": FadeOutParams,
    "gain": GainParams,
    "normalize": NormalizeParams,
    "reverse": ReverseParams,
    "remove_silence": RemoveSilenceParams,
    "speed": SpeedParams,
    "mono_mixdown": MonoMixdownParams,
    "swap_channels": SwapChannelsParams,
    "extract_channel": ExtractChannelParams,
}


def _describe_step(call: ToolCall) -> str:
    """Human-readable summary the UI renders above the raw operation block.

    Kept conservative — we never want this description to imply behavior that
    differs from what the operation will actually do. If a description doesn't
    match the verb 1:1, the user might apply something they didn't intend.
    """
    n = call.tool_name
    p = call.arguments or {}
    if n == "trim":
        return f"Keep audio from {p.get('start_sec', 0):.2f}s to {p.get('end_sec', 0):.2f}s"
    if n == "delete":
        return f"Delete audio from {p.get('start_sec', 0):.2f}s to {p.get('end_sec', 0):.2f}s"
    if n == "fade_in":
        return f"Fade in over {p.get('duration_sec', 0):.2f}s"
    if n == "fade_out":
        return f"Fade out over {p.get('duration_sec', 0):.2f}s"
    if n == "gain":
        db = p.get("gain_db", 0)
        sign = "+" if db >= 0 else ""
        return f"Adjust volume by {sign}{db} dB"
    if n == "normalize":
        return f"Normalize peak to {p.get('target_db', -3)} dB"
    if n == "reverse":
        return "Reverse the audio"
    if n == "remove_silence":
        return (
            f"Remove silence below {p.get('threshold_db', -40)} dB lasting "
            f"≥ {p.get('min_silence_sec', 0.5)}s"
        )
    if n == "speed":
        return f"Change speed by {p.get('factor', 1.0)}× (preserves pitch)"
    if n == "mono_mixdown":
        return "Mix stereo down to mono"
    if n == "swap_channels":
        return "Swap left and right channels"
    if n == "extract_channel":
        return f"Extract {p.get('channel', '?')} channel"
    return f"Operation: {n}"


def _validate_tool_call(call: ToolCall) -> tuple[str, str | None]:
    """Return (status, error_message).

    Schema-level validation only — `start < end`, `end <= duration`, etc.
    are cross-field checks that `operation_service` enforces when the user
    actually applies the step. We don't run those here because we want to
    keep step validation a pure function of the proposed parameters.
    """
    cls = _VALIDATORS.get(call.tool_name)
    if cls is None:
        return "invalid", f"Unknown tool: {call.tool_name}"
    try:
        cls.model_validate(call.arguments or {})
    except ValidationError as e:
        return "invalid", _short_validation_error(e)
    return "valid", None


def _short_validation_error(e: ValidationError) -> str:
    """Pick the first error message; Pydantic dumps can be verbose."""
    errs = e.errors()
    if not errs:
        return "Invalid parameters"
    err = errs[0]
    loc = ".".join(str(p) for p in err.get("loc", []))
    msg = err.get("msg", "invalid")
    return f"{loc}: {msg}" if loc else msg


# --- API side --------------------------------------------------------------


async def enqueue_generate_plan(
    db: AsyncSession,
    *,
    user: User,
    asset_id: str,
    prompt: str,
    selection: tuple[float, float] | None,
) -> Operation:
    asset = await db.get(Asset, asset_id)
    if asset is None or asset.user_id != user.id:
        raise OperationError("ASSET_NOT_FOUND", f"Asset {asset_id} not found")
    if asset.status != "ready":
        raise OperationError("ASSET_NOT_READY", f"Asset {asset_id} is not ready")

    duration = asset.duration_sec or 0.0
    if duration > settings.AI_MAX_INPUT_DURATION_SEC:
        raise OperationError(
            "AI_INPUT_TOO_LONG",
            f"Audio is {duration:.0f}s; max for AI is {settings.AI_MAX_INPUT_DURATION_SEC}s",
            field="duration_sec",
            constraint=f"must be <= {settings.AI_MAX_INPUT_DURATION_SEC}",
            received=duration,
        )

    # Selection bounds sanity (Pydantic already enforces positivity).
    if selection is not None:
        s, e = selection
        if s >= e or e > duration:
            raise OperationError(
                "INVALID_PARAMETERS",
                "selection must satisfy 0 <= start < end <= duration",
                field="selection",
                constraint=f"0 <= start < end <= {duration}",
                received=f"{s},{e}",
            )

    await enforce_ai_quota(db, user.id)

    operation = Operation(
        user_id=user.id,
        type="ai_nle_plan",
        input_asset_id=asset_id,
        parameters={
            "prompt": prompt,
            "selection": (
                {"start": float(selection[0]), "end": float(selection[1])}
                if selection else None
            ),
        },
        status="queued",
    )
    db.add(operation)
    await db.commit()
    await db.refresh(operation)

    from app.workers.ai_worker import run_ai_nle_plan_actor
    run_ai_nle_plan_actor.send(operation.id)

    return operation


# --- Worker side -----------------------------------------------------------


def run_ai_nle_plan_job(db: Session, operation_id: str) -> None:
    asyncio.run(_run_ai_nle_plan_job_async(db, operation_id))


async def _run_ai_nle_plan_job_async(db: Session, operation_id: str) -> None:
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
        logger.info("NLE plan op %s already in terminal state; skipping", operation_id)
        return

    op = db.get(Operation, operation_id)
    if op is None:
        return

    storage = get_storage()
    work_dir = Path(tempfile.mkdtemp(prefix=f"nle_{operation_id[:8]}_"))
    try:
        asset = db.get(Asset, op.input_asset_id)
        if asset is None or asset.storage_key is None:
            raise OperationError("ASSET_NOT_FOUND", "Input asset or storage key missing")

        params = op.parameters or {}
        prompt: str = (params.get("prompt") or "").strip()
        if not prompt:
            raise OperationError(
                "INVALID_PARAMETERS", "prompt must not be empty",
                field="prompt", constraint="non-empty", received="",
            )
        selection_raw = params.get("selection")
        selection: tuple[float, float] | None = None
        if selection_raw:
            selection = (
                float(selection_raw["start"]),
                float(selection_raw["end"]),
            )

        # D5: always-transcribe. The analyses_service cache makes subsequent
        # NLE calls on the same asset free; the first call pays the Whisper
        # cost once. If transcription fails (provider down etc.), we fall
        # back to running NLE with metadata + prompt + selection only.
        transcript_words: list[dict[str, Any]] = []
        transcript_used = False
        try:
            ext = Path(asset.storage_key).suffix or ".wav"
            input_path = work_dir / f"input{ext}"
            try:
                await storage.download_to_path(asset.storage_key, input_path)
            except ObjectNotFound:
                raise OperationError(
                    "PROCESSING_FAILED", "Input audio missing in storage",
                )
            tx_provider = get_transcription_provider()
            _analysis_row, transcript = await analyses_service.get_or_create_transcript(
                db, storage, asset, input_path, tx_provider,
                language="en", tmp_dir=work_dir,
            )
            transcript_words = [
                {"text": w.text, "start": w.start, "end": w.end}
                for w in transcript.words
            ]
            transcript_used = True
        except TranscriptionError as e:
            logger.warning(
                "NLE op %s: transcription failed (%s); continuing without transcript",
                operation_id, e.kind,
            )

        system_prompt = build_system_prompt(
            duration_sec=float(asset.duration_sec or 0),
            sample_rate=int(asset.sample_rate or 0),
            channels=int(asset.channels or 0),
            selection=selection,
            transcript_words=transcript_words or None,
        )
        tools = build_tool_catalog()

        provider = get_llm_provider()
        llm_response: LlmPlanResponse = await provider.generate_plan(
            system_prompt=system_prompt,
            user_prompt=prompt,
            tools=tools,
            max_tool_calls=settings.NLE_MAX_TOOL_CALLS,
        )

        steps: list[NlePlanStep] = []
        valid_count = 0
        for i, call in enumerate(llm_response.tool_calls):
            status, err = _validate_tool_call(call)
            if status == "valid":
                valid_count += 1
            steps.append(NlePlanStep(
                stepIndex=i,
                description=_describe_step(call),
                operation={
                    "type": call.tool_name,
                    "parameters": call.arguments or {},
                },
                validationStatus=status,
                validationError=err,
            ))

        result = NlePlanResult(
            prompt=prompt,
            modelVersion=llm_response.model_version,
            costUsd=float(llm_response.cost_usd),
            finalResponse=llm_response.final_response,
            steps=steps,
            transcriptUsed=transcript_used,
            selectionUsed=selection is not None,
        )

        op.result = result.model_dump()
        op.cost_usd = llm_response.cost_usd
        op.status = "completed"
        op.completed_at = datetime.utcnow()
        op.updated_at = op.completed_at
        db.commit()

        logger.info(
            "ai_nle_plan done op=%s user=%s steps=%d valid=%d cost=%s "
            "model=%s transcript=%s selection=%s",
            operation_id, op.user_id, len(steps), valid_count,
            llm_response.cost_usd, llm_response.model_version,
            transcript_used, selection is not None,
        )
    except LLMProviderError as e:
        db.rollback()
        op = db.get(Operation, operation_id)
        if op is not None:
            op.status = "failed"
            op.error_code = _ai_error_code_for(e.kind)
            op.error_message = str(e)[:500]
            op.completed_at = datetime.utcnow()
            op.updated_at = op.completed_at
            db.commit()
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
        logger.exception("NLE op %s crashed", operation_id)
        op = db.get(Operation, operation_id)
        if op is not None:
            op.status = "failed"
            op.error_code = "PROCESSING_FAILED"
            op.error_message = str(e)[:500]
            op.completed_at = datetime.utcnow()
            op.updated_at = op.completed_at
            db.commit()
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


_ = User  # silence "imported but unused" — referenced indirectly via op.user_id type hints
