"""Google Gemini LLM provider via the `google-genai` SDK.

MVP default real provider. Sends the system prompt as `system_instruction`,
the user prompt as the user turn, and the tool catalog as function
declarations with `function_calling_config=AUTO`. Parses the response into
the framework-agnostic `LlmPlanResponse` shape.

Cost estimation comes from the response's `usage_metadata`. Gemini 2.0 Flash
pricing (current as of writing): ~$0.075 / 1M input tokens, $0.30 / 1M
output. Free tier covers low-volume use; the cost field still reports a
non-zero estimate so the audit log stays honest.

Key redaction: any exception or log line includes the API key only as
`<redacted>`. Never log `self._key` directly — see `_redact` below.
"""
from __future__ import annotations

import logging
from typing import Any

from app.providers.llm import (
    LlmPlanResponse,
    LLMProvider,
    LLMProviderError,
    ToolCall,
    ToolDefinition,
)

logger = logging.getLogger(__name__)


# Per-1M-token pricing for the Flash family. If we add other models, extend
# this map; falling back to (0, 0) means cost reports as 0 (better than
# crashing the audit log).
_PRICE_PER_M_TOKENS: dict[str, tuple[float, float]] = {
    # (input, output) USD per million tokens
    "gemini-2.0-flash": (0.075, 0.30),
    "gemini-2.0-flash-exp": (0.0, 0.0),  # experimental tier: free
    "gemini-2.0-flash-lite": (0.0375, 0.15),
    "gemini-2.5-flash": (0.30, 2.50),
}


def _redact(s: str, key: str) -> str:
    """Replace any occurrence of the API key with `<redacted>`."""
    if not key or not s:
        return s
    return s.replace(key, "<redacted>")


def _kind_for_status(http_status: int | None) -> str:
    if http_status is None:
        return "provider_unavailable"
    if http_status == 401:
        return "unauthorized"
    if http_status == 429:
        return "rate_limited"
    if 500 <= http_status < 600:
        return "provider_unavailable"
    return "provider_unavailable"


class GeminiLLMProvider(LLMProvider):
    """Adapter over Google's GenAI SDK.

    Instantiate once per worker process. The first `generate_plan` call
    establishes the underlying HTTP client; subsequent calls reuse it.
    """

    def __init__(self, *, api_key: str, model: str):
        if not api_key:
            raise LLMProviderError(
                "unauthorized",
                "GEMINI_API_KEY not configured; set it in backend/.env",
            )
        self._key = api_key
        self._model = model
        self._client: Any = None  # Lazy-initialized in _ensure_client.

    def _ensure_client(self) -> None:
        if self._client is not None:
            return
        try:
            from google import genai  # type: ignore[import-not-found]
        except ImportError as e:
            raise LLMProviderError(
                "provider_unavailable",
                "google-genai is not installed; pip install google-genai",
            ) from e
        try:
            self._client = genai.Client(api_key=self._key)
        except Exception as e:
            raise LLMProviderError(
                "provider_unavailable",
                _redact(f"failed to construct Gemini client ({type(e).__name__})", self._key),
            ) from e

    async def generate_plan(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        tools: list[ToolDefinition],
        max_tool_calls: int = 10,
    ) -> LlmPlanResponse:
        self._ensure_client()
        from google.genai import types as gtypes  # type: ignore[import-not-found]

        function_declarations = [
            gtypes.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters=t.parameters_schema,
            )
            for t in tools
        ]
        config = gtypes.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[gtypes.Tool(function_declarations=function_declarations)],
            tool_config=gtypes.ToolConfig(
                function_calling_config=gtypes.FunctionCallingConfig(mode="AUTO"),
            ),
            # Temperature kept low — we want deterministic plans, not creative
            # interpretations of "trim the first 5 seconds".
            temperature=0.1,
        )

        try:
            # google-genai exposes async via .aio.
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=config,
            )
        except Exception as e:
            # Surface HTTP status if the SDK attached it; otherwise the
            # exception class name is the best we can do.
            http_status = getattr(e, "status_code", None) or getattr(e, "code", None)
            try:
                http_status = int(http_status) if http_status else None
            except (TypeError, ValueError):
                http_status = None
            kind = _kind_for_status(http_status)
            msg = _redact(f"Gemini call failed: {type(e).__name__}: {e}", self._key)
            logger.warning("Gemini provider error (kind=%s): %s", kind, msg)
            raise LLMProviderError(kind, msg) from e

        return self._parse_response(response, max_tool_calls)

    def _parse_response(self, response: Any, max_tool_calls: int) -> LlmPlanResponse:
        """Pull text + function calls out of the SDK response.

        The SDK uses Pydantic-y types where `.text` and `.function_call`
        are accessor properties on each `Part`. Missing optionals are `None`.
        """
        tool_calls: list[ToolCall] = []
        text_chunks: list[str] = []

        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            # Defensive: malformed response shape from the SDK.
            return LlmPlanResponse(
                tool_calls=[],
                final_response="(provider returned no candidates)",
                model_version=self._model,
                cost_usd=self._cost_from_usage(response),
                raw_response=self._raw_dump(response),
            )

        first = candidates[0]
        content = getattr(first, "content", None)
        if content is None:
            return LlmPlanResponse(
                tool_calls=[],
                final_response="",
                model_version=self._model,
                cost_usd=self._cost_from_usage(response),
                raw_response=self._raw_dump(response),
            )

        for part in getattr(content, "parts", []) or []:
            text = getattr(part, "text", None)
            if text:
                text_chunks.append(text)
            fn_call = getattr(part, "function_call", None)
            if fn_call is not None:
                name = getattr(fn_call, "name", None) or ""
                args = getattr(fn_call, "args", None) or {}
                # SDK sometimes returns a MapComposite — coerce to plain dict.
                args_dict = dict(args) if args is not None else {}
                tool_calls.append(ToolCall(tool_name=name, arguments=args_dict))
                if len(tool_calls) >= max_tool_calls:
                    break

        return LlmPlanResponse(
            tool_calls=tool_calls,
            final_response="\n".join(c for c in text_chunks if c).strip(),
            model_version=self._model,
            cost_usd=self._cost_from_usage(response),
            raw_response=self._raw_dump(response),
        )

    def _cost_from_usage(self, response: Any) -> float:
        """Estimate USD cost from `usage_metadata` if the model is priced.

        Returns 0.0 for unpriced models or when metadata is missing — never
        crashes the audit log path.
        """
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return 0.0
        input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        price_in, price_out = _PRICE_PER_M_TOKENS.get(self._model, (0.0, 0.0))
        return (input_tokens * price_in + output_tokens * price_out) / 1_000_000

    def _raw_dump(self, response: Any) -> dict:
        """Best-effort opaque dump for debugging. Never raises."""
        try:
            # Prefer SDK's own model_dump if available; else stringify.
            if hasattr(response, "model_dump"):
                return {"sdk_model_dump": response.model_dump()}
            return {"repr": _redact(repr(response), self._key)}
        except Exception:  # pragma: no cover
            return {"unparseable": True}
