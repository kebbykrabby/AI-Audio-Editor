"""Heuristic filler-word detector.

Consumes a `WordLevelTranscript` (from a `TranscriptionProvider`) and emits
a list of `FillerRegion`s — candidate cuts the user will review before committing.

Categories (MVP):
- ``um`` / ``uh`` / ``er``: pure fillers; high base confidence.
- ``stutter``: immediate repetition of the same short word (``I I``, ``the the``).
- ``like`` / ``so`` / ``you_know`` / ``i_mean``: discourse markers; classified
  at a lower base confidence because comparison / connective uses are common.

No model call — this is a pure function over the transcript. An LLM-based
classifier is an explicit v1.2 follow-up; see `project_ai_filler_words.md`.
"""
from __future__ import annotations

import re
from pydantic import BaseModel

from app.providers.transcription import WordLevelTranscript

_PURE_FILLERS = {"um", "umm", "ummm", "uh", "uhh", "uhhh", "er", "erm", "ah", "eh", "hm", "hmm"}
_DISCOURSE_MARKERS = {"like", "so", "actually", "basically", "literally"}
_STUTTER_MAX_LEN = 4  # only treat short-word repetitions as stutter
_PUNCT_RE = re.compile(r"[^\w']+")


class FillerRegion(BaseModel):
    start: float           # seconds; matches transcript word start
    end: float             # seconds; matches transcript word end (or last word of a phrase)
    text: str              # the actual transcribed text of the region
    category: str          # "um" | "uh" | "er" | "stutter" | "like" | "so" | "you_know" | "i_mean" | ...
    confidence: float      # classifier-assigned, 0.0-1.0
    word_index: int        # index into transcript.words of the first word in this region


def _normalize(text: str) -> str:
    return _PUNCT_RE.sub("", text).lower()


def detect_fillers(
    transcript: WordLevelTranscript,
    confidence_threshold: float = 0.0,
    categories: frozenset[str] | None = None,
) -> list[FillerRegion]:
    """Classify each transcribed word (or adjacent pair) against the filler rules.

    `confidence_threshold` filters the output; pass 0.0 to return everything
    so the UI can re-filter with its slider. `categories` restricts emission
    to a subset; pass None to enable all.
    """
    words = transcript.words
    regions: list[FillerRegion] = []

    i = 0
    while i < len(words):
        w = words[i]
        norm = _normalize(w.text)
        if not norm:
            i += 1
            continue

        # --- Two-word phrases first (consume i and i+1) ---
        next_norm = _normalize(words[i + 1].text) if i + 1 < len(words) else ""
        if norm == "you" and next_norm == "know":
            regions.append(FillerRegion(
                start=w.start, end=words[i + 1].end,
                text=f"{w.text} {words[i + 1].text}",
                category="you_know", confidence=0.60, word_index=i,
            ))
            i += 2
            continue
        if norm == "i" and next_norm == "mean":
            regions.append(FillerRegion(
                start=w.start, end=words[i + 1].end,
                text=f"{w.text} {words[i + 1].text}",
                category="i_mean", confidence=0.55, word_index=i,
            ))
            i += 2
            continue

        # --- Single-word classifications ---
        if norm in _PURE_FILLERS:
            if norm.startswith("um") or norm == "hm" or norm == "hmm":
                category = "um"
            elif norm.startswith("uh"):
                category = "uh"
            else:
                category = "er"
            regions.append(FillerRegion(
                start=w.start, end=w.end, text=w.text,
                category=category, confidence=0.95, word_index=i,
            ))
            i += 1
            continue

        if norm in _DISCOURSE_MARKERS:
            regions.append(FillerRegion(
                start=w.start, end=w.end, text=w.text,
                category=norm, confidence=0.55, word_index=i,
            ))
            i += 1
            continue

        # Stutter: immediate repeat of the prior word, short word only.
        if (
            i > 0
            and len(norm) <= _STUTTER_MAX_LEN
            and norm == _normalize(words[i - 1].text)
        ):
            regions.append(FillerRegion(
                start=w.start, end=w.end, text=w.text,
                category="stutter", confidence=0.75, word_index=i,
            ))
            i += 1
            continue

        i += 1

    if categories is not None:
        regions = [r for r in regions if r.category in categories]
    if confidence_threshold > 0.0:
        regions = [r for r in regions if r.confidence >= confidence_threshold]
    return regions
