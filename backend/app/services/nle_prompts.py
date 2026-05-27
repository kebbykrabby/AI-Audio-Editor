"""System prompt + tool catalog for natural-language editing.

The system prompt is curated. Reading it should fully explain the LLM's
contract; reading the user's prompt should never feel surprising on top of
that. Updates here are commit-reviewed like any code change — there's
no runtime override path.

The tool catalog is built from the Pydantic schemas in
`app/schemas/operation.py` via `operation_schema_to_tool` so the LLM's
parameter shapes stay in sync with what the server actually accepts.
"""
from __future__ import annotations

from app.providers.llm import ToolDefinition, operation_schema_to_tool
from app.schemas.operation import (
    DeleteParams,
    ExtractChannelParams,
    FadeInParams,
    FadeOutParams,
    GainParams,
    MonoMixdownParams,
    NormalizeParams,
    RemoveSilenceParams,
    ReverseParams,
    SpeedParams,
    SwapChannelsParams,
    TrimParams,
)


# --- System prompt --------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """You are an audio editing assistant for a browser-based audio editor.

Your job: take the user's plain-English request and translate it into a
sequence of one or more audio editing operations from the provided tool
list. The operations will be reviewed by the user before any audio is
actually changed.

ASSET METADATA (the audio the user is currently editing):
- Duration: {duration_sec:.2f} seconds
- Sample rate: {sample_rate} Hz
- Channels: {channels} ({channel_label})
{selection_context}
{transcript_context}

HARD RULES — operations that violate these are rejected before execution:
- All timestamps must be in [0, {duration_sec:.2f}] seconds.
- For trim/delete: start_sec must be < end_sec.
- For fade_in/fade_out: duration_sec must be < {duration_sec:.2f}.
- For speed: factor must be in [0.25, 4.0].
- mono_mixdown, swap_channels, and extract_channel REQUIRE channels >= 2.
  The current asset has {channels} channels — only propose these if appropriate.

AMBIGUITY HANDLING:
If the user's request is unclear, ambiguous, or asks for something you
cannot do with the provided tools, return ZERO tool calls and put a
short clarifying question in your text response. Do NOT guess.

STYLE:
- Keep your text response to 1-2 sentences max.
- Prefer the simplest plan that satisfies the request.
- Do not invent operations or parameters that aren't in the tool list.
"""


SELECTION_CONTEXT_TEMPLATE = (
    "- User has currently SELECTED the range "
    "{start_sec:.2f}s — {end_sec:.2f}s. "
    "Interpret phrases like 'this part', 'the selection', or 'here' as "
    "referring to this range."
)


TRANSCRIPT_CONTEXT_HEADER = (
    "- WORD-LEVEL TRANSCRIPT of the audio is provided below. Each entry "
    "lists the word and its start/end seconds. Use this to resolve content-"
    "based references like 'where I said hello' or 'the introduction'."
)


def build_system_prompt(
    *,
    duration_sec: float,
    sample_rate: int,
    channels: int,
    selection: tuple[float, float] | None = None,
    transcript_words: list[dict] | None = None,
) -> str:
    """Assemble the system prompt for a single NLE plan request.

    `transcript_words` is a list of `{text, start, end}` dicts (the shape
    `nle_service` produces from a `WordLevelTranscript`).
    """
    channel_label = (
        "mono" if channels == 1 else "stereo" if channels == 2 else f"{channels}-channel"
    )

    selection_block = ""
    if selection is not None:
        s, e = selection
        selection_block = "\n" + SELECTION_CONTEXT_TEMPLATE.format(
            start_sec=float(s), end_sec=float(e),
        )

    transcript_block = ""
    if transcript_words:
        lines = [TRANSCRIPT_CONTEXT_HEADER, ""]
        for w in transcript_words:
            lines.append(
                f"  [{float(w['start']):.2f} - {float(w['end']):.2f}] {w['text']}"
            )
        transcript_block = "\n" + "\n".join(lines)

    return SYSTEM_PROMPT_TEMPLATE.format(
        duration_sec=duration_sec,
        sample_rate=sample_rate,
        channels=channels,
        channel_label=channel_label,
        selection_context=selection_block,
        transcript_context=transcript_block,
    )


# --- Tool catalog ---------------------------------------------------------

# Map each operation type to a human-readable description the LLM uses to
# decide whether to invoke it. Keep these short; the JSON schema below
# gives the parameter detail.

_OP_DESCRIPTIONS: dict[str, str] = {
    "trim": (
        "Keep only the audio between two timestamps; discard the rest. "
        "Output duration = end_sec - start_sec."
    ),
    "delete": (
        "Remove a range of audio; keep the parts before and after spliced "
        "together. Output duration = original - (end_sec - start_sec)."
    ),
    "fade_in": (
        "Fade volume from silence to full over the first duration_sec "
        "seconds of the audio."
    ),
    "fade_out": (
        "Fade volume from full to silence over the last duration_sec "
        "seconds of the audio."
    ),
    "gain": (
        "Adjust overall volume by gain_db decibels. Positive = louder, "
        "negative = quieter. Range -60 to +24 dB."
    ),
    "normalize": (
        "Peak-normalize so the loudest sample reaches target_db "
        "(typically -3 to -1)."
    ),
    "reverse": "Reverse the entire audio. No parameters.",
    "remove_silence": (
        "Detect and remove silent gaps below threshold_db that last at least "
        "min_silence_sec. Output is shorter than input."
    ),
    "speed": (
        "Change playback speed by factor (0.25 to 4.0). Pitch is preserved. "
        "Output duration = original / factor."
    ),
    "mono_mixdown": (
        "Mix stereo audio down to mono via (L+R)/2. Requires stereo input."
    ),
    "swap_channels": (
        "Swap the left and right channels. Requires stereo input."
    ),
    "extract_channel": (
        "Extract the left or right channel from stereo input; output is mono. "
        "Requires stereo input."
    ),
}


_OP_PARAMS: dict[str, type] = {
    "trim": TrimParams,
    "delete": DeleteParams,
    "fade_in": FadeInParams,
    "fade_out": FadeOutParams,
    "gain": GainParams,
    "normalize": NormalizeParams,
    "reverse": ReverseParams,
    "remove_silence": RemoveSilenceParams,
    "speed": SpeedParams,
    "mono_mixdown": MonoMixdownParams,
    "swap_channels": SwapChannelsParams,
    "extract_channel": ExtractChannelParams,
}


def build_tool_catalog() -> list[ToolDefinition]:
    """Construct the LLM tool list for a single NLE plan request.

    Same order every time so prompt-caching at the LLM provider stays warm.
    """
    return [
        operation_schema_to_tool(
            name=op_type,
            description=_OP_DESCRIPTIONS[op_type],
            pydantic_schema=params_cls.model_json_schema(),
        )
        for op_type, params_cls in _OP_PARAMS.items()
    ]
