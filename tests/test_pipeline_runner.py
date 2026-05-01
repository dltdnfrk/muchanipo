import json
from pathlib import Path

import pytest

from src.pipeline.runner import run_pipeline, round_result_to_digest
from src.research.depth import DEPTH_PROFILES


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
    assert result["depth"] == "deep"
    assert result["executed_council_round_count"] == 10
    assert result["council_persona_pool_size"] == 80
    assert result["active_council_persona_count"] == 10
    assert result["council_turn_transcript"]
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


def test_run_pipeline_shallow_depth_reduces_internal_autoresearch_budget():
    result = run_pipeline("딸기 진단키트 시장성", offline=True, depth="shallow")
    artifacts = result["pipeline_result"].state.artifacts

    assert result["depth"] == "shallow"
    assert len(result["rounds"]) == 10
    assert result["executed_council_round_count"] == 6
    assert artifacts["research_depth"] == "shallow"
    assert artifacts["research_query_limit"] == "4"
    assert artifacts["council_round_budget"] == "6"
    assert artifacts["council_persona_pool_size"] == "24"
    assert artifacts["active_council_persona_count"] == "6"
    assert artifacts["target_runtime_seconds"] == "120"
    assert artifacts["extended_test_time_compute"] == "disabled"
    assert artifacts["persona_pool_size"] == "24"
    assert artifacts["active_persona_count"] == "6"
    assert result["council_persona_pool_size"] == 24
    assert result["active_council_persona_count"] == 6


def test_run_pipeline_validates_mirofish_entity_personas_before_council():
    result = run_pipeline("MiroFish validation smoke", offline=True, depth="shallow")
    pipeline_result = result["pipeline_result"]
    artifacts = pipeline_result.state.artifacts

    mirofish_personas = [
        persona
        for persona in pipeline_result.council.personas
        if persona.persona_id.startswith("mirofish-entity-")
    ]

    assert mirofish_personas
    assert artifacts["mirofish_entity_persona_count"] == artifacts[
        "mirofish_validated_entity_persona_count"
    ]
    for persona in mirofish_personas:
        assert persona.manifest["mirofish_source"] == "generate_persona_from_entity"
        assert "value_axes" in persona.manifest
        assert "mirofish_ontology_entity_profile" in persona.revision_notes
        assert "validated_against_ontology" in persona.revision_notes
        assert "lockdown_checked" in persona.revision_notes
        assert "deep_validated" in persona.revision_notes


def test_run_pipeline_max_depth_records_extended_compute_without_new_dependency(monkeypatch):
    import src.pipeline.runner as runner_mod

    captured: list[tuple[str, str, str, str]] = []

    class _StopAfterInitPipeline:
        def __init__(self, *, depth, **kwargs):
            self.depth = depth

        def run(self, topic):
            from src.pipeline.state import PipelineState

            state = PipelineState(run_id="run-depth-max")
            state.record_artifact("research_depth", self.depth)
            state.record_artifact("research_query_limit", "12")
            state.record_artifact("council_round_budget", "10")
            state.record_artifact("council_persona_pool_size", "160")
            state.record_artifact("active_council_persona_count", "16")
            state.record_artifact("extended_test_time_compute", "enabled")
            captured.append((
                state.artifacts["research_depth"],
                state.artifacts["research_query_limit"],
                state.artifacts["council_round_budget"],
                state.artifacts["extended_test_time_compute"],
            ))
            raise RuntimeError("stop after depth metadata")

    monkeypatch.setattr(runner_mod, "IdeaToCouncilPipeline", _StopAfterInitPipeline)
    monkeypatch.setattr(runner_mod, "default_gateway", lambda **kwargs: object())
    monkeypatch.setattr(runner_mod, "build_runner", lambda **kwargs: object())

    with pytest.raises(RuntimeError, match="stop after depth metadata"):
        runner_mod.run_pipeline("max topic", offline=True, depth="max")

    assert captured == [("max", "12", "10", "enabled")]


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


