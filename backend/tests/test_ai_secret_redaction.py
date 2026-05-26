"""Verifies the WhisperProvider never leaks the OPENAI_API_KEY.

The Auth Specialist's Hard Standard: no credential in any logged line, exception
message, or exception __repr__. We mock OpenAI responses across the realistic
failure modes (401/429/5xx, network error, malformed body) and assert the
literal API key is absent from caplog output and exception strings.
"""
from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest

from app.providers.transcription import TranscriptionError
from app.providers.whisper import WhisperProvider

_FAKE_KEY = "sk-redactiontest-abcdef-0123456789"


def _audio_file(tmp_path: Path) -> Path:
    p = tmp_path / "clip.wav"
    # Minimal RIFF/WAVE header + no data. Whisper never sees it (mock intercepts),
    # the provider just reads bytes.
    p.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    return p


async def _run_and_capture(caplog, key: str, transport: httpx.MockTransport, audio: Path):
    # Swap httpx's default AsyncClient to use the mock transport.
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        return original_init(self, *args, **kwargs)

    httpx.AsyncClient.__init__ = patched_init  # type: ignore[assignment]
    try:
        provider = WhisperProvider(api_key=key)
        caplog.set_level(logging.DEBUG)
        try:
            await provider.transcribe(audio)
        except TranscriptionError as e:
            return e
        return None
    finally:
        httpx.AsyncClient.__init__ = original_init  # type: ignore[assignment]


async def test_401_does_not_leak_key(tmp_path, caplog):
    audio = _audio_file(tmp_path)
    transport = httpx.MockTransport(lambda req: httpx.Response(401, json={"error": "bad key"}))
    err = await _run_and_capture(caplog, _FAKE_KEY, transport, audio)
    assert err is not None and err.kind == "unauthorized"
    _assert_no_key_anywhere(caplog, err)


async def test_429_does_not_leak_key(tmp_path, caplog):
    audio = _audio_file(tmp_path)
    transport = httpx.MockTransport(lambda req: httpx.Response(429, json={"error": "slow down"}))
    err = await _run_and_capture(caplog, _FAKE_KEY, transport, audio)
    assert err is not None and err.kind == "rate_limited"
    _assert_no_key_anywhere(caplog, err)


async def test_500_does_not_leak_key(tmp_path, caplog):
    audio = _audio_file(tmp_path)
    transport = httpx.MockTransport(lambda req: httpx.Response(503, text="upstream boom"))
    err = await _run_and_capture(caplog, _FAKE_KEY, transport, audio)
    assert err is not None and err.kind == "provider_unavailable"
    _assert_no_key_anywhere(caplog, err)


async def test_malformed_body_does_not_leak_key(tmp_path, caplog):
    audio = _audio_file(tmp_path)
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"not": "a transcript"}))
    err = await _run_and_capture(caplog, _FAKE_KEY, transport, audio)
    assert err is not None and err.kind == "output_invalid"
    _assert_no_key_anywhere(caplog, err)


async def test_network_error_does_not_leak_key(tmp_path, caplog):
    audio = _audio_file(tmp_path)

    def boom(req):
        raise httpx.ConnectError("cannot reach host")

    transport = httpx.MockTransport(boom)
    err = await _run_and_capture(caplog, _FAKE_KEY, transport, audio)
    assert err is not None and err.kind == "provider_unavailable"
    _assert_no_key_anywhere(caplog, err)


def _assert_no_key_anywhere(caplog, err: TranscriptionError | None) -> None:
    # 1. no full key in captured logs
    for record in caplog.records:
        assert _FAKE_KEY not in record.getMessage(), f"API key leaked in log: {record.getMessage()!r}"
    # 2. no key in exception message / repr
    if err is not None:
        assert _FAKE_KEY not in str(err)
        assert _FAKE_KEY not in repr(err)
    # 3. no `sk-` substring either — defense in depth
    for record in caplog.records:
        assert "sk-" not in record.getMessage(), f"key-like token in log: {record.getMessage()!r}"


def test_constructor_rejects_placeholder():
    with pytest.raises(TranscriptionError) as exc:
        WhisperProvider(api_key="CHANGE_ME")
    assert exc.value.kind == "unauthorized"
    assert "CHANGE_ME" not in str(exc.value)  # don't echo the literal back either


def test_constructor_rejects_empty():
    with pytest.raises(TranscriptionError) as exc:
        WhisperProvider(api_key="")
    assert exc.value.kind == "unauthorized"
