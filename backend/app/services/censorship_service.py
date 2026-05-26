"""Profanity detector — heuristic word-list match over a word-level transcript.

MVP scope (Phase 1):
- Built-in English profanity list (`BUILT_IN` constant below)
- Exact-match only (lowercase + punctuation strip vs. word set)
- One region per matched word, confidence=1.0, matched_by="exact"

Per-user word-list overrides land in Phase 3.
Variants + phonetic matchers land in Phase 4. The function signature is
intentionally pure (transcript + set in, regions out) so those matchers
can compose without touching this module's shape.

Word-list governance: BUILT_IN is intentionally curated. Each entry is a
complete word; the matcher tokenizes, so substring matches (the
"Scunthorpe problem") cannot fire — "assassin" will not match "ass"
because the matcher compares whole-word tokens, not substrings.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

from app.providers.transcription import WordLevelTranscript


_PUNCT_RE = re.compile(r"[^\w']+")


BUILT_IN: frozenset[str] = frozenset({
    "fuck", "fucks", "fucked", "fucking", "fucker", "fuckers", "fuckin",
    "shit", "shits", "shitting", "shitted", "shitty", "bullshit",
    "bitch", "bitches",
    "asshole", "assholes",
    "bastard", "bastards",
    "damn", "damned", "dammit", "goddamn", "goddamned",
    "piss", "pissed", "pissing",
    "crap", "crappy", "crapped",
    "cunt", "cunts",
    "dick", "dicks", "dickhead",
    "cock", "cocks",
    "pussy", "pussies",
    "tits", "titty", "tit",
    "bollocks",
    "wanker", "wankers",
    "twat", "twats",
    "prick", "pricks",
})


class ProfanityRegion(BaseModel):
    start: float
    end: float
    text: str
    word_index: int
    confidence: float
    category: str = "profanity"
    matched_by: str = "exact"


def _normalize(text: str) -> str:
    return _PUNCT_RE.sub("", text).lower()


def effective_word_set(
    user_added: list[str] | None = None,
    user_removed: list[str] | None = None,
) -> frozenset[str]:
    """Compute (BUILT_IN - removed) ∪ added, all normalized.

    `user_added` and `user_removed` are stored on `User.censorship_words`
    as `{"added": [...], "removed": [...]}`. This helper is the canonical
    way to derive the per-user effective list — call it from `ai_service`
    and tests, never inline the set math.
    """
    builtin = BUILT_IN
    if user_removed:
        builtin = builtin - {_normalize(w) for w in user_removed if _normalize(w)}
    if user_added:
        return builtin | {_normalize(w) for w in user_added if _normalize(w)}
    return builtin


def detect_profanity(
    transcript: WordLevelTranscript,
    word_set: frozenset[str],
) -> list[ProfanityRegion]:
    """Exact-match every word in the transcript against `word_set`.

    Returns one region per matched word, in transcript order. `word_set`
    must already be normalized (lowercase + punctuation stripped) —
    `effective_word_set()` does this for you.

    Phase 4 will add variants + phonetic matchers as separate functions
    composed with this one; do not extend this function with fuzzy logic.
    """
    if not word_set:
        return []

    regions: list[ProfanityRegion] = []
    for i, w in enumerate(transcript.words):
        norm = _normalize(w.text)
        if not norm:
            continue
        if norm in word_set:
            regions.append(ProfanityRegion(
                start=w.start,
                end=w.end,
                text=w.text,
                word_index=i,
                confidence=1.0,
                matched_by="exact",
            ))
    return regions
