import json
import time
from pathlib import Path

import pytest

from src.evidence.artifact import EvidenceRef, Finding
from src.execution.models import ModelResult
from src.pipeline.runner import run_pipeline, round_result_to_digest
from src.research.depth import DEPTH_PROFILES
from src.runtime.live_mode import LiveModeViolation


def test_run_pipeline_mimo_opencode_policy_fails_before_progress_without_api_key(monkeypatch):
    for name in ("XIAOMI_MIMO_API_KEY", "MIMO_API_KEY", "OPENCODE_GO_API_KEY", "OPENCODE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MUCHANIPO_VERIFICATION_ROUTING", "mimo_opencode_go_only")
    events = []

    with pytest.raises(LiveModeViolation, match="mimo:missing_credential"):
        run_pipeline("policy gate", offline=False, require_live=True, progress_callback=events.append)

    assert events == []


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


def test_council_progress_gateway_times_out_persona_generation_call(monkeypatch):
    from src.pipeline.idea_to_council import _CouncilProviderProgressGateway

    class SlowGateway:
        stage_routes = {"council": "opencode"}
        fallback_chain = {"council": ["opencode"]}

        def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
            time.sleep(0.2)
            return ModelResult(text="late", provider="opencode")

    monkeypatch.setenv("MUCHANIPO_COUNCIL_PROVIDER_TIMEOUT_SEC", "0.01")
    events: list[dict] = []
    gateway = _CouncilProviderProgressGateway(SlowGateway(), events.append)

    with pytest.raises(TimeoutError, match="council provider call timed out"):
        gateway.call(
            "council",
            "persona prompt",
            council_stage="persona_propose",
            layer_id="persona_generation",
        )

    event_names = [event["event"] for event in events]
    assert "council_provider_call_start" in event_names
    assert "council_provider_call_timeout" in event_names
    timeout_event = next(event for event in events if event["event"] == "council_provider_call_timeout")
    assert timeout_event["provider_route"] == "opencode"
    assert timeout_event["council_stage"] == "persona_propose"
    assert timeout_event["layer"] == "persona_generation"
    assert timeout_event["blocks_product_pass"] is True


def test_council_progress_gateway_allows_fallback_provider_after_primary_timeout(monkeypatch):
    from src.execution.gateway_v2 import GatewayV2
    from src.pipeline.idea_to_council import _CouncilProviderProgressGateway

    calls: list[str] = []

    class TimingOutPrimary:
        name = "mimo"

        def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
            calls.append(self.name)
            time.sleep(0.02)
            raise TimeoutError("primary timed out")

    class FastFallback:
        name = "opencode"

        def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
            calls.append(self.name)
            return ModelResult(text="fallback council draft", provider=self.name)

    monkeypatch.setenv("MUCHANIPO_COUNCIL_CALL_TIMEOUT_SEC", "0.01")
    events: list[dict] = []
    gateway = GatewayV2(
        providers={"mimo": TimingOutPrimary(), "opencode": FastFallback()},
        stage_routes={"council": "mimo"},
        fallback_chain={"council": ["mimo", "opencode"]},
    )
    progress_gateway = _CouncilProviderProgressGateway(gateway, events.append)

    result = progress_gateway.call(
        "council",
        "persona prompt",
        council_stage="persona_propose",
        layer_id="persona_generation",
    )

    assert result.provider == "opencode"
    assert result.is_fallback is True
    assert calls == ["mimo", "opencode"]
    event_names = [event["event"] for event in events]
    assert "council_provider_call_done" in event_names
    assert "council_provider_call_timeout" not in event_names


