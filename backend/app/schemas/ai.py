"""Pydantic schemas for AI endpoints.

The detect-fillers alias (`POST /api/assets/{id}/ai/detect-fillers`) is sugar
over the Operation lifecycle — request/response shapes live here so the AI
endpoint isn't forced to depend on `schemas.operation` for AI-specific types.
The stored `Operation.result` JSONB is built from `FillerDetectionResult`.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class DetectFillersRequest(BaseModel):
    # Confidence floor the server applies before persisting. 0.0 = keep every
    # candidate so the UI can re-filter with its slider without a second call.
    confidence_threshold: float = Field(ge=0.0, le=1.0, default=0.0)
    # Restrict the emitted categories (e.g., ["um", "uh"] to skip discourse
    # markers). None = all categories the classifier knows about.
    categories: list[str] | None = None


class FillerRegionPayload(BaseModel):
    start: float
    end: float
    text: str
    category: str
    confidence: float
    wordIndex: int


class FillerDetectionResult(BaseModel):
    transcriptId: str
    durationSec: float
    language: str
    regions: list[FillerRegionPayload]
    costUsd: float | None = None
    modelVersion: str


# --- Profanity detection (Phase 1: exact matcher only) ----------------------

class DetectProfanityRequest(BaseModel):
    # Phase 1: no parameters. Phase 4 will add matcher-mode toggles
    # (exact/variants/phonetic) and a confidence_threshold here.
    pass


class ProfanityRegionPayload(BaseModel):
    start: float
    end: float
    text: str
    wordIndex: int
    confidence: float
    category: str
    matchedBy: str  # "exact" | "variants" | "phonetic"


class ProfanityDetectionResult(BaseModel):
    transcriptId: str
    durationSec: float
    language: str
    regions: list[ProfanityRegionPayload]
    costUsd: float | None = None
    modelVersion: str


# --- Censorship word-list overrides (Phase 3) -----------------------------

class CensorshipMatchers(BaseModel):
    """Which matchers run during profanity detection. Exact is always on
    (toggling it off would make the feature do nothing). Variants is on by
    default. Phonetic is off by default because false-positive risk is real.
    """
    variants: bool = True
    phonetic: bool = False


class CensorshipWordsResponse(BaseModel):
    """Effective state of the user's censorship word list + matcher toggles.

    `builtIn` is the curated list every user starts with. `added` are
    user-contributed words (always censored). `removed` are built-ins the
    user has chosen to exclude. Effective set = (builtIn - removed) ∪ added.
    """
    builtIn: list[str]
    added: list[str]
    removed: list[str]
    matchers: CensorshipMatchers = CensorshipMatchers()


class CensorshipWordsUpdate(BaseModel):
    """Partial update — fields not present leave the existing values alone."""
    added: list[str] | None = None
    removed: list[str] | None = None
    matchers: CensorshipMatchers | None = None
