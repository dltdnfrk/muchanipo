from pathlib import Path

import pytest

from src.pipeline.runner import run_pipeline, round_result_to_digest


def test_round_result_to_digest_extracts_claims_and_confidence():
    digest = round_result_to_digest(
        {
            "convergence": {"consensus_score": 0.82},
            "results": [
                {
                    "analysis": "Primary market signal is strong.",
                    "key_points": ["Customers need fast diagnosis.", "Distribution is the constraint."],
                    "evidence": [{"id": "E1"}, "E2"],
                    "confidence": 0.7,
                }
            ],
        },
        "L1_market_sizing",
        "시장 규모",
    )

    assert digest.layer_id == "L1_market_sizing"
    assert digest.key_claim == "Primary market signal is strong."
    assert digest.body_claims[:2] == ["Customers need fast diagnosis.", "Distribution is the constraint."]
    assert digest.evidence_ref_ids == ["E1", "E2"]
    assert digest.confidence == 0.82


def test_run_pipeline_returns_ten_rounds_six_chapter_report_and_progress():
    events = []

    result = run_pipeline("딸기 진단키트 시장성", progress_callback=events.append, offline=True)

    assert len(result["rounds"]) == 10
    assert result["brief"].is_ready
    assert Path(result["vault_path"]).exists()
    assert Path(result["report_path"]).exists()
    for n in range(1, 7):
        assert f"## Chapter {n}" in result["report_md"]

    started = [event["stage"] for event in events if event["event"] == "stage_started"]
    assert started == [
        "intake",
        "interview",
        "targeting",
        "research",
        "evidence",
        "council",
        "report",
        "vault",
        "agents",
        "finalize",
    ]
    completed = [event["stage"] for event in events if event["event"] == "stage_completed"]
    assert completed == started
    assert [
        (event["event"], event["stage"])
        for event in events[:4]
    ] == [
        ("stage_started", "intake"),
        ("stage_completed", "intake"),
        ("stage_started", "interview"),
        ("stage_completed", "interview"),
    ]
    started_targeting = next(
        event for event in events
        if event["event"] == "stage_started" and event["stage"] == "targeting"
    )
    assert "reference_step" not in started_targeting


def test_run_pipeline_uses_human_gate_only_when_live_requested(monkeypatch):
    import src.pipeline.runner as runner_mod

    captured_modes: list[str] = []

    class _StopAfterInitPipeline:
        def __init__(self, *, hitl_adapter, **kwargs):
            captured_modes.append(hitl_adapter.mode)

        def run(self, topic):
            raise RuntimeError("stop after init")

    monkeypatch.setattr(runner_mod, "IdeaToCouncilPipeline", _StopAfterInitPipeline)
    monkeypatch.setattr(runner_mod, "default_gateway", lambda **kwargs: object())
    monkeypatch.setattr(runner_mod, "build_runner", lambda **kwargs: object())

    monkeypatch.setenv("MUCHANIPO_ONLINE", "1")
    with pytest.raises(RuntimeError, match="stop after init"):
        runner_mod.run_pipeline("live topic", offline=False)

    monkeypatch.delenv("MUCHANIPO_ONLINE")
    with pytest.raises(RuntimeError, match="stop after init"):
        runner_mod.run_pipeline("configured but non-live topic", offline=False)

    assert captured_modes == ["markdown", "auto_approve"]


def test_run_pipeline_selects_plannotator_when_configured(monkeypatch):
    import src.pipeline.runner as runner_mod

    captured_modes: list[str] = []

    class _StopAfterInitPipeline:
        def __init__(self, *, hitl_adapter, **kwargs):
            captured_modes.append(hitl_adapter.mode)

        def run(self, topic):
            raise RuntimeError("stop after init")

    monkeypatch.setattr(runner_mod, "IdeaToCouncilPipeline", _StopAfterInitPipeline)
    monkeypatch.setattr(runner_mod, "default_gateway", lambda **kwargs: object())
    monkeypatch.setattr(runner_mod, "build_runner", lambda **kwargs: object())
    monkeypatch.setenv("PLANNOTATOR_OFFLINE", "1")

    with pytest.raises(RuntimeError, match="stop after init"):
        runner_mod.run_pipeline("plannotator topic", offline=True)

    assert captured_modes == ["plannotator"]


def test_run_pipeline_explicit_require_live_uses_live_hitl_gate(monkeypatch):
    import src.pipeline.runner as runner_mod

    captured: list[tuple[str, bool]] = []

    class _StopAfterInitPipeline:
        def __init__(self, *, hitl_adapter, require_live, **kwargs):
            captured.append((hitl_adapter.mode, require_live))

        def run(self, topic):
            raise RuntimeError("stop after init")

    monkeypatch.setattr(runner_mod, "IdeaToCouncilPipeline", _StopAfterInitPipeline)
    monkeypatch.setattr(runner_mod, "default_gateway", lambda **kwargs: object())
    monkeypatch.setattr(runner_mod, "build_runner", lambda **kwargs: object())
    monkeypatch.delenv("MUCHANIPO_ONLINE", raising=False)

    with pytest.raises(RuntimeError, match="stop after init"):
        runner_mod.run_pipeline("explicit live", offline=False, require_live=True)

    assert captured == [("markdown", True)]