def test_council_progress_gateway_exposes_sanitized_live_usage_fields():
    from src.pipeline.idea_to_council import _CouncilProviderProgressGateway

    class UsageGateway:
        stage_routes = {"council": "opencode"}
        fallback_chain = {"council": ["opencode"]}

        def call(self, stage: str, prompt: str, **kwargs) -> ModelResult:
            return ModelResult(
                text="source-backed live response",
                provider="opencode",
                model="opencode/kimi-k2.6",
                raw={"usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}},
            )

    events: list[dict] = []
    gateway = _CouncilProviderProgressGateway(UsageGateway(), events.append)

    gateway.call("council", "persona prompt", council_stage="persona_propose", layer_id="persona_generation")

    done = next(event for event in events if event["event"] == "council_provider_call_done")
    assert done["provider"] == "opencode"
    assert done["model"] == "opencode/kimi-k2.6"
    assert done["http_status_class"] == "2xx"
    assert done["usage_prompt_tokens"] == 11
    assert done["usage_completion_tokens"] == 7
    assert done["usage_total_tokens"] == 18
    assert done["response_chars"] > 0



def test_run_pipeline_returns_ten_rounds_six_chapter_report_and_progress():
    events = []

    result = run_pipeline("딸기 진단키트 시장성", progress_callback=events.append, offline=True)

    assert len(result["rounds"]) == 10
    assert result["depth"] == "deep"
    assert result["executed_council_round_count"] == 10
    assert result["council_persona_pool_size"] == 80
    assert result["active_council_persona_count"] == 6
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
    council_turn_idx = next(
        idx for idx, event in enumerate(events) if event["event"] == "council_turn"
    )
    council_completed_idx = next(
        idx
        for idx, event in enumerate(events)
        if event["event"] == "stage_completed" and event["stage"] == "council"
    )
    assert council_turn_idx < council_completed_idx
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
    assert started_targeting["reference_step"] == 2
    assert "GStack plan-review" in started_targeting["reference_projects"]


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


def test_run_pipeline_honors_bounded_council_env_overrides(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_COUNCIL_ROUND_BUDGET", "1")
    monkeypatch.setenv("MUCHANIPO_ACTIVE_PERSONA_COUNT", "1")

    result = run_pipeline("bounded council smoke", offline=True, depth="shallow")
    artifacts = result["pipeline_result"].state.artifacts

    assert result["executed_council_round_count"] == 1
    assert result["active_council_persona_count"] == 1
    assert artifacts["council_round_budget"] == "1"
    assert artifacts["council_profile_round_budget"] == "6"
    assert artifacts["active_council_persona_count"] == "1"
    assert artifacts["active_council_profile_persona_count"] == "6"


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


def test_run_pipeline_explicit_live_rejects_auto_approve_env(monkeypatch):
    import src.pipeline.runner as runner_mod

    monkeypatch.setenv("MUCHANIPO_HITL_MODE", "auto_approve")

    with pytest.raises(RuntimeError, match="live mode rejects MUCHANIPO_HITL_MODE=auto_approve"):
        runner_mod.run_pipeline("explicit live", offline=False, require_live=True)


def test_run_pipeline_preflights_live_provider_candidates(monkeypatch):
    import src.pipeline.runner as runner_mod

    gateway_kwargs: list[dict] = []
    preflight_stages: list[tuple[str, ...]] = []

    class _Gateway:
        def assert_live_provider_candidates(self, stages):
            preflight_stages.append(tuple(stages))
            return {stage: ["gemini"] for stage in stages}

    class _StopAfterInitPipeline:
        def __init__(self, **kwargs):
            pass

        def run(self, topic):
            raise RuntimeError("stop after live preflight")

    def fake_default_gateway(**kwargs):
        gateway_kwargs.append(dict(kwargs))
        return _Gateway()

    monkeypatch.setattr(runner_mod, "IdeaToCouncilPipeline", _StopAfterInitPipeline)
    monkeypatch.setattr(runner_mod, "default_gateway", fake_default_gateway)
    monkeypatch.setattr(runner_mod, "build_runner", lambda **kwargs: object())

    with pytest.raises(RuntimeError, match="stop after live preflight"):
        runner_mod.run_pipeline("explicit live", offline=False, require_live=True)

    assert gateway_kwargs[0]["require_live_default"] is True
    assert preflight_stages == [
        ("intake", "interview", "targeting", "research", "evidence", "council", "report", "eval")
    ]


def test_run_pipeline_offline_disables_live_academic_targeting(monkeypatch):
    import src.pipeline.runner as runner_mod
    import src.research.academic.openalex as openalex_mod

    class _StopAfterPolicyPipeline:
        def __init__(self, **kwargs):
            pass

        def run(self, topic):
            assert openalex_mod._skip_live_targeting() is True
            assert runner_mod.os.environ["MUCHANIPO_OFFLINE"] == "1"
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
    assert "MUCHANIPO_OFFLINE" not in runner_mod.os.environ


def test_run_pipeline_offline_overrides_stale_live_academic_targeting_env(monkeypatch):
    import src.pipeline.runner as runner_mod
    import src.research.academic.openalex as openalex_mod

    class _StopAfterPolicyPipeline:
        def __init__(self, **kwargs):
            pass

        def run(self, topic):
            assert openalex_mod._skip_live_targeting() is True
            assert runner_mod.os.environ["MUCHANIPO_OFFLINE"] == "1"
            raise RuntimeError("stop after policy")

    monkeypatch.setenv("MUCHANIPO_ACADEMIC_TARGETING", "1")
    monkeypatch.setattr(runner_mod, "IdeaToCouncilPipeline", _StopAfterPolicyPipeline)
    monkeypatch.setattr(runner_mod, "default_gateway", lambda **kwargs: object())
    monkeypatch.setattr(runner_mod, "build_runner", lambda **kwargs: object())

    with pytest.raises(RuntimeError, match="stop after policy"):
        runner_mod.run_pipeline("offline topic", offline=True)

    assert runner_mod.os.environ["MUCHANIPO_ACADEMIC_TARGETING"] == "1"


def test_run_pipeline_source_research_collects_sources_without_live_llm(monkeypatch):
    import src.pipeline.runner as runner_mod

    gateway_kwargs: list[dict] = []
    build_runner_kwargs: list[dict] = []
    pipeline_kwargs: list[dict] = []

    class _StopAfterPolicyPipeline:
        def __init__(self, **kwargs):
            pipeline_kwargs.append(dict(kwargs))

        def run(self, topic):
            assert runner_mod.os.environ["MUCHANIPO_ACADEMIC_TARGETING"] == "1"
            assert runner_mod.os.environ["MUCHANIPO_OFFLINE"] == "0"
            raise RuntimeError("stop after source research policy")

    def fake_gateway(**kwargs):
        gateway_kwargs.append(dict(kwargs))
        return object()

    def fake_build_runner(**kwargs):
        build_runner_kwargs.append(dict(kwargs))
        return object()

    monkeypatch.setenv("MUCHANIPO_SOURCE_RESEARCH", "1")
    monkeypatch.setattr(runner_mod, "IdeaToCouncilPipeline", _StopAfterPolicyPipeline)
    monkeypatch.setattr(runner_mod, "default_gateway", fake_gateway)
    monkeypatch.setattr(runner_mod, "build_runner", fake_build_runner)

    with pytest.raises(RuntimeError, match="stop after source research policy"):
        runner_mod.run_pipeline("source-backed topic", offline=True, require_live=False)

    assert build_runner_kwargs[0]["use_real"] is True
    assert gateway_kwargs[0]["force_offline"] is True
    assert gateway_kwargs[0]["require_live_default"] is False
    assert pipeline_kwargs[0]["require_live"] is False


def test_run_pipeline_live_source_research_applies_bounded_runtime_defaults(monkeypatch):
    import src.pipeline.runner as runner_mod

    for name in (
        "MUCHANIPO_PUBLIC_WEB_TIMEOUT_SECONDS",
        "MUCHANIPO_ACADEMIC_HTTP_TIMEOUT_SECONDS",
        "MUCHANIPO_ACADEMIC_HTTP_MAX_RETRIES",
        "MUCHANIPO_AUTORESEARCH_ITERATIONS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MUCHANIPO_SOURCE_RESEARCH", "1")
    monkeypatch.setenv("MUCHANIPO_VERIFICATION_ROUTING", "mimo_opencode_go_only")
    monkeypatch.setenv("XIAOMI_MIMO_API_KEY", "tp-test")
    observed_env: dict[str, str | None] = {}
    events: list[dict] = []

    class _Gateway:
        def assert_live_provider_candidates(self, stages):
            observed_env["provider_gate_seen"] = ",".join(stages)
            return {stage: ["mimo", "opencode"] for stage in stages}

    class _StopAfterRuntimePolicyPipeline:
        def __init__(self, **kwargs):
            observed_env["public_timeout"] = runner_mod.os.environ.get("MUCHANIPO_PUBLIC_WEB_TIMEOUT_SECONDS")
            observed_env["academic_timeout"] = runner_mod.os.environ.get("MUCHANIPO_ACADEMIC_HTTP_TIMEOUT_SECONDS")
            observed_env["academic_retries"] = runner_mod.os.environ.get("MUCHANIPO_ACADEMIC_HTTP_MAX_RETRIES")
            observed_env["iterations"] = runner_mod.os.environ.get("MUCHANIPO_AUTORESEARCH_ITERATIONS")

        def run(self, topic):
            raise RuntimeError("stop after bounded source runtime policy")

    monkeypatch.setattr(runner_mod, "default_gateway", lambda **kwargs: _Gateway())
    monkeypatch.setattr(runner_mod, "build_runner", lambda **kwargs: object())
    monkeypatch.setattr(runner_mod, "IdeaToCouncilPipeline", _StopAfterRuntimePolicyPipeline)

    with pytest.raises(RuntimeError, match="bounded source runtime policy"):
        runner_mod.run_pipeline(
            "live source topic",
            offline=False,
            require_live=True,
            depth="shallow",
            progress_callback=events.append,
        )

    provider_ready = next(event for event in events if event.get("status") == "provider_route_candidates_ready")
    assert provider_ready["stage"] == "provider_routing"
    assert provider_ready["live_required"] is True
    assert provider_ready["route_candidates"]["research"] == ["mimo", "opencode"]
    assert provider_ready["route_candidates"]["evidence"] == ["mimo", "opencode"]
    assert observed_env["provider_gate_seen"]
    assert observed_env["public_timeout"] == "4.0"
    assert observed_env["academic_timeout"] == "4.0"
    assert observed_env["academic_retries"] == "1"
    assert observed_env["iterations"] == "1"
    assert runner_mod.os.environ.get("MUCHANIPO_PUBLIC_WEB_TIMEOUT_SECONDS") is None
    assert runner_mod.os.environ.get("MUCHANIPO_ACADEMIC_HTTP_TIMEOUT_SECONDS") is None
    assert runner_mod.os.environ.get("MUCHANIPO_ACADEMIC_HTTP_MAX_RETRIES") is None
    assert runner_mod.os.environ.get("MUCHANIPO_AUTORESEARCH_ITERATIONS") is None


def test_run_pipeline_source_research_records_karpathy_autoresearch_loop(monkeypatch, tmp_path):
    import src.pipeline.runner as runner_mod

    class SourceRunner:
        def __init__(self):
            self.last_backend_trace: list[dict] = []

        def run(self, plan):
            query = plan.queries[0]
            ref = EvidenceRef(
                id="source-ref",
                source_url="https://doi.org/10.1234/strawberry",
                source_title="Strawberry diagnostics paper",
                quote="strawberry diagnostics source-backed evidence",
                source_grade="A" if "official statistics" in query else "B",
                provenance={"kind": "openalex", "metadata": {"query": query}},
            )
            self.last_backend_trace = [
                {
                    "backend": "academic",
                    "query": query,
                    "status": "ok",
                    "count": 1,
                }
            ]
            return [Finding(claim="source-backed evidence", support=[ref], confidence=0.8)]

    monkeypatch.setenv("MUCHANIPO_SOURCE_RESEARCH", "1")
    monkeypatch.setenv("MUCHANIPO_AUTORESEARCH_WORKDIR", str(tmp_path))
    monkeypatch.setattr(runner_mod, "build_runner", lambda **kwargs: SourceRunner())

    result = runner_mod.run_pipeline(
        "딸기 진단키트 시장성",
        offline=True,
        require_live=False,
        depth="shallow",
    )
    artifacts = result["pipeline_result"].state.artifacts
    runtime = json.loads(artifacts["karpathy_autoresearch_runtime"])
    backend_trace = json.loads(artifacts["research_backend_trace"])

    assert artifacts["source_research_enabled"] == "true"
    assert artifacts["research_runner_kind"] == "KarpathyAutoresearchRunner"
    assert artifacts["karpathy_autoresearch_source_revision"] == "228791fb499afffb54b46200aca536f79142f117"
    assert artifacts["karpathy_autoresearch_source_path"] == "third_party/karpathy-autoresearch"
    assert artifacts["karpathy_autoresearch_iteration_count"] == "2"
    assert runtime["adaptation_boundary"] == "scratch_query_plan_loop_no_repo_git_reset"
    assert Path(runtime["program_path"]).exists()
    assert Path(runtime["results_path"]).exists()
    assert {item["autoresearch_iteration"] for item in backend_trace} == {1, 2}


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


def test_run_pipeline_honors_muchanipo_vault_root_env(tmp_path, monkeypatch):
    """When MUCHANIPO_VAULT_ROOT is set, the report is written under that root."""
    vault_root = tmp_path / "vault-root"
    monkeypatch.setenv("MUCHANIPO_VAULT_ROOT", str(vault_root))

    result = run_pipeline("딸기 진단키트 시장성", offline=True)

    vault_path = Path(result["vault_path"])
    assert vault_path.exists()
    assert vault_path.is_file()
    # The vault file must live under the configured root, not under the
    # default temp scratch directory.
    assert str(vault_path).startswith(str(vault_root))
    assert vault_path.read_text(encoding="utf-8").strip()
