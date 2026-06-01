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


# Fields most tool-calling APIs (Google FunctionDeclaration in particular)
# accept on a parameter property schema. Everything else is stripped before
# the schema reaches the API. Whitelist > blacklist because the surface keeps
# evolving as JSON Schema drafts and provider implementations diverge.
_ALLOWED_PARAM_FIELDS: frozenset[str] = frozenset({
    "type", "description", "enum", "format", "nullable",
    "minimum", "maximum",
    "minLength", "maxLength",
    "items", "properties", "required",
    "anyOf",
})


def _sanitize_property(schema: dict) -> dict:
    """Map a Pydantic-emitted property schema to the subset Google + co. accept.

    Concretely:
    - `exclusiveMinimum: N` (Pydantic 2 style for `gt=N`) → `minimum: N`
    - `exclusiveMaximum: N` (Pydantic 2 style for `lt=N`) → `maximum: N`
      (The strictness loss is paid back by server-side Pydantic re-validation
      in `nle_service._validate_tool_call`, which uses the original schema.)
    - Drop anything outside `_ALLOWED_PARAM_FIELDS` — title, default, examples,
      additionalProperties, etc. don't help the LLM and may be rejected.
    - Recurse into nested `items` / `properties` because list element schemas
      and nested object props can carry the same gotchas.
    """
    out: dict[str, Any] = {}
    for k, v in schema.items():
        if k == "exclusiveMinimum":
            out["minimum"] = v
        elif k == "exclusiveMaximum":
            out["maximum"] = v
        elif k in _ALLOWED_PARAM_FIELDS:
            if k == "items" and isinstance(v, dict):
                out[k] = _sanitize_property(v)
            elif k == "properties" and isinstance(v, dict):
                out[k] = {pk: _sanitize_property(pv) for pk, pv in v.items()}
            elif k == "anyOf" and isinstance(v, list):
                out[k] = [_sanitize_property(s) if isinstance(s, dict) else s for s in v]
            else:
                out[k] = v
        # Silently drop anything else.
    return out


def operation_schema_to_tool(
    *,
    name: str,
    description: str,
    pydantic_schema: dict,
) -> ToolDefinition:
    """Translate a Pydantic `.model_json_schema()` output to a ToolDefinition.

    The Pydantic schema lives at `schemas/operation.py`; this helper massages
    the result into the shape every LLM tool-calling API accepts:
    - Top-level object schema with `properties` + `required`
    - Inline `anyOf` for nullable scalar types
    - Field whitelist via `_sanitize_property` — drops Pydantic-emitted
      fields the FunctionDeclaration validator rejects (title, exclusive*,
      default, examples, etc.) and converts exclusiveMinimum/Maximum to
      minimum/maximum

    Note: the per-field range constraints communicated to the LLM are
    slightly looser than the server's Pydantic validation (gt → ge). The
    server is still the source of truth — `_validate_tool_call` re-runs the
    original schema and catches any tool calls with strictly-zero values.
    """
    cleaned: dict[str, Any] = {
        "type": "object",
        "properties": {},
    }
    props = pydantic_schema.get("properties", {})
    required = list(pydantic_schema.get("required", []))
    for key, schema in props.items():
        flat = _scalar(schema) if isinstance(schema, dict) else schema
        if isinstance(flat, dict):
            cleaned["properties"][key] = _sanitize_property(flat)
        else:
            cleaned["properties"][key] = flat
    if required:
        cleaned["required"] = required
    return ToolDefinition(
        name=name,
        description=description,
        parameters_schema=cleaned,
    )
