from pathlib import Path
from types import SimpleNamespace

import pytest

from src.evidence.artifact import EvidenceRef, Finding
from src.execution.gateway_v2 import GatewayV2
from src.execution.models import ModelResult
from src.execution.providers.mock import MockProvider
from src.hitl.plannotator_adapter import HITLAdapter
from src.pipeline.idea_to_council import IdeaToCouncilPipeline
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


def test_gateway_live_mode_rejects_mock_provider_result():
    gw = GatewayV2(
        providers={"mock": MockProvider()},
        stage_routes={"research": "mock"},
        fallback_chain={"research": ["mock"]},
    )

    with pytest.raises(LiveModeViolation, match="mock model result"):
        gw.call("research", "ping", require_live=True)


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

    with pytest.raises(LiveModeViolation, match="approved HITL gate 'brief'"):
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


def test_live_report_guard_rejects_mock_markers():
    with pytest.raises(LiveModeViolation, match="report marker"):
        assert_live_report("# Report\n\n[mock-anthropic/council] placeholder\n")
