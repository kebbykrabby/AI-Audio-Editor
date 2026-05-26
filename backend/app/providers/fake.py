"""Fake transcription provider for tests and offline/dev runs.

Returns a pre-baked `WordLevelTranscript` without touching the network.
Tests inject their own fixture via `FakeTranscriptionProvider(transcript=...)`.
The default instance returns an empty transcript so a mistaken prod wire-up
fails loudly (no regions detected) rather than silently looking like real data.
"""
from __future__ import annotations

from pathlib import Path

from app.providers.transcription import (
    TranscriptionProvider,
    WordLevelTranscript,
)


class FakeTranscriptionProvider(TranscriptionProvider):
    def __init__(self, transcript: WordLevelTranscript | None = None):
        self._transcript = transcript or WordLevelTranscript(
            language="en",
            duration_sec=0.0,
            words=[],
            model_version="fake-v1",
            cost_usd=0.0,
        )

    async def transcribe(
        self, audio_path: Path, language: str = "en"
    ) -> WordLevelTranscript:
        return self._transcript
