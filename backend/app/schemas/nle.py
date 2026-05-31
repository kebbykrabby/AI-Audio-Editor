"""Pydantic schemas for natural-language editing.

The `POST /api/assets/{id}/ai/plan` endpoint accepts a prompt + optional
waveform selection and returns an operation id. The completed operation's
`result` JSONB carries the `NlePlanResult` below — frontend reads it via
the existing `GET /api/operations/{id}` poll path.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class NleSelection(BaseModel):
    """User's current waveform selection at the moment they submitted the
    prompt. Optional — sent only when the user has dragged a region.

    The LLM gets this as context so phrases like "this part" and "the
    selection" resolve to a concrete range.
    """
    startSec: float = Field(ge=0)
    endSec: float = Field(gt=0)


class NlePlanRequest(BaseModel):
    """User-supplied input for plan generation."""
    prompt: str = Field(min_length=1, max_length=2000)
    selection: NleSelection | None = None

    @field_validator("prompt")
    @classmethod
    def _strip_and_require_content(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("prompt must not be empty or whitespace-only")
        return stripped


class NlePlanStep(BaseModel):
    """One operation the LLM proposed, plus our server-side validation result.

    `validationStatus`:
    - "valid"     — Pydantic schema accepted the params; safe to apply.
    - "invalid"   — schema rejected the params; UI shows but cannot apply.

    Invalid steps are kept in the response (not dropped) so the user sees
    what the LLM proposed and can re-prompt with more specificity.
    """
    stepIndex: int = Field(ge=0)
    description: str
    operation: dict          # {"type": str, "parameters": dict}
    validationStatus: str    # "valid" | "invalid"
    validationError: str | None = None


class NlePlanResult(BaseModel):
    """Persisted as `Operation.result` for ai_nle_plan ops."""
    prompt: str
    modelVersion: str
    costUsd: float | None = None
    # `final_response` text from the LLM. Empty when a real plan was returned.
    # When `steps` is empty, this carries the LLM's clarifying question.
    finalResponse: str
    steps: list[NlePlanStep]
    # Whether the transcript was included in the prompt this run.
    transcriptUsed: bool
    # Whether a waveform selection was passed through.
    selectionUsed: bool
