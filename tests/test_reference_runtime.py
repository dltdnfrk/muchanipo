from __future__ import annotations

from src.evidence.artifact import EvidenceRef
from src.execution.models import ModelResult
from src.pipeline.reference_runtime import build_reference_runtime_artifacts
from src.report.schema import ResearchReport


class _GatewayReACTResponder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def call(self, stage: str, prompt: str, **kwargs):
        self.calls.append({"stage": stage, "prompt": prompt, "kwargs": dict(kwargs)})
        idx = len(self.calls) % 4
        if idx == 1:
            text = '<tool_call>{"name":"insight_forge","parameters":{"query":"gateway react evidence"}}</tool_call>'
        elif idx == 2:
            text = '<tool_call>{"name":"mempalace_search","parameters":{"query":"gateway react evidence"}}</tool_call>'
        elif idx == 3:
            text = '<tool_call>{"name":"web_search","parameters":{"query":"gateway react evidence"}}</tool_call>'
        else:
            text = "Final Answer: gateway ReACT wrote this section from tool observations."
        return ModelResult(text=text, provider="test-gateway", model="react-test")


class _Council:
    personas = []
    rounds = [{"consensus": "gateway react evidence should be used"}]


def test_reference_runtime_wires_react_to_live_gateway(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_OFFLINE", "1")
    gateway = _GatewayReACTResponder()
    report = ResearchReport(
        brief_id="brief-react",
        title="gateway react evidence",
        executive_summary="gateway summary",
        evidence_refs=[
            EvidenceRef(
                id="ref-react",
                source_url="local://react",
                source_title="React Source",
                quote="gateway react evidence",
                source_grade="A",
                provenance={"kind": "local", "source_text": "gateway react evidence"},
            )
        ],
        confidence=0.8,
    )

    artifacts = build_reference_runtime_artifacts(
        report=report,
        council=_Council(),
        evidence_summary={"trusted": 1, "verified_claim_ratio": 1.0, "unsupported_finding_count": 0},
        gateway=gateway,
        require_live=True,
    )

    react = artifacts["react"]
    assert react["gateway_llm_enabled"] is True
    assert react["llm_response_count"] >= 4
    assert "llm_react_loop" in react["execution_modes"]
    assert gateway.calls
    assert all(call["stage"] == "report" for call in gateway.calls)
    assert all(call["kwargs"]["require_live"] is True for call in gateway.calls)
    assert react["sections"][0]["execution_mode"] == "llm_react_loop"
    assert react["sections"][0]["section_markdown"].startswith("gateway ReACT wrote")
