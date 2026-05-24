"""OpenAI Whisper transcription provider (REST, no SDK).

Uses httpx directly so we don't pull the `openai` package and its transitive
deps for one endpoint. The request shape matches OpenAI's
`POST /v1/audio/transcriptions` with `response_format=verbose_json` and
word-level timestamp granularity.

Never logs the Authorization header. On non-2xx, raises `TranscriptionError`
with a kind derived from HTTP status — no response body forwarded.
"""
from __future__ import annotations

from pathlib import Path

import httpx

from app.providers.transcription import (
    TranscribedWord,
    TranscriptionError,
    TranscriptionProvider,
    WordLevelTranscript,
)

_OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"
_WHISPER_USD_PER_MIN = 0.006  # whisper-1 published rate (2026-04)


class WhisperProvider(TranscriptionProvider):
    def __init__(self, api_key: str, model: str = "whisper-1", timeout_sec: float = 300.0):
        if not api_key or api_key == "CHANGE_ME":
            raise TranscriptionError(
                "unauthorized", "OPENAI_API_KEY is not configured"
            )
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_sec

    async def transcribe(
        self, audio_path: Path, language: str = "en"
    ) -> WordLevelTranscript:
        audio_bytes = audio_path.read_bytes()
        files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
        data = {
            "model": self._model,
            "language": language,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word",
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(_OPENAI_URL, headers=headers, data=data, files=files)
            except httpx.TimeoutException as exc:
                raise TranscriptionError("provider_unavailable", "OpenAI request timed out") from exc
            except httpx.HTTPError as exc:
                raise TranscriptionError("provider_unavailable", f"OpenAI network error: {type(exc).__name__}") from exc

        if resp.status_code == 401:
            raise TranscriptionError("unauthorized", "OpenAI rejected the API key", status_code=401)
        if resp.status_code == 413:
            raise TranscriptionError("input_too_long", "OpenAI rejected file size", status_code=413)
        if resp.status_code == 429:
            raise TranscriptionError("rate_limited", "OpenAI rate limit hit", status_code=429)
        if resp.status_code >= 500:
            raise TranscriptionError("provider_unavailable", f"OpenAI {resp.status_code}", status_code=resp.status_code)
        if resp.status_code >= 400:
            raise TranscriptionError("output_invalid", f"OpenAI {resp.status_code}", status_code=resp.status_code)

        try:
            payload = resp.json()
            duration = float(payload["duration"])
            words = [
                TranscribedWord(text=w["word"], start=float(w["start"]), end=float(w["end"]))
                for w in payload.get("words", [])
            ]
            language_out = payload.get("language", language)
        except (KeyError, ValueError, TypeError) as exc:
            raise TranscriptionError("output_invalid", "Whisper response shape unexpected") from exc

        return WordLevelTranscript(
            language=language_out,
            duration_sec=duration,
            words=words,
            model_version=self._model,
            cost_usd=round(duration / 60.0 * _WHISPER_USD_PER_MIN, 6),
        )
