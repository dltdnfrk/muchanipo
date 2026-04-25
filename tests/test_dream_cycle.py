from pathlib import Path

import pytest

from src.wiki.dream_cycle import DreamCycle, Episode, accumulate_all


def test_dream_cycle_promotes_after_repetition_threshold():
    cycle = DreamCycle(threshold=3)

    cycle.accumulate({"key": "agtech-sensor", "content": "soil sensor drift observed"})
    cycle.accumulate(Endpoint := Episode(key="agtech-sensor", content="farmer reported drift"))
    assert Endpoint.key == "agtech-sensor"
    assert cycle.should_promote() is False

    cycle.accumulate({"topic": "agtech-sensor", "text": "maintenance ticket repeated"})

    assert cycle.should_promote() is True
    assert cycle.promotion_candidates() == {"agtech-sensor": 3}


def test_compile_truth_deduplicates_observations():
    cycle = DreamCycle(threshold=2)
    accumulate_all(
        cycle,
        [
            {"key": "rice-yield", "content": "rice yield forecast needs rainfall context"},
            {"key": "rice-yield", "content": "rice yield forecast needs rainfall context"},
            {"key": "rice-yield", "content": "county baseline should be shown"},
        ],
    )

    compiled = cycle.compile_truth("rice-yield")

    assert "- observations: 3" in compiled
    assert "- unique_observations: 2" in compiled
    assert compiled.count("rice yield forecast needs rainfall context") == 1


def test_promote_to_compiled_truth_uses_lockdown_guard(tmp_path, monkeypatch):
    import src.wiki.dream_cycle as dream_cycle

    calls = []

    def fake_guard(path):
        calls.append(Path(path))
        return True, "allowed"

    monkeypatch.setattr(dream_cycle, "guard_write", fake_guard)
    cycle = DreamCycle(threshold=1)

    target = cycle.promote_to_compiled_truth(tmp_path, "compiled truth: 농업", "content\n")

    assert target == tmp_path / "compiled-truth-농업.md"
    assert target.read_text(encoding="utf-8") == "content\n"
    assert calls == [target]


def test_promote_to_compiled_truth_denies_blocked_paths(tmp_path, monkeypatch):
    import src.wiki.dream_cycle as dream_cycle

    monkeypatch.setattr(dream_cycle, "guard_write", lambda path: (False, "deny_write"))
    cycle = DreamCycle(threshold=1)

    with pytest.raises(PermissionError, match="deny_write"):
        cycle.promote_to_compiled_truth(tmp_path, "blocked", "content\n")
