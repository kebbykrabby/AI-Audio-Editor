"""Local Whisper transcription provider (faster-whisper / CTranslate2).

No API key, no per-call cost. The model is downloaded once on first use and
cached under HF_HOME (default `~/.cache/huggingface`); subsequent transcribes
hit the cached model. Runs on CPU out of the box; auto-uses CUDA when
available.

Swap back to the OpenAI REST path by setting `TRANSCRIPTION_PROVIDER=openai`
and `OPENAI_API_KEY=...` — `providers.whisper.WhisperProvider` is retained
for that future switch so the change is one config line, not a rewrite.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.providers.transcription import (
    TranscribedWord,
    TranscriptionError,
    TranscriptionProvider,
    WordLevelTranscript,
)


class LocalWhisperProvider(TranscriptionProvider):
    """Adapter over `faster-whisper`.

    Instantiate once per worker process — model load is ~1–3 s and allocates
    ~150–500 MB depending on model size. The constructor does NOT load the
    model; first `transcribe()` call does. This keeps import cost predictable
    for the worker entrypoint.
    """

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "auto",
    ):
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model = None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise TranscriptionError(
                "provider_unavailable",
                "faster-whisper is not installed; pip install faster-whisper",
            ) from e
        try:
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
        except Exception as e:
            raise TranscriptionError(
                "provider_unavailable",
                f"failed to load whisper model ({type(e).__name__})",
            ) from e

    async def transcribe(
        self, audio_path: Path, language: str = "en"
    ) -> WordLevelTranscript:
        self._ensure_model()
        loop = asyncio.get_event_loop()

        def _run() -> tuple[list[TranscribedWord], str, float]:
            # `transcribe` returns (segments_generator, info). We must drain the
            # generator to realise word timestamps — it's lazy.
            segments, info = self._model.transcribe(  # type: ignore[union-attr]
                str(audio_path),
                language=language,
                word_timestamps=True,
                vad_filter=False,
            )
            out: list[TranscribedWord] = []
            for seg in segments:
                if not seg.words:
                    continue
                for w in seg.words:
                    out.append(TranscribedWord(
                        text=w.word.strip(),
                        start=float(w.start),
                        end=float(w.end),
                    ))
            return out, info.language, float(info.duration)

        try:
            words, detected_lang, duration = await loop.run_in_executor(None, _run)
        except TranscriptionError:
            raise
        except Exception as e:
            raise TranscriptionError(
                "provider_unavailable",
                f"local transcription failed ({type(e).__name__})",
            ) from e

        return WordLevelTranscript(
            language=detected_lang,
            duration_sec=duration,
            words=words,
            model_version=f"faster-whisper-{self._model_size}",
            cost_usd=0.0,
        )
