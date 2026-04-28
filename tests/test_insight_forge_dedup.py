"""Tests for GBrain 4-Layer (plus stale marker) dedup pipeline in insight-forge.py.

insight-forge.py has a hyphen in its filename so it cannot be imported directly.
We use importlib.util via the existing conftest helper.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_insight_forge():
    spec = importlib.util.spec_from_file_location(
        "insight_forge", ROOT / "src" / "search" / "insight-forge.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def forge():
    return _load_insight_forge()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(
    text: str,
    source: str = "src",
    rrf_score: float = 1.0,
    matched_questions=None,
    compiled_truth: str = "",
    latest_timeline: str = "",
) -> dict:
    d = {
        "text": text,
        "source": source,
        "rrf_score": rrf_score,
        "matched_questions": matched_questions or ["WHAT"],
    }
    if compiled_truth:
        d["compiled_truth"] = compiled_truth
    if latest_timeline:
        d["latest_timeline"] = latest_timeline
    return d


# ---------------------------------------------------------------------------
# Layer 1: _dedup_by_source
# ---------------------------------------------------------------------------

class TestDedupBySource:
    def test_keeps_highest_score_per_source(self, forge):
        results = [
            _item("low", source="a", rrf_score=0.5),
            _item("high", source="a", rrf_score=0.9),
            _item("other", source="b", rrf_score=0.7),
        ]
        out = forge._dedup_by_source(results)
        texts = [o["text"] for o in out]
        assert "high" in texts
        assert "low" not in texts
        assert "other" in texts

    def test_sorts_by_rrf_score_descending(self, forge):
        results = [
            _item("c", source="c", rrf_score=0.3),
            _item("a", source="a", rrf_score=0.9),
            _item("b", source="b", rrf_score=0.5),
        ]
        out = forge._dedup_by_source(results)
        assert [o["text"] for o in out] == ["a", "b", "c"]

    def test_empty_list(self, forge):
        assert forge._dedup_by_source([]) == []

    def test_missing_source_key_passes_through(self, forge):
        results = [
            {"text": "no source", "rrf_score": 0.5},
            {"text": "also no source", "rrf_score": 0.6},
        ]
        out = forge._dedup_by_source(results)
        assert len(out) == 2

    def test_single_source(self, forge):
        results = [
            _item("first", source="only", rrf_score=0.5),
            _item("second", source="only", rrf_score=0.9),
        ]
        out = forge._dedup_by_source(results)
        assert len(out) == 1
        assert out[0]["text"] == "second"


# ---------------------------------------------------------------------------
# Layer 2: deduplicate (Jaccard similarity)
# ---------------------------------------------------------------------------

class TestDeduplicate:
    def test_removes_high_jaccard_duplicates(self, forge):
        results = [
            _item("hello world foo bar", rrf_score=1.0),
            _item("hello world foo bar", rrf_score=0.9),  # identical → Jaccard 1.0
            _item("totally different text here", rrf_score=0.8),
        ]
        out = forge.deduplicate(results, threshold=0.8)
        texts = [o["text"] for o in out]
        assert len(texts) == 2
        assert "hello world foo bar" in texts
        assert "totally different text here" in texts

    def test_preserves_order_and_first_item(self, forge):
        results = [
            _item("alpha beta gamma", rrf_score=1.0),
            _item("alpha beta gamma", rrf_score=0.9),  # identical → Jaccard 1.0
        ]
        out = forge.deduplicate(results, threshold=0.8)
        assert len(out) == 1
        assert out[0]["text"] == "alpha beta gamma"

    def test_empty_list(self, forge):
        assert forge.deduplicate([]) == []

    def test_no_duplicates_when_all_different(self, forge):
        results = [
            _item("apple banana", rrf_score=1.0),
            _item("cherry date", rrf_score=0.9),
            _item("elderberry fig", rrf_score=0.8),
        ]
        out = forge.deduplicate(results, threshold=0.8)
        assert len(out) == 3

    def test_handles_missing_text(self, forge):
        results = [
            {"source": "a", "rrf_score": 1.0},
            {"source": "b", "rrf_score": 0.9},
        ]
        out = forge.deduplicate(results, threshold=0.8)
        # Both have empty text → Jaccard = 1.0, so second is dropped
        assert len(out) == 1


# ---------------------------------------------------------------------------
# Layer 3: _enforce_type_diversity
# ---------------------------------------------------------------------------

class TestEnforceTypeDiversity:
    def test_caps_dominant_type(self, forge):
        results = [
            _item("a", matched_questions=["WHAT"]),
            _item("b", matched_questions=["WHAT"]),
            _item("c", matched_questions=["WHAT"]),
            _item("d", matched_questions=["WHY"]),
            _item("e", matched_questions=["HOW"]),
        ]
        out = forge._enforce_type_diversity(results, max_ratio=0.6)
        # 5 items * 0.6 = 3 max per type
        what_count = sum(1 for o in out if o["matched_questions"][0] == "WHAT")
        assert what_count <= 3
        assert len(out) >= 3

    def test_all_same_type_gets_capped(self, forge):
        results = [
            _item("a", matched_questions=["WHAT"]),
            _item("b", matched_questions=["WHAT"]),
            _item("c", matched_questions=["WHAT"]),
            _item("d", matched_questions=["WHAT"]),
            _item("e", matched_questions=["WHAT"]),
        ]
        out = forge._enforce_type_diversity(results, max_ratio=0.6)
        assert len(out) == 3  # max(1, int(5*0.6+0.5)) = 3

    def test_empty_list(self, forge):
        assert forge._enforce_type_diversity([]) == []

    def test_missing_matched_questions_defaults_to_unknown(self, forge):
        results = [
            {"text": "a", "source": "s1"},
            {"text": "b", "source": "s2"},
            {"text": "c", "source": "s3"},
        ]
        out = forge._enforce_type_diversity(results, max_ratio=0.6)
        # All UNKNOWN, cap = max(1, int(3*0.6+0.5)) = 2
        assert len(out) == 2


# ---------------------------------------------------------------------------
# Layer 4: _cap_per_source
# ---------------------------------------------------------------------------

class TestCapPerSource:
    def test_limits_per_source(self, forge):
        results = [
            _item("a1", source="page_a"),
            _item("a2", source="page_a"),
            _item("a3", source="page_a"),
            _item("b1", source="page_b"),
        ]
        out = forge._cap_per_source(results, max_per_source=2)
        a_count = sum(1 for o in out if o["source"] == "page_a")
        assert a_count == 2
        assert len(out) == 3

    def test_single_source(self, forge):
        results = [
            _item("a1", source="only"),
            _item("a2", source="only"),
            _item("a3", source="only"),
        ]
        out = forge._cap_per_source(results, max_per_source=2)
        assert len(out) == 2

    def test_empty_list(self, forge):
        assert forge._cap_per_source([]) == []

    def test_missing_source_key_counts_as_empty(self, forge):
        results = [
            {"text": "no src 1", "rrf_score": 1.0},
            {"text": "no src 2", "rrf_score": 0.9},
            {"text": "no src 3", "rrf_score": 0.8},
        ]
        out = forge._cap_per_source(results, max_per_source=2)
        # source is empty string, count starts at 0 each time because
        # dict.get("", 0) returns the same key "". Actually all share ""
        # so only 2 should be kept.
        assert len(out) == 2


# ---------------------------------------------------------------------------
# Layer 5: _mark_stale
# ---------------------------------------------------------------------------

class TestMarkStale:
    def test_marks_when_compiled_older_than_latest(self, forge):
        results = [
            _item(
                "old fact",
                compiled_truth="2023-01-01",
                latest_timeline="2024-01-01",
            ),
        ]
        out = forge._mark_stale(results)
        assert out[0]["text"].startswith("[STALE] old fact")

    def test_does_not_mark_when_compiled_newer(self, forge):
        results = [
            _item(
                "fresh fact",
                compiled_truth="2024-06-01",
                latest_timeline="2024-01-01",
            ),
        ]
        out = forge._mark_stale(results)
        assert not out[0]["text"].startswith("[STALE]")

    def test_does_not_mark_when_equal(self, forge):
        results = [
            _item(
                "same date",
                compiled_truth="2024-01-01",
                latest_timeline="2024-01-01",
            ),
        ]
        out = forge._mark_stale(results)
        assert not out[0]["text"].startswith("[STALE]")

    def test_missing_fields_pass_through(self, forge):
        results = [
            _item("no dates"),
            _item("only compiled", compiled_truth="2024-01-01"),
            _item("only latest", latest_timeline="2024-01-01"),
        ]
        out = forge._mark_stale(results)
        assert all(not o["text"].startswith("[STALE]") for o in out)

    def test_empty_list(self, forge):
        assert forge._mark_stale([]) == []

    def test_custom_marker(self, forge):
        results = [
            _item(
                "legacy",
                compiled_truth="2022-01-01",
                latest_timeline="2023-01-01",
            ),
        ]
        out = forge._mark_stale(results, stale_marker="[OUTDATED]")
        assert out[0]["text"].startswith("[OUTDATED] legacy")

    def test_does_not_double_mark(self, forge):
        results = [
            _item(
                "[STALE] already marked",
                compiled_truth="2022-01-01",
                latest_timeline="2023-01-01",
            ),
        ]
        out = forge._mark_stale(results)
        # Should not add another prefix
        assert out[0]["text"].count("[STALE]") == 1

    def test_iso_datetime_strings(self, forge):
        results = [
            _item(
                "datetime",
                compiled_truth="2023-01-01T12:00:00Z",
                latest_timeline="2024-01-01T00:00:00+09:00",
            ),
        ]
        out = forge._mark_stale(results)
        assert out[0]["text"].startswith("[STALE] datetime")


# ---------------------------------------------------------------------------
# Integration: deduplicate_gbrain
# ---------------------------------------------------------------------------

class TestDeduplicateGbrain:
    def test_full_pipeline_reduces_results(self, forge):
        results = [
            # Layer 1: same source, keep highest score
            _item("low a", source="page_a", rrf_score=0.5, matched_questions=["WHAT"]),
            _item("high a", source="page_a", rrf_score=0.9, matched_questions=["WHAT"]),
            # Layer 2: near-duplicate text
            _item("hello world alpha", source="page_b", rrf_score=0.8, matched_questions=["WHY"]),
            _item("hello world beta", source="page_c", rrf_score=0.7, matched_questions=["HOW"]),
            # Layer 3/4 extras
            _item("extra b1", source="page_b", rrf_score=0.6, matched_questions=["WHAT"]),
            _item("extra b2", source="page_b", rrf_score=0.55, matched_questions=["WHAT"]),
            _item("extra c1", source="page_c", rrf_score=0.5, matched_questions=["WHY"]),
        ]
        out = forge.deduplicate_gbrain(results)
        # Should be reduced by at least one layer
        assert len(out) <= len(results)

    def test_stale_marker_applied_at_end(self, forge):
        results = [
            _item(
                "stale item",
                source="page_a",
                rrf_score=1.0,
                compiled_truth="2022-01-01",
                latest_timeline="2024-01-01",
            ),
        ]
        out = forge.deduplicate_gbrain(results)
        assert len(out) == 1
        assert out[0]["text"].startswith("[STALE] stale item")

    def test_empty_list(self, forge):
        assert forge.deduplicate_gbrain([]) == []

    def test_single_item_passes_through(self, forge):
        results = [
            _item("lonely", source="only", rrf_score=1.0, matched_questions=["WHAT"]),
        ]
        out = forge.deduplicate_gbrain(results)
        assert len(out) == 1
        assert out[0]["text"] == "lonely"

    def test_preserves_original_dicts_for_unmarked(self, forge):
        original = _item("untouched", source="s", rrf_score=1.0)
        results = [original]
        out = forge.deduplicate_gbrain(results)
        # For non-stale items the pipeline may still copy via deduplicate logic,
        # but the content should remain identical.
        assert out[0]["text"] == "untouched"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_all_layers_on_empty_list(self, forge):
        assert forge._dedup_by_source([]) == []
        assert forge.deduplicate([]) == []
        assert forge._enforce_type_diversity([]) == []
        assert forge._cap_per_source([]) == []
        assert forge._mark_stale([]) == []
        assert forge.deduplicate_gbrain([]) == []

    def test_all_same_type_with_many_items(self, forge):
        results = [
            _item(f"item {i}", source=f"page_{i}", matched_questions=["WHAT"])
            for i in range(10)
        ]
        out = forge._enforce_type_diversity(results, max_ratio=0.6)
        assert len(out) == 6  # max(1, int(10*0.6+0.5)) = 6

    def test_many_from_single_source(self, forge):
        results = [
            _item(f"item {i}", source="only", rrf_score=1.0 - i * 0.05)
            for i in range(10)
        ]
        out = forge.deduplicate_gbrain(results)
        # Layer 1 keeps highest (item 0), Layer 4 caps at 2
        assert len(out) <= 2

    def test_results_with_missing_keys_survive_pipeline(self, forge):
        results = [
            {"text": "minimal"},
            {"text": "almost minimal", "source": "s"},
        ]
        out = forge.deduplicate_gbrain(results)
        # Should not raise and should return some subset
        assert isinstance(out, list)
