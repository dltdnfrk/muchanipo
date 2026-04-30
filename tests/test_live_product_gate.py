from pathlib import Path
from types import SimpleNamespace
import sys
import types

import pytest

from src.evidence.artifact import EvidenceRef, Finding
from src.evidence.store import EvidenceStore
from src.execution.gateway_v2 import GatewayV2
from src.execution.models import ModelGateway, ModelResult
from src.execution.providers.mock import MockProvider
from src.hitl.plannotator_adapter import HITLAdapter
from src.pipeline.idea_to_council import IdeaToCouncilPipeline, _round_digests
from src.runtime.live_mode import LiveModeViolation, assert_live_report


class _SuccessProvider:
    name = "gemini"

    def call(self, stage: str, prompt: str, **kwargs):
        return ModelResult(text="source-backed answer", provider=self.name, model="gemini-live")


class _EmptyEvidenceRunner:
    def run(self, plan):
        return [
            Finding(
                claim=f"Initial research direction for: {query}",
                support=[
                    EvidenceRef(
                        id=f"empty-{idx}",
                        source_url=None,
                        source_title="No live evidence — graceful fallback",
                        quote=query,
                        source_grade="D",
                        provenance={"kind": "empty", "query": query},
                    )
                ],
                confidence=0.2,
            )
            for idx, query in enumerate(plan.queries, start=1)
        ]


class _TrustedEvidenceRunner:
    def run(self, plan):
        ref = EvidenceRef(
            id="openalex:live-1",
            source_url="https://doi.org/10.123/live",
            source_title="Live academic source",
            quote="strawberry diagnostics evidence",
            source_grade="A",
            provenance={
                "kind": "openalex",
                "source_text": "strawberry diagnostics evidence",
            },
        )
        return [
            Finding(
                claim="strawberry diagnostics evidence",
                support=[ref],
                confidence=0.8,
            )
        ]


class _OnlyCGradeEvidenceRunner:
    def run(self, plan):
        ref = EvidenceRef(
            id="web:live-c",
            source_url="https://example.com/live-c",
            source_title="Live but weak web source",
            quote="strawberry diagnostics evidence",
            source_grade="C",
            provenance={
                "kind": "web",
                "source": "https://example.com/live-c",
                "source_text": "strawberry diagnostics evidence",
            },
        )
        return [
            Finding(
                claim="strawberry diagnostics evidence",
                support=[ref],
                confidence=0.55,
            )
        ]


def test_gateway_live_mode_rejects_mock_provider_result():
    gw = GatewayV2(
        providers={"mock": MockProvider()},
        stage_routes={"research": "mock"},
        fallback_chain={"research": ["mock"]},
    )

    with pytest.raises(LiveModeViolation, match="mock model result"):
        gw.call("research", "ping", require_live=True)


def test_gateway_default_live_mode_rejects_mock_provider_result_without_env():
    gw = GatewayV2(
        providers={"mock": MockProvider()},
        stage_routes={"research": "mock"},
        fallback_chain={"research": ["mock"]},
        require_live_default=True,
    )

    with pytest.raises(LiveModeViolation, match="mock model result"):
        gw.call("research", "ping")


