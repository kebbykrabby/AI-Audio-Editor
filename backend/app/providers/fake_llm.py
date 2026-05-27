"""Deterministic LLM provider for tests + offline dev.

Mirrors `FakeTranscriptionProvider`: holds a canned `LlmPlanResponse` and
returns it on every call regardless of input. Tests can inject custom
plans via the constructor; the default returns an empty plan with a
"no provider configured" final_response so a mistaken prod wire-up
fails loudly rather than silently emitting random ops.
"""
from __future__ import annotations

from app.providers.llm import (
    LlmPlanResponse,
    LLMProvider,
    ToolCall,
    ToolDefinition,
)


class FakeLLMProvider(LLMProvider):
    def __init__(self, response: LlmPlanResponse | None = None):
        self._response = response or LlmPlanResponse(
            tool_calls=[],
            final_response=(
                "No real LLM provider is configured. Set LLM_PROVIDER=gemini "
                "and add GEMINI_API_KEY to backend/.env to enable plan generation."
            ),
            model_version="fake-v1",
            cost_usd=0.0,
        )

    async def generate_plan(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        tools: list[ToolDefinition],
        max_tool_calls: int = 10,
    ) -> LlmPlanResponse:
        # Inputs are accepted but ignored — the response is pre-baked.
        _ = (system_prompt, user_prompt, tools, max_tool_calls)
        return self._response


def make_plan_response(
    *,
    tool_calls: list[tuple[str, dict]],
    final_response: str = "",
    model_version: str = "fake-v1",
    cost_usd: float = 0.0,
) -> LlmPlanResponse:
    """Test helper: build an `LlmPlanResponse` from a list of (tool_name, args)
    tuples. Saves callers from constructing `ToolCall`s manually.
    """
    return LlmPlanResponse(
        tool_calls=[ToolCall(tool_name=n, arguments=a) for n, a in tool_calls],
        final_response=final_response,
        model_version=model_version,
        cost_usd=cost_usd,
    )
