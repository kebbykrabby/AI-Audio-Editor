"""Unit tests for the Gemini LLM adapter.

Real network calls are NOT exercised here — every test mocks the SDK
response. A live-call smoke test that hits the actual Gemini API would
live in `scripts/smoke_gemini.py` (out of scope for unit-test runs).

What's covered:
- Constructor rejects empty API key with a clear `unauthorized` error
- Missing google-genai library → `provider_unavailable` from _ensure_client
- Response with only text → tool_calls=[], final_response carries the text
- Response with function_calls → ToolCall objects populated with name + args
- Mixed text + function_calls → both populated
- max_tool_calls truncation
- Cost estimate from usage_metadata for a priced model
- Cost falls back to 0.0 for unknown / unpriced models without crashing
- API errors (mock raising) → LLMProviderError with the right kind based on
  HTTP status, with the API key redacted from the message
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.gemini_llm import GeminiLLMProvider, _redact
from app.providers.llm import LLMProviderError, ToolDefinition


# --- Construction + key redaction -------------------------------------------


def test_construction_rejects_empty_key():
    with pytest.raises(LLMProviderError) as exc:
        GeminiLLMProvider(api_key="", model="gemini-2.0-flash")
    assert exc.value.kind == "unauthorized"


def test_redact_replaces_key_with_placeholder():
    msg = "Authorization failed with key sk-very-secret-12345"
    out = _redact(msg, "sk-very-secret-12345")
    assert "sk-very-secret-12345" not in out
    assert "<redacted>" in out


def test_redact_handles_empty_inputs():
    assert _redact("", "key") == ""
    assert _redact("text", "") == "text"


def test_missing_library_raises_provider_unavailable(monkeypatch):
    """If google-genai is uninstalled, _ensure_client surfaces a clean error
    rather than letting an ImportError leak to the worker."""
    import sys
    p = GeminiLLMProvider(api_key="test-key", model="gemini-2.0-flash")
    monkeypatch.setitem(sys.modules, "google.genai", None)
    monkeypatch.setitem(sys.modules, "google", None)
    with pytest.raises(LLMProviderError) as exc:
        p._ensure_client()
    assert exc.value.kind == "provider_unavailable"
    assert "google-genai" in str(exc.value).lower() or "genai" in str(exc.value).lower()


# --- Response parsing (no network) ------------------------------------------


def _fake_response(
    *,
    text_parts: list[str] | None = None,
    function_calls: list[tuple[str, dict]] | None = None,
    input_tokens: int = 100,
    output_tokens: int = 50,
):
    """Build a SimpleNamespace that quacks like the SDK response shape.

    The adapter accesses these properties:
      response.candidates[0].content.parts[i].text
      response.candidates[0].content.parts[i].function_call.name
      response.candidates[0].content.parts[i].function_call.args
      response.usage_metadata.prompt_token_count
      response.usage_metadata.candidates_token_count
    """
    parts = []
    for t in text_parts or []:
        parts.append(SimpleNamespace(text=t, function_call=None))
    for name, args in function_calls or []:
        fc = SimpleNamespace(name=name, args=args)
        parts.append(SimpleNamespace(text=None, function_call=fc))

    content = SimpleNamespace(parts=parts)
    candidate = SimpleNamespace(content=content)
    usage = SimpleNamespace(
        prompt_token_count=input_tokens,
        candidates_token_count=output_tokens,
    )
    return SimpleNamespace(
        candidates=[candidate], usage_metadata=usage,
    )


@pytest.mark.asyncio
async def test_parse_text_only_response():
    """LLM returned an ambiguity-style text response (no tool calls).

    Tests the `_parse_response` helper directly so we don't need to mock
    the SDK call chain. Adapter must place text in `final_response` and
    return empty `tool_calls`.
    """
    p = GeminiLLMProvider(api_key="test-key", model="gemini-2.0-flash")
    resp = _fake_response(
        text_parts=["Did you mean trim or delete? Please clarify."],
    )
    parsed = p._parse_response(resp, max_tool_calls=10)
    assert parsed.tool_calls == []
    assert "trim or delete" in parsed.final_response
    assert parsed.model_version == "gemini-2.0-flash"


@pytest.mark.asyncio
async def test_parse_function_calls_only():
    p = GeminiLLMProvider(api_key="test-key", model="gemini-2.0-flash")
    resp = _fake_response(
        function_calls=[
            ("trim", {"start_sec": 0.0, "end_sec": 30.0}),
            ("fade_out", {"duration_sec": 2.0, "curve": "linear"}),
        ],
    )
    parsed = p._parse_response(resp, max_tool_calls=10)
    assert len(parsed.tool_calls) == 2
    assert parsed.tool_calls[0].tool_name == "trim"
    assert parsed.tool_calls[0].arguments == {"start_sec": 0.0, "end_sec": 30.0}
    assert parsed.tool_calls[1].tool_name == "fade_out"
    # No text → empty final_response.
    assert parsed.final_response == ""


@pytest.mark.asyncio
async def test_parse_mixed_text_and_function_calls():
    p = GeminiLLMProvider(api_key="test-key", model="gemini-2.0-flash")
    resp = _fake_response(
        text_parts=["I'll trim the first 30 seconds."],
        function_calls=[("trim", {"start_sec": 0.0, "end_sec": 30.0})],
    )
    parsed = p._parse_response(resp, max_tool_calls=10)
    assert len(parsed.tool_calls) == 1
    assert "trim the first" in parsed.final_response


@pytest.mark.asyncio
async def test_max_tool_calls_truncates():
    p = GeminiLLMProvider(api_key="test-key", model="gemini-2.0-flash")
    resp = _fake_response(
        function_calls=[
            ("reverse", {}),
            ("fade_in", {"duration_sec": 1.0, "curve": "linear"}),
            ("fade_out", {"duration_sec": 2.0, "curve": "linear"}),
        ],
    )
    parsed = p._parse_response(resp, max_tool_calls=2)
    assert len(parsed.tool_calls) == 2


@pytest.mark.asyncio
async def test_parse_empty_candidates_returns_helpful_message():
    """Defensive case — provider returned no candidates at all."""
    p = GeminiLLMProvider(api_key="test-key", model="gemini-2.0-flash")
    resp = SimpleNamespace(candidates=[], usage_metadata=None)
    parsed = p._parse_response(resp, max_tool_calls=10)
    assert parsed.tool_calls == []
    assert "no candidates" in parsed.final_response.lower()


# --- Cost estimation --------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_estimate_for_priced_model():
    """gemini-2.0-flash has known pricing. Verify the math."""
    p = GeminiLLMProvider(api_key="test-key", model="gemini-2.0-flash")
    resp = _fake_response(
        function_calls=[("reverse", {})],
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    parsed = p._parse_response(resp, max_tool_calls=10)
    # 1M input × $0.075 + 1M output × $0.30 = $0.375
    assert parsed.cost_usd == pytest.approx(0.375, abs=0.001)


@pytest.mark.asyncio
async def test_cost_zero_for_unknown_model_does_not_crash():
    p = GeminiLLMProvider(api_key="test-key", model="gemini-future-banana")
    resp = _fake_response(function_calls=[], input_tokens=100, output_tokens=50)
    parsed = p._parse_response(resp, max_tool_calls=10)
    assert parsed.cost_usd == 0.0


@pytest.mark.asyncio
async def test_cost_zero_when_usage_metadata_missing():
    p = GeminiLLMProvider(api_key="test-key", model="gemini-2.0-flash")
    resp = SimpleNamespace(
        candidates=[
            SimpleNamespace(content=SimpleNamespace(parts=[])),
        ],
        usage_metadata=None,
    )
    parsed = p._parse_response(resp, max_tool_calls=10)
    assert parsed.cost_usd == 0.0


# --- Error path mapping -----------------------------------------------------


@pytest.mark.asyncio
async def test_api_error_with_401_status_maps_to_unauthorized():
    p = GeminiLLMProvider(api_key="secret-test-key", model="gemini-2.0-flash")
    p._ensure_client()  # make _client non-None so the patch hits the call path

    err = Exception("auth failed using secret-test-key")
    setattr(err, "status_code", 401)

    fake_aio = MagicMock()
    fake_aio.models.generate_content = AsyncMock(side_effect=err)
    with patch.object(p, "_client", MagicMock(aio=fake_aio)):
        with pytest.raises(LLMProviderError) as exc:
            await p.generate_plan(
                system_prompt="s", user_prompt="u",
                tools=[ToolDefinition("trim", "Trim.", {"type": "object"})],
            )
    assert exc.value.kind == "unauthorized"
    # Key must be redacted from the message.
    assert "secret-test-key" not in str(exc.value)
    assert "<redacted>" in str(exc.value)


@pytest.mark.asyncio
async def test_api_error_with_429_maps_to_rate_limited():
    p = GeminiLLMProvider(api_key="k", model="gemini-2.0-flash")
    p._ensure_client()

    err = Exception("quota exhausted")
    setattr(err, "code", 429)

    fake_aio = MagicMock()
    fake_aio.models.generate_content = AsyncMock(side_effect=err)
    with patch.object(p, "_client", MagicMock(aio=fake_aio)):
        with pytest.raises(LLMProviderError) as exc:
            await p.generate_plan(
                system_prompt="s", user_prompt="u",
                tools=[ToolDefinition("trim", "Trim.", {"type": "object"})],
            )
    assert exc.value.kind == "rate_limited"


@pytest.mark.asyncio
async def test_api_error_without_status_maps_to_provider_unavailable():
    p = GeminiLLMProvider(api_key="k", model="gemini-2.0-flash")
    p._ensure_client()

    fake_aio = MagicMock()
    fake_aio.models.generate_content = AsyncMock(
        side_effect=Exception("network unreachable"),
    )
    with patch.object(p, "_client", MagicMock(aio=fake_aio)):
        with pytest.raises(LLMProviderError) as exc:
            await p.generate_plan(
                system_prompt="s", user_prompt="u",
                tools=[ToolDefinition("trim", "Trim.", {"type": "object"})],
            )
    assert exc.value.kind == "provider_unavailable"