def test_run_pipeline_offline_disables_live_academic_targeting(monkeypatch):
    import src.pipeline.runner as runner_mod
    import src.research.academic.openalex as openalex_mod

    class _StopAfterPolicyPipeline:
        def __init__(self, **kwargs):
            pass

        def run(self, topic):
            assert openalex_mod._skip_live_targeting() is True
            raise RuntimeError("stop after policy")

    def fail_http_client(*args, **kwargs):
        raise AssertionError("offline pipeline must not instantiate OpenAlex targeting HTTP client")

    monkeypatch.delenv("MUCHANIPO_ACADEMIC_TARGETING", raising=False)
    monkeypatch.setattr(runner_mod, "IdeaToCouncilPipeline", _StopAfterPolicyPipeline)
    monkeypatch.setattr(runner_mod, "default_gateway", lambda **kwargs: object())
    monkeypatch.setattr(runner_mod, "build_runner", lambda **kwargs: object())
    monkeypatch.setattr(openalex_mod.httpx, "Client", fail_http_client)

    with pytest.raises(RuntimeError, match="stop after policy"):
        runner_mod.run_pipeline("offline topic", offline=True)

    assert "MUCHANIPO_ACADEMIC_TARGETING" not in runner_mod.os.environ


def test_run_pipeline_offline_overrides_stale_live_academic_targeting_env(monkeypatch):
    import src.pipeline.runner as runner_mod
    import src.research.academic.openalex as openalex_mod

    class _StopAfterPolicyPipeline:
        def __init__(self, **kwargs):
            pass

        def run(self, topic):
            assert openalex_mod._skip_live_targeting() is True
            raise RuntimeError("stop after policy")

    monkeypatch.setenv("MUCHANIPO_ACADEMIC_TARGETING", "1")
    monkeypatch.setattr(runner_mod, "IdeaToCouncilPipeline", _StopAfterPolicyPipeline)
    monkeypatch.setattr(runner_mod, "default_gateway", lambda **kwargs: object())
    monkeypatch.setattr(runner_mod, "build_runner", lambda **kwargs: object())

    with pytest.raises(RuntimeError, match="stop after policy"):
        runner_mod.run_pipeline("offline topic", offline=True)

    assert runner_mod.os.environ["MUCHANIPO_ACADEMIC_TARGETING"] == "1"


@pytest.mark.parametrize("depth_name", list(DEPTH_PROFILES))
def test_run_pipeline_enforces_budget_for_each_depth(depth_name):
    result = run_pipeline("param depth test", offline=True, depth=depth_name)
    artifacts = result["pipeline_result"].state.artifacts
    profile = DEPTH_PROFILES[depth_name]

    assert result["depth"] == depth_name
    assert artifacts["research_depth"] == depth_name
    assert artifacts["research_query_limit"] == str(profile.query_limit)
    assert artifacts["council_round_budget"] == str(profile.council_round_budget)
    assert artifacts["council_persona_pool_size"] == str(profile.persona_pool_size)
    assert artifacts["active_council_persona_count"] == str(profile.active_persona_count)
    assert result["council_persona_pool_size"] == profile.persona_pool_size
    assert result["active_council_persona_count"] == profile.active_persona_count
    assert artifacts["target_runtime_seconds"] == str(profile.target_runtime_seconds)
    assert artifacts["extended_test_time_compute"] == (
        "enabled" if profile.extended_test_time_compute else "disabled"
    )
    assert artifacts["autoresearch_hitl_state_gate"] == "enforced"
    assert "total_tool_use_tokens" in artifacts["autoresearch_usage_ledger_fields"]
    assert "total_thought_tokens" in artifacts["autoresearch_usage_ledger_fields"]
    phase_trace = json.loads(artifacts["autoresearch_phase_trace"])
    assert phase_trace
    assert artifacts["autoresearch_client_timeout_seconds"] == str(profile.target_runtime_seconds)
    if profile.extended_test_time_compute:
        assert artifacts["autoresearch_execution_mode"] == "background_async_max"
        assert artifacts["autoresearch_async_background"] == "enabled"
        observed_usage = json.loads(artifacts["deep_research_max_observed_usage"])
        assert observed_usage["total_tokens"] == 699_116
        assert observed_usage["total_tool_use_tokens"] == 618_481
        assert artifacts["deep_research_max_observed_total_tokens"] == "699116"
    else:
        assert artifacts["autoresearch_execution_mode"] == "inline_local"
        assert artifacts["autoresearch_async_background"] == "disabled"
