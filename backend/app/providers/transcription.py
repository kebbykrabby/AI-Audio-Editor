"""Transcription provider protocol and result schema.

The service layer depends only on this module; concrete providers
(`whisper.py`, `fake.py`) implement the protocol. Swapping providers is a
one-line config change; see `get_transcription_provider` for the factory.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class TranscribedWord(BaseModel):
    text: str
    start: float  # seconds from start of input
    end: float


class WordLevelTranscript(BaseModel):
    language: str              # BCP-47ish; Whisper returns full names ("english")
    duration_sec: float
    words: list[TranscribedWord]
    model_version: str         # provider-reported, used as cache-key component
    cost_usd: float | None = None


class TranscriptionError(Exception):
    """Provider-level failure. The service layer maps `.kind` to an AI_* error code.

    kind ∈ {"provider_unavailable", "rate_limited", "input_too_long",
            "output_invalid", "unauthorized"}
    """

    def __init__(self, kind: str, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code


class TranscriptionProvider(Protocol):
    async def transcribe(
        self, audio_path: Path, language: str = "en"
    ) -> WordLevelTranscript: ...
