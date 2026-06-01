"""Unit tests for the LLM provider Protocol + FakeLLMProvider + tool catalog.

Pure unit tests: no network, no LLM credits, no DB. Verifies the contract
that future real providers (Gemini, Anthropic, OpenAI) need to match.
"""
from __future__ import annotations

import pytest

from app.providers.fake_llm import FakeLLMProvider, make_plan_response
from app.providers.llm import (
    LlmPlanResponse,
    operation_schema_to_tool,
)
from app.schemas.operation import (
    FadeInParams,
    SpeedParams,
    TrimParams,
)
from app.services.nle_prompts import (
    build_system_prompt,
    build_tool_catalog,
)


# --- FakeLLMProvider --------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_default_response_is_helpful_not_silent():
    """The default FakeLLMProvider should fail loudly via final_response so
    a mistaken prod wire-up is visible to the user."""
    p = FakeLLMProvider()
    out = await p.generate_plan(
        system_prompt="ignored",
        user_prompt="ignored",
        tools=[],
    )
    assert out.tool_calls == []
    assert "GEMINI_API_KEY" in out.final_response or "LLM_PROVIDER" in out.final_response
    assert out.model_version == "fake-v1"


@pytest.mark.asyncio
async def test_fake_returns_injected_response():
    canned = make_plan_response(
        tool_calls=[
            ("trim", {"start_sec": 0.0, "end_sec": 30.0}),
            ("fade_out", {"duration_sec": 2.0, "curve": "linear"}),
        ],
        final_response="Trimming and fading.",
    )
    p = FakeLLMProvider(response=canned)
    out = await p.generate_plan(
        system_prompt="anything",
        user_prompt="anything",
        tools=[],
    )
    assert len(out.tool_calls) == 2
    assert out.tool_calls[0].tool_name == "trim"
    assert out.tool_calls[0].arguments == {"start_sec": 0.0, "end_sec": 30.0}
    assert out.tool_calls[1].tool_name == "fade_out"
    assert out.final_response == "Trimming and fading."


@pytest.mark.asyncio
async def test_fake_ignores_inputs():
    """Fake should be deterministic per construction; inputs don't change output."""
    canned = make_plan_response(tool_calls=[("reverse", {})])
    p = FakeLLMProvider(response=canned)
    r1 = await p.generate_plan(system_prompt="a", user_prompt="b", tools=[])
    r2 = await p.generate_plan(system_prompt="c", user_prompt="d", tools=[])
    assert r1 == r2


# --- Tool schema serialization ---------------------------------------------


def test_operation_schema_to_tool_strips_pydantic_noise():
    tool = operation_schema_to_tool(
        name="trim",
        description="Keep range.",
        pydantic_schema=TrimParams.model_json_schema(),
    )
    assert tool.name == "trim"
    schema = tool.parameters_schema
    assert schema["type"] == "object"
    assert "start_sec" in schema["properties"]
    assert "end_sec" in schema["properties"]
    # title fields would just confuse the LLM; strip them.
    for prop in schema["properties"].values():
        assert "title" not in prop


def test_operation_schema_to_tool_preserves_range_constraints():
    """Pydantic Field(ge=0.25, le=4.0) on speed factor → schema retains the
    minimum/maximum so the LLM gets the same guard rails the server enforces."""
    tool = operation_schema_to_tool(
        name="speed",
        description="Change speed.",
        pydantic_schema=SpeedParams.model_json_schema(),
    )
    factor = tool.parameters_schema["properties"]["factor"]
    assert factor.get("minimum") == 0.25
    assert factor.get("maximum") == 4.0


def test_operation_schema_to_tool_required_list():
    tool = operation_schema_to_tool(
        name="fade_in",
        description="Fade in.",
        pydantic_schema=FadeInParams.model_json_schema(),
    )
    # duration_sec has no default → required.
    assert "duration_sec" in tool.parameters_schema["required"]


def test_operation_schema_to_tool_converts_exclusive_min_to_minimum():
    """`Field(gt=0)` emits `exclusiveMinimum: 0` in modern Pydantic, which the
    Gemini FunctionDeclaration validator rejects as an extra field. Sanitizer
    converts it to `minimum: 0` so the LLM still gets a guard rail and the
    Google SDK accepts the tool definition.

    Original schema validity is enforced server-side by Pydantic re-running
    the *original* schema on each tool call (`_validate_tool_call`); the LLM
    just gets a slightly looser hint.
    """
    tool = operation_schema_to_tool(
        name="fade_in",
        description="Fade in.",
        pydantic_schema=FadeInParams.model_json_schema(),
    )
    duration = tool.parameters_schema["properties"]["duration_sec"]
    assert "exclusiveMinimum" not in duration, (
        "exclusiveMinimum must be stripped — Gemini's FunctionDeclaration "
        "rejects it as an extra field"
    )
    assert duration.get("minimum") == 0