def test_gateway_real_research_env_rejects_mock_provider_result(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_REAL_RESEARCH", "1")
    monkeypatch.delenv("MUCHANIPO_REQUIRE_LIVE", raising=False)
    gw = GatewayV2(
        providers={"mock": MockProvider()},
        stage_routes={"research": "mock"},
        fallback_chain={"research": ["mock"]},
    )

    with pytest.raises(LiveModeViolation, match="mock model result"):
        gw.call("research", "ping")


def test_gateway_live_mode_allows_non_mock_result():
    gw = GatewayV2(
        providers={"gemini": _SuccessProvider()},
        stage_routes={"research": "gemini"},
        fallback_chain={"research": ["gemini"]},
    )

    result = gw.call("research", "ping", require_live=True)

    assert result.provider == "gemini"
    assert result.text == "source-backed answer"


def test_gateway_live_mode_rejects_empty_or_short_output():
    class _ShortProvider:
        name = "anthropic"

        def call(self, stage: str, prompt: str, **kwargs):
            return ModelResult(text="ok", provider=self.name, model="claude-live")

    gw = GatewayV2(
        providers={"anthropic": _ShortProvider()},
        stage_routes={"report": "anthropic"},
        fallback_chain={"report": ["anthropic"]},
    )

    with pytest.raises(LiveModeViolation, match="too-short"):
        gw.call("report", "ping", require_live=True)


def test_pipeline_live_mode_blocks_pending_hitl(tmp_path: Path):
    pipeline = IdeaToCouncilPipeline(
        hitl_adapter=HITLAdapter(mode="markdown", queue_dir=tmp_path / "queue", timeout_seconds=0),
        research_runner=_TrustedEvidenceRunner(),
        vault_dir=tmp_path / "vault",
        council_log_dir=tmp_path / "council",
        require_live=True,
    )

    with pytest.raises(LiveModeViolation, match="approved HITL gate 'plan'"):
        pipeline.run("딸기 농가용 진단키트 시장성")


def test_pipeline_live_mode_blocks_empty_research_evidence(tmp_path: Path):
    pipeline = IdeaToCouncilPipeline(
        hitl_adapter=HITLAdapter(mode="auto_approve"),
        research_runner=_EmptyEvidenceRunner(),
        vault_dir=tmp_path / "vault",
        council_log_dir=tmp_path / "council",
        require_live=True,
    )

    with pytest.raises(LiveModeViolation, match="non-live evidence"):
        pipeline.run("딸기 농가용 진단키트 시장성")


def test_pipeline_live_mode_requires_ab_grade_evidence_floor(tmp_path: Path):
    pipeline = IdeaToCouncilPipeline(
        hitl_adapter=HITLAdapter(mode="auto_approve"),
        research_runner=_OnlyCGradeEvidenceRunner(),
        vault_dir=tmp_path / "vault",
        council_log_dir=tmp_path / "council",
        require_live=True,
    )

    with pytest.raises(LiveModeViolation, match="A/B-grade evidence"):
        pipeline.run("딸기 농가용 진단키트 시장성")


def test_pipeline_live_mode_rejects_fallback_council_personas(tmp_path: Path, monkeypatch):
    import src.pipeline.idea_to_council as pipeline_mod

    class _FallbackPersonaGenerator:
        def __init__(self, *args, **kwargs):
            pass

        def generate(self, *args, **kwargs):
            return [
                SimpleNamespace(
                    persona_id="persona-fallback-001",
                    name="Fallback Evidence Reviewer 1",
                    role="evidence_reviewer",
                    manifest={"fallback": True},
                )
            ], {"fallbacks_used": 1, "coverage_after_admit": 0.0}

    monkeypatch.setattr(pipeline_mod, "PersonaGenerator", _FallbackPersonaGenerator)
    pipeline = IdeaToCouncilPipeline(
        hitl_adapter=HITLAdapter(mode="auto_approve"),
        research_runner=_TrustedEvidenceRunner(),
        model_gateway=GatewayV2(
            providers={"gemini": _SuccessProvider()},
            stage_routes={"council": "gemini"},
            fallback_chain={"council": ["gemini"]},
        ),
        vault_dir=tmp_path / "vault",
        council_log_dir=tmp_path / "council",
        require_live=True,
    )

    with pytest.raises(LiveModeViolation, match="fallback council personas"):
        pipeline.run("딸기 농가용 진단키트 시장성")


def test_pipeline_live_mode_blocks_plan_review_failure(tmp_path: Path, monkeypatch):
    import src.pipeline.idea_to_council as pipeline_mod

    class _BlockingPlanReview:
        def autoplan(self, design_doc):
            return SimpleNamespace(
                design_doc=design_doc,
                consensus_score=0.1,
                gate_passed=False,
                gate_reason="insufficient consensus",
            )

    monkeypatch.setattr(pipeline_mod, "PlanReview", _BlockingPlanReview)
    pipeline = IdeaToCouncilPipeline(
        hitl_adapter=HITLAdapter(mode="auto_approve"),
        research_runner=_TrustedEvidenceRunner(),
        vault_dir=tmp_path / "vault",
        council_log_dir=tmp_path / "council",
        require_live=True,
    )

    with pytest.raises(LiveModeViolation, match="plan review gate"):
        pipeline.run("딸기 농가용 진단키트 시장성")


def test_pipeline_env_real_research_implies_live_gate(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MUCHANIPO_REAL_RESEARCH", "1")

    pipeline = IdeaToCouncilPipeline(
        hitl_adapter=HITLAdapter(mode="auto_approve"),
        research_runner=_EmptyEvidenceRunner(),
        vault_dir=tmp_path / "vault",
        council_log_dir=tmp_path / "council",
    )

    assert pipeline.require_live is True
    with pytest.raises(LiveModeViolation, match="non-live evidence"):
        pipeline.run("딸기 농가용 진단키트 시장성")


def test_pipeline_constructor_require_live_propagates_to_gateway(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("MUCHANIPO_REQUIRE_LIVE", raising=False)
    monkeypatch.delenv("MUCHANIPO_ONLINE", raising=False)
    monkeypatch.delenv("MUCHANIPO_REAL_RESEARCH", raising=False)
    gw = GatewayV2(
        providers={"mock": MockProvider(response="mock council critique")},
        stage_routes={"council": "mock"},
        fallback_chain={"council": ["mock"]},
    )
    pipeline = IdeaToCouncilPipeline(
        hitl_adapter=HITLAdapter(mode="auto_approve"),
        research_runner=_TrustedEvidenceRunner(),
        model_gateway=gw,
        vault_dir=tmp_path / "vault",
        council_log_dir=tmp_path / "council",
        require_live=True,
    )

    with pytest.raises(LiveModeViolation, match="mock model result"):
        pipeline.run("딸기 농가용 진단키트 시장성")


def test_pipeline_live_mode_rejects_empty_model_gateway(tmp_path: Path):
    with pytest.raises(LiveModeViolation, match="non-mock model provider"):
        IdeaToCouncilPipeline(
            model_gateway=ModelGateway(),
            vault_dir=tmp_path / "vault",
            council_log_dir=tmp_path / "council",
            require_live=True,
        )


def test_live_evidence_rejects_missing_source_url_or_source():
    from src.runtime.live_mode import assert_live_evidence

    ref = EvidenceRef(
        id="openalex:no-source",
        source_url=None,
        source_title="Live paper",
        quote="source-backed claim",
        source_grade="A",
        provenance={"kind": "openalex", "source_text": "source-backed claim"},
    )

    with pytest.raises(LiveModeViolation, match="source_url"):
        assert_live_evidence({"trusted": 1}, [ref])


def test_live_report_guard_rejects_mock_markers():
    with pytest.raises(LiveModeViolation, match="report marker"):
        assert_live_report("# Report\n\n[mock-anthropic/council] placeholder\n")


def test_live_report_guard_allows_non_mock_fallback_language():
    assert_live_report(
        "\n".join([
            "# Report",
            "",
            "## Evidence Index",
            "",
            "- `E1` Cited source",
            "",
            "## Chapter 1: Executive Summary",
            "",
            "Anthropic fallback provider returned a cited answer. (Evidence: `E1`)",
            "",
            "## Claim Grounding Matrix",
            "",
            "| Chapter | Claim | Evidence |",
            "| --- | --- | --- |",
            "| 1 | Anthropic fallback provider returned a cited answer. | `E1` |",
            "",
        ])
    )


def test_live_report_guard_rejects_uncited_real_sounding_report():
    with pytest.raises(LiveModeViolation, match="Evidence Index"):
        assert_live_report(
            "\n".join([
                "# Report",
                "",
                "## Chapter 1: Executive Summary",
                "",
                "The market is attractive and the product should launch.",
                "",
            ])
        )


def test_live_report_guard_rejects_claims_without_explicit_evidence_refs():
    with pytest.raises(LiveModeViolation, match="explicit evidence citations"):
        assert_live_report(
            "\n".join([
                "# Report",
                "",
                "## Evidence Index",
                "",
                "- `E1` Cited source",
                "",
                "## Chapter 1: Executive Summary",
                "",
                "The market is attractive and the product should launch.",
                "",
                "## Claim Grounding Matrix",
                "",
                "| Chapter | Claim | Evidence |",
                "| --- | --- | --- |",
                "| 1 | The market is attractive. | `E1` |",
                "",
            ])
        )


def test_offline_report_limitations_do_not_self_trip_live_guard():
    from src.pipeline.idea_to_council import _report_limitations

    text = "\n".join(_report_limitations(require_live=False))

    assert "mock-first skeleton" not in text
    assert "not a real autoresearch run" not in text


def test_evidence_store_live_mode_fails_closed_on_provenance_validator_error(monkeypatch):
    module = types.ModuleType("src.eval.citation_grounder")

    def boom(payload):
        raise RuntimeError("validator unavailable")

    module._lockdown_validate_provenance = boom
    monkeypatch.setitem(sys.modules, "src.eval.citation_grounder", module)

    ref = EvidenceRef(
        id="openalex:live-provenance",
        source_url="https://doi.org/10.123/live-provenance",
        source_title="Live paper",
        quote="source-backed claim",
        source_grade="A",
        provenance={"kind": "openalex", "source_text": "source-backed claim"},
    )

    with pytest.raises(LiveModeViolation, match="provenance validation failed"):
        EvidenceStore(require_live=True).add(ref)


def test_live_vault_save_uses_run_version_suffix(tmp_path: Path):
    pipeline = IdeaToCouncilPipeline(
        hitl_adapter=HITLAdapter(mode="auto_approve"),
        vault_dir=tmp_path / "vault",
        require_live=True,
    )

    path = pipeline._save_to_vault("brief-123", "# report\n", run_id="run:abc/123")

    assert path.name == "brief-123-run-abc-123.md"
    assert path.read_text(encoding="utf-8") == "# report\n"


def test_live_council_digest_rejects_synthetic_round_fallback():
    ref = EvidenceRef(
        id="openalex:live-council",
        source_url="https://doi.org/10.123/live-council",
        source_title="Live council source",
        quote="source-backed claim",
        source_grade="A",
        provenance={"kind": "openalex", "source_text": "source-backed claim"},
    )

    with pytest.raises(LiveModeViolation, match="structured council synthesis"):
        _round_digests(SimpleNamespace(rounds=[]), [ref], require_live=True)
