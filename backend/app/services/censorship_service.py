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


def normalize_user_words(words: list[str] | None) -> list[str]:
    """Normalize a user-supplied list: lowercase, strip punctuation, drop
    empties + duplicates, preserve insertion order.

    Use this on input from the CRUD endpoint before persisting so the stored
    list always matches what the matcher will see.
    """
    if not words:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        n = _normalize(w)
        if not n or n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


DEFAULT_MATCHERS: dict[str, bool] = {"variants": True, "phonetic": False}


def get_matchers(user_overrides: dict | None) -> dict[str, bool]:
    """Read matcher toggles with defaults filled in.

    Per D4 default: variants on, phonetic off (FP risk).
    """
    overrides = user_overrides or {}
    raw = overrides.get("matchers") or {}
    return {
        "variants": bool(raw.get("variants", DEFAULT_MATCHERS["variants"])),
        "phonetic": bool(raw.get("phonetic", DEFAULT_MATCHERS["phonetic"])),
    }


def get_words_state(user_overrides: dict | None) -> dict:
    """Return the user's word-list state in the shape the CRUD endpoint emits.

    Defensive against legacy or malformed JSON: missing fields default sensibly.
    """
    overrides = user_overrides or {}
    return {
        "builtIn": sorted(BUILT_IN),
        "added": list(overrides.get("added") or []),
        "removed": list(overrides.get("removed") or []),
        "matchers": get_matchers(user_overrides),
    }


def merge_words_update(
    user_overrides: dict | None,
    added: list[str] | None,
    removed: list[str] | None,
    matchers: dict | None = None,
) -> dict:
    """Apply a partial CRUD update.

    `added`, `removed`, and `matchers` are full replacements when present;
    None leaves the existing field alone. Lists are normalized before storing.
    `matchers` is validated structurally (only known keys, coerced to bool).
    """
    overrides = dict(user_overrides or {})
    if added is not None:
        overrides["added"] = normalize_user_words(added)
    if removed is not None:
        # Drop anything the user "removes" that isn't actually a built-in —
        # otherwise the removed list grows with no effect.
        overrides["removed"] = [
            w for w in normalize_user_words(removed) if w in BUILT_IN
        ]
    if matchers is not None:
        existing = get_matchers(user_overrides)
        overrides["matchers"] = {
            "variants": bool(matchers.get("variants", existing["variants"])),
            "phonetic": bool(matchers.get("phonetic", existing["phonetic"])),
        }
    return overrides


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

    Variants and phonetic matchers are separate functions — call
    `detect_profanity_full` to compose all three with the user's toggles.
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


# --- Phase 4: variants + phonetic matchers -------------------------------

_SUFFIX_STRIPS = (
    "ings", "ing", "ies", "ied", "ers", "er", "est",
    "ly", "ed", "es", "s", "y",
)


def _stem(word: str) -> str:
    """Strip a common suffix once. Conservative: returns the original word if no
    suffix matches or stripping would leave fewer than 3 letters.

    Not a full Porter stemmer; just enough to catch the common forms a
    profanity list misses (fucking → fuck, shitty → shit).
    """
    for suf in _SUFFIX_STRIPS:
        if len(word) > len(suf) + 2 and word.endswith(suf):
            return word[: -len(suf)]
    return word


def _expand_variants(word: str) -> set[str]:
    """Generate a small set of likely variants for `word`. Conservative — we'd
    rather miss a match than create a false positive.
    """
    if not word:
        return set()
    out: set[str] = {word}
    # Stem
    s = _stem(word)
    if s != word:
        out.add(s)
    # Common plural/3rd-person forms
    if not word.endswith("s"):
        out.add(word + "s")
    if word.endswith("y") and len(word) >= 3:
        out.add(word[:-1] + "ies")
    return out


def expand_variants_set(words: frozenset[str] | set[str]) -> frozenset[str]:
    """Expand a normalized word set with stems + obvious inflections.

    The Phase 4 variants matcher just runs exact-match against the expanded
    set, so this is cheap and side-effect-free.
    """
    out: set[str] = set()
    for w in words:
        out.update(_expand_variants(w))
    return frozenset(out)