def test_operation_schema_to_tool_strips_unknown_fields():
    """Whitelist enforcement — fields outside _ALLOWED_PARAM_FIELDS are dropped,
    even if Pydantic added them. Pin one common offender: `default`.
    """
    # Build a synthetic schema with an extra field to make sure the whitelist
    # actually drops things and isn't a coincidental no-op.
    fake_schema = {
        "properties": {
            "thing": {
                "type": "number",
                "default": 42,
                "examples": [1, 2, 3],
                "title": "Thing",
            },
        },
        "required": ["thing"],
    }
    tool = operation_schema_to_tool(
        name="fake_op",
        description="A fake op.",
        pydantic_schema=fake_schema,
    )
    thing = tool.parameters_schema["properties"]["thing"]
    assert thing == {"type": "number"}


def test_operation_schema_to_tool_strips_exclusive_min_for_remove_silence():
    """RemoveSilenceParams.min_silence_sec uses gt=0, le=10 → same trap."""
    from app.schemas.operation import RemoveSilenceParams
    tool = operation_schema_to_tool(
        name="remove_silence",
        description="Remove silence.",
        pydantic_schema=RemoveSilenceParams.model_json_schema(),
    )
    min_sil = tool.parameters_schema["properties"]["min_silence_sec"]
    assert "exclusiveMinimum" not in min_sil
    assert min_sil.get("minimum") == 0
    assert min_sil.get("maximum") == 10


# --- System prompt assembly ------------------------------------------------


def test_system_prompt_includes_asset_metadata():
    prompt = build_system_prompt(
        duration_sec=120.5, sample_rate=44100, channels=2,
    )
    assert "120.50 seconds" in prompt
    assert "44100" in prompt
    assert "stereo" in prompt


def test_system_prompt_mono_label():
    prompt = build_system_prompt(
        duration_sec=10.0, sample_rate=48000, channels=1,
    )
    assert "mono" in prompt
    assert "stereo" not in prompt.split("Channels:")[1].split("\n")[0]


def test_system_prompt_omits_selection_block_when_none():
    prompt = build_system_prompt(
        duration_sec=10.0, sample_rate=48000, channels=1,
    )
    assert "currently SELECTED" not in prompt


def test_system_prompt_includes_selection_when_set():
    prompt = build_system_prompt(
        duration_sec=60.0, sample_rate=44100, channels=2,
        selection=(5.5, 12.3),
    )
    assert "currently SELECTED" in prompt
    assert "5.50s" in prompt
    assert "12.30s" in prompt


def test_system_prompt_omits_transcript_block_when_none():
    prompt = build_system_prompt(
        duration_sec=10.0, sample_rate=48000, channels=1,
    )
    assert "WORD-LEVEL TRANSCRIPT" not in prompt


def test_system_prompt_includes_transcript_when_set():
    words = [
        {"text": "hello", "start": 0.0, "end": 0.4},
        {"text": "world", "start": 0.5, "end": 0.9},
    ]
    prompt = build_system_prompt(
        duration_sec=10.0, sample_rate=44100, channels=2,
        transcript_words=words,
    )
    assert "WORD-LEVEL TRANSCRIPT" in prompt
    assert "hello" in prompt
    assert "world" in prompt
    assert "0.00 - 0.40" in prompt


def test_system_prompt_states_channel_count_for_validation():
    """The system prompt must tell the LLM the current channel count so it
    won't propose stereo-only ops on a mono asset."""
    prompt_mono = build_system_prompt(
        duration_sec=10.0, sample_rate=48000, channels=1,
    )
    assert "channels: 1" in prompt_mono.lower() or "channels >= 2" in prompt_mono.lower()
    # And the rule itself is in the prompt:
    assert "mono_mixdown" in prompt_mono


# --- Tool catalog ----------------------------------------------------------


def test_tool_catalog_has_all_supported_ops():
    catalog = build_tool_catalog()
    names = {t.name for t in catalog}
    # The 12 operations the design doc commits to.
    expected = {
        "trim", "delete", "fade_in", "fade_out", "gain", "normalize",
        "reverse", "remove_silence", "speed",
        "mono_mixdown", "swap_channels", "extract_channel",
    }
    assert names == expected


def test_tool_catalog_excludes_segment_ops():
    """remove_segments and censor_segments are intentionally EXCLUDED from MVP
    (they require region lists that don't fit a natural-language ask)."""
    names = {t.name for t in build_tool_catalog()}
    assert "remove_segments" not in names
    assert "censor_segments" not in names


def test_tool_catalog_order_is_stable():
    """Same call twice → same order. Important for LLM provider prompt-caching."""
    a = [t.name for t in build_tool_catalog()]
    b = [t.name for t in build_tool_catalog()]
    assert a == b


def test_each_tool_has_description():
    for t in build_tool_catalog():
        assert t.description, f"{t.name} has empty description"
        assert len(t.description) > 20, f"{t.name} description too short"


def test_each_tool_has_object_schema():
    for t in build_tool_catalog():
        assert t.parameters_schema["type"] == "object"


# --- LlmPlanResponse contract ----------------------------------------------


def test_response_round_trip_via_dataclass():
    """A response built from make_plan_response should be a vanilla
    LlmPlanResponse (so consumers can pattern-match on it without surprises).
    """
    resp = make_plan_response(tool_calls=[("trim", {"start_sec": 0, "end_sec": 5})])
    assert isinstance(resp, LlmPlanResponse)
    assert resp.tool_calls[0].tool_name == "trim"
