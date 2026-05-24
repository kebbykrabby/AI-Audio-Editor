"""Unit tests for the LocalWhisperProvider error-path behavior.

Real transcription requires the `faster-whisper` package and a downloaded
model — we don't exercise that in CI. Instead we verify:
- constructing the provider is cheap and doesn't load the model
- when the library is not importable, `_ensure_model` raises a clean
  `TranscriptionError(kind="provider_unavailable")` rather than an uncaught
  `ImportError` leaking to the worker.
"""
from __future__ import annotations

import sys

import pytest

from app.providers.local_whisper import LocalWhisperProvider
from app.providers.transcription import TranscriptionError


def test_construction_does_not_load_model():
    p = LocalWhisperProvider(model_size="tiny")
    assert p._model is None


def test_missing_library_raises_provider_unavailable(monkeypatch):
    # Blocks `from faster_whisper import WhisperModel` regardless of whether the
    # package is actually installed — setting the entry to None forces ImportError.
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    p = LocalWhisperProvider(model_size="tiny")
    with pytest.raises(TranscriptionError) as exc:
        p._ensure_model()
    assert exc.value.kind == "provider_unavailable"
    # Message should guide the user to install — not leak a raw ImportError repr.
    assert "faster-whisper" in str(exc.value) or "whisper" in str(exc.value).lower()
