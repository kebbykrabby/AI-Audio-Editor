"""LLM provider Protocol for natural-language editing.

Parallel to `providers/transcription.py`. Three adapters at launch:
- `FakeLLMProvider` — deterministic; tests + offline dev; default.
- `GeminiLLMProvider` — Google Gemini 2.0 Flash via Google AI Studio (free tier).
- `AnthropicLLMProvider` / `OpenAILLMProvider` — Phase 5 polish; same interface.

The provider is responsible for tool-calling: given a list of tool definitions
(JSON Schema per tool), it returns a structured `LlmPlanResponse` with the
tool calls the LLM chose and any `final_response` clarification text.

Hallucinated tool names should NOT be possible — every real LLM tool-calling
API enforces the tool name comes from the provided list. Argument
hallucination is caught downstream by Pydantic schema validation in
`operation_service._validate_params`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolDefinition:
    """One tool the LLM is allowed to call.

    Maps 1:1 to an operation type. `parameters_schema` is a JSON Schema dict
    (Pydantic's `.model_json_schema()` output, cleaned up).
    """
    name: str
    description: str
    parameters_schema: dict


@dataclass
class ToolCall:
    """One operation the LLM proposed."""
    tool_name: str   # operation type, e.g. "trim", "fade_out"
    arguments: dict  # operation parameters, matching the schema


@dataclass
class LlmPlanResponse:
    """Structured response from an LLM provider.

    `tool_calls` is the proposed plan, in execution order. Empty if the LLM
    couldn't or didn't propose any (ambiguity case — see `final_response`).
    `final_response` is the natural-language text the LLM emitted alongside
    its tool calls. For ambiguity it carries a clarifying question; for a
    successful plan it's typically a short summary or empty.
    """
    tool_calls: list[ToolCall]
    final_response: str
    model_version: str
    cost_usd: float
    # Raw API response for debugging / auditing; kept opaque on purpose.
    raw_response: dict = field(default_factory=dict)


class LLMProviderError(Exception):
    """Raised by adapters when the underlying API rejects the call.

    Mirrors `TranscriptionError`'s `kind` taxonomy so callers can translate
    cleanly to user-facing error codes:
    - `provider_unavailable`: library missing, network down, model not found
    - `unauthorized`: bad / missing API key
    - `rate_limited`: provider quota hit
    - `output_invalid`: LLM returned malformed structured output
    """
    def __init__(self, kind: str, message: str):
        self.kind = kind
        super().__init__(message)


class LLMProvider(Protocol):
    """Generate a structured plan given a prompt and tool definitions."""

    async def generate_plan(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        tools: list[ToolDefinition],
        max_tool_calls: int = 10,
    ) -> LlmPlanResponse:
        """Call the LLM with the prompt + tools and return a structured plan.

        Raises `LLMProviderError` on transport / auth / quota / output issues.
        Successful responses with zero tool calls are NOT an error — that's
        the documented ambiguity path; the caller surfaces `final_response`
        to the user.

        `max_tool_calls` is a soft cap to prevent a runaway plan; providers
        should pass it to their API where supported.
        """
        ...


def _scalar(value: Any) -> Any:
    """JSON Schema sometimes uses anyOf for `int | None`. Tool-call APIs prefer
    simple types — this flattens to the primary non-null type when possible.
    """
    if isinstance(value, dict) and "anyOf" in value:
        non_null = [s for s in value["anyOf"] if s.get("type") != "null"]
        if len(non_null) == 1:
            return non_null[0]
    return value


def operation_schema_to_tool(
    *,
    name: str,
    description: str,
    pydantic_schema: dict,
) -> ToolDefinition:
    """Translate a Pydantic `.model_json_schema()` output to a ToolDefinition.

    The Pydantic schema lives at `schemas/operation.py`; this helper just
    massages the result into the shape LLM tool-calling APIs expect:
    - Top-level object schema with `properties` + `required`
    - Strip `$defs` and `title` cruft
    - Inline `anyOf` for nullable scalar types
    - Pass through `enum`, `Literal`, range constraints (gt/ge/lt/le)
    """
    cleaned: dict[str, Any] = {
        "type": "object",
        "properties": {},
    }
    props = pydantic_schema.get("properties", {})
    required = list(pydantic_schema.get("required", []))
    for key, schema in props.items():
        s = dict(_scalar(schema))
        # Drop noisy metadata that doesn't help the LLM.
        s.pop("title", None)
        cleaned["properties"][key] = s
    if required:
        cleaned["required"] = required
    return ToolDefinition(
        name=name,
        description=description,
        parameters_schema=cleaned,
    )
