"""Unit tests for censorship_service — exact matcher + effective_word_set.

Pure-function tests; no DB, no broker. Whisper-side mocked via hand-crafted
WordLevelTranscript instances.
"""
from __future__ import annotations

import pytest

from app.providers.transcription import TranscribedWord, WordLevelTranscript
from app.services.censorship_service import (
    BUILT_IN,
    detect_profanity,
    effective_word_set,
)


def _transcript(words: list[tuple[str, float, float]], language: str = "en") -> WordLevelTranscript:
    return WordLevelTranscript(
        language=language,
        duration_sec=10.0,
        words=[TranscribedWord(text=t, start=s, end=e) for t, s, e in words],
        model_version="test-v1",
        cost_usd=0.0,
    )


def test_builtin_word_set_is_lowercase():
    """Whole-word matcher relies on lowercase entries."""
    for word in BUILT_IN:
        assert word == word.lower()
        assert " " not in word


def test_effective_word_set_default_is_builtin():
    assert effective_word_set() == BUILT_IN
    assert effective_word_set(user_added=None, user_removed=None) == BUILT_IN


def test_effective_word_set_with_added_words():
    out = effective_word_set(user_added=["custom", "WordTwo"])
    assert "custom" in out
    assert "wordtwo" in out  # normalized to lowercase
    assert BUILT_IN.issubset(out)


def test_effective_word_set_with_removed_words():
    # Pick a known builtin to remove
    sample = next(iter(BUILT_IN))
    out = effective_word_set(user_removed=[sample])
    assert sample not in out
    # Other builtins remain
    others = BUILT_IN - {sample}
    assert others.issubset(out)


def test_effective_word_set_add_then_remove_does_not_remove_added():
    # If user adds a word AND lists it as removed, the union takes precedence
    # because (BUILT_IN - removed) ∪ added still contains added.
    out = effective_word_set(user_added=["mything"], user_removed=["mything"])
    assert "mything" in out


def test_detect_matches_exact_word():
    t = _transcript([
        ("hello", 0.0, 0.5),
        ("shit", 0.6, 0.9),
        ("world", 1.0, 1.5),
    ])
    regions = detect_profanity(t, BUILT_IN)
    assert len(regions) == 1
    r = regions[0]
    assert r.text == "shit"
    assert r.start == 0.6
    assert r.end == 0.9
    assert r.word_index == 1
    assert r.confidence == 1.0
    assert r.matched_by == "exact"
    assert r.category == "profanity"


def test_detect_strips_punctuation():
    t = _transcript([
        ("Shit,", 0.0, 0.4),
        ("hello!", 0.5, 0.9),
    ])
    regions = detect_profanity(t, BUILT_IN)
    assert len(regions) == 1
    assert regions[0].text == "Shit,"  # preserves the original surface form


def test_detect_is_case_insensitive():
    t = _transcript([
        ("SHIT", 0.0, 0.3),
        ("Fuck", 0.4, 0.7),
        ("dAmN", 0.8, 1.0),
    ])
    regions = detect_profanity(t, BUILT_IN)
    assert {r.text for r in regions} == {"SHIT", "Fuck", "dAmN"}


def test_detect_no_substring_match():
    """The matcher tokenizes; "ass" inside "class" must not match."""
    t = _transcript([
        ("classic", 0.0, 0.5),
        ("assassin", 0.6, 1.0),
        ("hello", 1.1, 1.5),
    ])
    regions = detect_profanity(t, BUILT_IN)
    assert regions == []


def test_detect_empty_word_set_returns_no_regions():
    t = _transcript([("shit", 0.0, 0.3)])
    assert detect_profanity(t, frozenset()) == []


def test_detect_empty_transcript_returns_no_regions():
    t = _transcript([])
    assert detect_profanity(t, BUILT_IN) == []


def test_detect_handles_user_added_words():
    word_set = effective_word_set(user_added=["banana"])
    t = _transcript([
        ("hello", 0.0, 0.4),
        ("banana", 0.5, 0.9),
        ("world", 1.0, 1.4),
    ])
    regions = detect_profanity(t, word_set)
    assert len(regions) == 1
    assert regions[0].text == "banana"


def test_detect_skips_when_user_removes_builtin():
    word_set = effective_word_set(user_removed=["shit"])
    t = _transcript([("shit", 0.0, 0.3)])
    regions = detect_profanity(t, word_set)
    assert regions == []


def test_detect_preserves_word_indices_across_skipped_words():
    """word_index must match the position in transcript.words."""
    t = _transcript([
        ("the", 0.0, 0.2),     # 0
        ("cat", 0.3, 0.5),     # 1
        ("shit", 0.6, 0.9),    # 2 ← match
        ("the", 1.0, 1.2),     # 3
        ("dog", 1.3, 1.5),     # 4
        ("damn", 1.6, 1.9),    # 5 ← match
    ])
    regions = detect_profanity(t, BUILT_IN)
    assert [r.word_index for r in regions] == [2, 5]


@pytest.mark.parametrize("punctuation", [".", ",", "!", "?", ";", ":"])
def test_detect_strips_trailing_punctuation(punctuation):
    t = _transcript([("shit" + punctuation, 0.0, 0.3)])
    regions = detect_profanity(t, BUILT_IN)
    assert len(regions) == 1