def detect_variants(
    transcript: WordLevelTranscript,
    expanded_word_set: frozenset[str],
    *,
    skip_word_indices: set[int] | None = None,
) -> list[ProfanityRegion]:
    """Same shape as `detect_profanity` but matches against the variants-expanded
    set. Skips any word index already matched by an earlier matcher so the
    `matched_by` tag reflects the *first* matcher that caught it.
    """
    if not expanded_word_set:
        return []
    skip = skip_word_indices or set()
    regions: list[ProfanityRegion] = []
    for i, w in enumerate(transcript.words):
        if i in skip:
            continue
        norm = _normalize(w.text)
        if not norm:
            continue
        if norm in expanded_word_set:
            regions.append(ProfanityRegion(
                start=w.start, end=w.end, text=w.text,
                word_index=i, confidence=0.85, matched_by="variants",
            ))
    return regions


def _metaphone_codes(words: set[str] | frozenset[str]) -> set[str]:
    """Build a set of Metaphone codes for a normalized word set. Uses the
    Double Metaphone primary code; secondary codes are dropped (the more
    conservative match cuts false positives further).
    """
    from metaphone import doublemetaphone
    out: set[str] = set()
    for w in words:
        primary, _secondary = doublemetaphone(w)
        if primary:
            out.add(primary)
    return out


def detect_phonetic(
    transcript: WordLevelTranscript,
    target_codes: set[str],
    *,
    skip_word_indices: set[int] | None = None,
) -> list[ProfanityRegion]:
    """Match transcript words by phonetic similarity (Double Metaphone primary).

    Per D2: callers should restrict `target_codes` to user-added words only —
    phonetic matching on the BUILT_IN list has unacceptable false-positive
    risk ("duck" → DK matches "fuck").
    """
    if not target_codes:
        return []
    from metaphone import doublemetaphone
    skip = skip_word_indices or set()
    regions: list[ProfanityRegion] = []
    for i, w in enumerate(transcript.words):
        if i in skip:
            continue
        norm = _normalize(w.text)
        if not norm:
            continue
        primary, _secondary = doublemetaphone(norm)
        if primary and primary in target_codes:
            regions.append(ProfanityRegion(
                start=w.start, end=w.end, text=w.text,
                word_index=i, confidence=0.5, matched_by="phonetic",
            ))
    return regions


def detect_profanity_full(
    transcript: WordLevelTranscript,
    *,
    user_added: list[str] | None = None,
    user_removed: list[str] | None = None,
    variants_enabled: bool = True,
    phonetic_enabled: bool = False,
) -> list[ProfanityRegion]:
    """Run the configured matcher pipeline and return de-duped regions.

    Composition rules (per design doc §6):
    - Exact always runs.
    - Variants (if enabled) runs against (BUILT_IN ∪ added) expanded with
      stems/plurals, skipping indices the exact matcher already caught.
    - Phonetic (if enabled) runs ONLY against user-added words (per D2),
      skipping indices the earlier matchers already caught.
    - One region per word index, tagged with the matcher that first caught it.
    """
    added = [_normalize(w) for w in (user_added or []) if _normalize(w)]
    removed = [_normalize(w) for w in (user_removed or []) if _normalize(w)]
    word_set = effective_word_set(user_added=added, user_removed=removed)

    regions = detect_profanity(transcript, word_set)
    caught: set[int] = {r.word_index for r in regions}

    if variants_enabled:
        # Only NEW variants (those not already in word_set), AND with the
        # user's removed set subtracted — stemming an inflected built-in
        # like 'shits' → 'shit' could otherwise re-introduce a word the user
        # explicitly excluded.
        expanded = expand_variants_set(word_set) - word_set
        if removed:
            expanded = expanded - set(removed)
        regions.extend(detect_variants(transcript, expanded, skip_word_indices=caught))
        caught.update(r.word_index for r in regions)

    if phonetic_enabled and added:
        # D2: phonetic ONLY against user-added words, not BUILT_IN.
        added_set = frozenset(added)
        codes = _metaphone_codes(added_set)
        regions.extend(detect_phonetic(transcript, codes, skip_word_indices=caught))

    # Re-sort by word index since matchers append in their own order.
    regions.sort(key=lambda r: r.word_index)
    return regions
