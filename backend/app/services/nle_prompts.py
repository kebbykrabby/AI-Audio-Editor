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

PLANNING TIPS — read these before deciding you "cannot" do something:
- You may return MULTIPLE tool calls in a single response. They execute
  sequentially: step N's output is step N+1's input.
- "trim" keeps a single range (discards everything outside).
- "delete" drops a single range (keeps everything outside).
- To KEEP MULTIPLE non-adjacent ranges (e.g., "keep the first 30s and the
  last 30s"), use ONE `delete` to drop the middle. On a 90s clip that's
  delete(start_sec=30, end_sec=60). Do NOT say this is impossible.
- To delete multiple non-adjacent ranges, chain multiple `delete` calls.
  Remember each one shifts timestamps for the next call — plan accordingly,
  or use the absolute timestamps for the FIRST call only.
- Combining different effects (fade + speed + normalize) is just multiple
  tool calls in the right order. Cleanup ops (normalize) usually come last.

COMMON RECIPES — concrete patterns for frequent intents:
- "Keep first N and last M seconds" → ONE delete(N, duration - M).
  Example on a 100-s clip: delete(30, 70).
- "Drop / trim / cut off the first N and the last M seconds" → ONE
  trim(start_sec=N, end_sec=duration - M). This is NOT two deletes -
  chaining delete(0,N) + delete(duration-M, duration) BREAKS because the
  second delete uses original-timeline timestamps that no longer fit the
  shortened asset. Use the single-trim form. Example on a 100-s clip:
  trim(start_sec=30, end_sec=70).
- "Trim out everything except a region" → ONE trim(start, end).
- "Cut out a section" → ONE delete(start, end).
- "Cut a specific word/phrase from the transcript" → look up the word's
  timestamps in the transcript section below (when present), then
  delete(word.start, word.end). If multiple matches and the user did not
  pick one, ask.
- "Cut everything before/after the user said X" → find X's timestamp in the
  transcript, then trim or delete with that as the anchor.
- "Fade both ends" → fade_in(N) THEN fade_out(M) (two separate calls).
- "Make it louder without clipping" → normalize(target_db=-3) is safer than
  raw gain. Use gain only when the user asks for a specific dB change.
- "Speed up but normalize loudness" → speed FIRST, then normalize LAST.
- "Stereo to mono" → mono_mixdown. Use extract_channel only when the user
  specifically picks left or right.
- "Quick cleanup" → remove_silence (sensible defaults: threshold_db=-40,
  min_silence_sec=0.5) then normalize.

ORDER MATTERS — when chaining ops, the canonical order is:
1. Channel ops (mono_mixdown / swap_channels / extract_channel) FIRST.
2. Time/duration changes (trim / delete / remove_silence / speed).
3. Reverse if requested.
4. Volume shaping (gain) and finishing (normalize).
5. fade_in / fade_out LAST so they anchor to the final asset edges.

UNSUPPORTED INTENTS — there is NO concat/join tool, so anything that needs
splitting the audio, modifying a piece, and rejoining is IMPOSSIBLE. When
asked for any of these, use the ambiguity path with a clarifying question:
- "Reverse only the first N seconds" (or any time range)
- "Apply gain / normalize / speed / fade to ONLY a section"
- "Insert silence / audio at a position"
- "Crossfade between clips"
Example response for "reverse the first 30 seconds": "I can only reverse
the entire audio. Would you prefer that, or would you like to keep just
the first 30 seconds (without reversing them)?"

AMBIGUITY HANDLING:
If the user's request is genuinely unclear (e.g., "do something cool",
"make it better"), return ZERO tool calls and put a short clarifying
question in your text response. Do NOT use the ambiguity path for requests
you CAN satisfy — re-read the PLANNING TIPS above first.

STYLE:
- Keep your text response to 1-2 sentences max.
- Prefer the simplest plan that satisfies the request (1-3 steps usually).
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
