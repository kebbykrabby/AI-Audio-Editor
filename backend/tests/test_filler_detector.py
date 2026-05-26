"""Unit tests for the heuristic filler-word classifier.

The classifier is a pure function over a `WordLevelTranscript`. Tests construct
synthetic transcripts to lock in the MVP categorization rules:
- pure fillers (um/uh/er) at high confidence
- discourse markers (like/so) at low confidence
- two-word phrases (you know, I mean) combined into one region
- stutters detected by immediate repetition of short words
"""
from __future__ import annotations

from app.processors.filler_detector import FillerRegion, detect_fillers
from app.providers.transcription import TranscribedWord, WordLevelTranscript


def _transcript(*word_tuples: tuple[str, float, float]) -> WordLevelTranscript:
    return WordLevelTranscript(
        language="en",
        duration_sec=max((e for _, _, e in word_tuples), default=0.0),
        words=[TranscribedWord(text=t, start=s, end=e) for t, s, e in word_tuples],
        model_version="test",
    )


def test_um_detected_high_confidence():
    t = _transcript(("So", 0.0, 0.3), ("um", 0.3, 0.5), ("hello", 0.6, 1.0))
    regions = detect_fillers(t)
    ums = [r for r in regions if r.category == "um"]
    assert len(ums) == 1
    assert ums[0].confidence >= 0.9
    assert ums[0].text == "um"


def test_uh_variants():
    t = _transcript(("uh", 0.0, 0.2), ("uhh", 0.3, 0.5), ("uhhh", 0.6, 0.9))
    regions = detect_fillers(t)
    uhs = [r for r in regions if r.category == "uh"]
    assert len(uhs) == 3
    assert all(r.confidence >= 0.9 for r in uhs)


def test_you_know_combined_into_one_region():
    t = _transcript(("you", 0.0, 0.2), ("know", 0.2, 0.5), ("right", 0.6, 1.0))
    regions = detect_fillers(t)
    yks = [r for r in regions if r.category == "you_know"]
    assert len(yks) == 1
    assert yks[0].start == 0.0
    assert yks[0].end == 0.5
    assert yks[0].text == "you know"


def test_i_mean_combined_into_one_region():
    t = _transcript(("I", 0.0, 0.2), ("mean", 0.2, 0.5), ("yes", 0.6, 1.0))
    regions = detect_fillers(t)
    ims = [r for r in regions if r.category == "i_mean"]
    assert len(ims) == 1
    assert ims[0].end == 0.5


def test_stutter_detected_on_short_word_repeat():
    t = _transcript(("I", 0.0, 0.2), ("I", 0.25, 0.4), ("went", 0.5, 0.9))
    regions = detect_fillers(t)
    stutters = [r for r in regions if r.category == "stutter"]
    assert len(stutters) == 1
    assert stutters[0].start == 0.25


def test_long_word_repeat_is_not_stutter():
    """Long-word repeat ("really really") is often rhetorical emphasis, not a
    stutter. The classifier leaves these alone for MVP."""
    t = _transcript(("really", 0.0, 0.5), ("really", 0.6, 1.0), ("good", 1.1, 1.5))
    regions = detect_fillers(t)
    stutters = [r for r in regions if r.category == "stutter"]
    assert stutters == []


def test_like_and_so_low_confidence():
    t = _transcript(("like", 0.0, 0.3), ("so", 0.4, 0.7))
    regions = detect_fillers(t)
    by_cat = {r.category: r for r in regions}
    assert by_cat["like"].confidence < 0.7
    assert by_cat["so"].confidence < 0.7


def test_default_threshold_includes_all():
    """confidence_threshold=0 returns every candidate so the UI can re-filter."""
    t = _transcript(("um", 0.0, 0.2), ("like", 0.3, 0.5))
    assert len(detect_fillers(t, confidence_threshold=0.0)) == 2


def test_threshold_filters_low_confidence():
    t = _transcript(("um", 0.0, 0.2), ("like", 0.3, 0.5))
    regions = detect_fillers(t, confidence_threshold=0.7)
    cats = {r.category for r in regions}
    assert "um" in cats
    assert "like" not in cats


def test_categories_filter():
    t = _transcript(("um", 0.0, 0.2), ("uh", 0.3, 0.5), ("like", 0.6, 0.9))
    regions = detect_fillers(t, categories=frozenset({"um"}))
    cats = [r.category for r in regions]
    assert cats == ["um"]


def test_punctuation_does_not_prevent_match():
    t = _transcript(("Um,", 0.0, 0.2), ("right.", 0.3, 0.6))
    ums = [r for r in detect_fillers(t) if r.category == "um"]
    assert len(ums) == 1


def test_empty_transcript_returns_empty():
    t = _transcript()
    assert detect_fillers(t) == []


def test_word_index_set_correctly():
    t = _transcript(("hello", 0.0, 0.3), ("um", 0.4, 0.6), ("world", 0.7, 1.0))
    regions = detect_fillers(t)
    um = next(r for r in regions if r.category == "um")
    assert um.word_index == 1


def test_region_is_filler_region_model():
    t = _transcript(("um", 0.0, 0.2))
    regions = detect_fillers(t)
    assert isinstance(regions[0], FillerRegion)
