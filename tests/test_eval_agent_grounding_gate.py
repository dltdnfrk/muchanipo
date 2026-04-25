"""Commit C — eval-agent grounding gate 통합 회귀 테스트."""

import json
from pathlib import Path

import pytest

from conftest import load_script_module


eval_agent = load_script_module("eval_agent", "src/eval/eval-agent.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _high_score_report() -> dict:
    """모든 축 만점에 가까운 PASS 후보 — recommendations/evidence 풍부."""
    return {
        "schema_version": "v2.0",
        "council_id": "council-pass-candidate",
        "topic": "PASS demote target",
        "consensus": (
            "MuchaNipo replay harness reduces manual regression review by 25% in 2026. "
            * 4
        ),
        "recommendations": [
            "Adopt the replay harness for every eval-agent regression run with detailed runbooks.",
            "Keep recent council reports in JSONL so failures can be reproduced quickly.",
            "Pilot rubric-learner v3 with confidence thresholds and weekly retros.",
            "Build telemetry dashboard for grounding gate failures by axis and topic.",
            "Add automated alerts for citation_fidelity score drops across cycles.",
            "Document signoff-queue flow in onboarding kit with concrete scenarios.",
        ],
        "dissent": (
            "The replay set must stay small enough for local pytest runs; otherwise CI bloats. "
            "Critical: keep schema validators in lockstep. Major: warn on missing source_text."
        ),
        "confidence": 0.85,
        # eval-agent의 score_evidence_quality 는 string 리스트를 기대 — string 으로 둠.
        # citation_grounder 는 string 도 _normalize_evidence 에서 dict 로 변환함.
        "evidence": [
            f"근거 자료 {i} — replay harness {i}회 운영 결과 doi:10.0/test.{i} 논문."
            for i in range(1, 11)
        ],
        "personas": [
            {"name": f"P{i}", "role": "QA", "confidence": 0.7 + (i % 3) * 0.1, "layer": (i % 3) + 1}
            for i in range(1, 11)
        ],
        "web_research": [{"sources": 22}, {"sources": 25}, {"sources": 18}],
    }


def _full_rubric(grounding_enabled: bool = True) -> dict:
    """v2.1 11-axis rubric with grounding_gate toggle."""
    axes = {
        name: {"weight": 1.0, "max": 10, "description": name}
        for name in (
            "usefulness", "reliability", "novelty", "actionability",
            "completeness", "evidence_quality", "perspective_diversity",
            "coherence", "depth", "impact",
        )
    }
    axes["citation_fidelity"] = {
        "weight": 0.0,
        "max": 10,
        "description": "weight 0 — 측정만",
        "active_for_score": False,
    }
    return {
        "version": "2.1.0",
        "axes": axes,
        "thresholds": {"pass": 70, "uncertain": 50},
        "grounding_gate": {
            "enabled": grounding_enabled,
            "min_verified_ratio": 0.8,
            "max_critical_unsupported": 0,
            "demote_pass_to_uncertain": True,
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_grounding_gate_demotes_pass_to_uncertain_when_below_ratio():
    report = _high_score_report()
    rubric = _full_rubric(grounding_enabled=True)

    result = eval_agent.evaluate(report, rubric)

    # consensus claim 들이 evidence quote 와 substring 매칭이 안 되므로
    # verified_ratio 는 0.8 미만 → PASS 가 게이트에서 강등돼야 함.
    assert result["grounding"]["verified_claim_ratio"] < 0.8
    decision = result["grounding_gate_decision"]
    assert decision.get("enabled") is True
    assert decision.get("allow_pass") is False
    assert decision.get("demoted") is True
    assert result["verdict"] == "UNCERTAIN"


def test_grounding_gate_disabled_does_not_demote():
    report = _high_score_report()
    rubric = _full_rubric(grounding_enabled=False)

    result = eval_agent.evaluate(report, rubric)

    # gate 비활성화 → 강등 발생 X (총점 자체는 PASS 임계 이상이어야 함)
    decision = result["grounding_gate_decision"]
    assert decision == {} or decision.get("enabled") in (False, None)
    # 충분히 높은 점수 — 강등이 일어나지 않으면 PASS 유지
    assert result["total"] >= rubric["thresholds"]["pass"]
    assert result["verdict"] == "PASS"


def test_citation_fidelity_weight_0_does_not_affect_total():
    report = _high_score_report()
    rubric = _full_rubric(grounding_enabled=True)

    result = eval_agent.evaluate(report, rubric)

    # weight 0 → score 0 으로 기록, 총점에 영향 없음
    assert result["scores"].get("citation_fidelity") == 0
    sum_other_axes = sum(
        v for k, v in result["scores"].items() if k != "citation_fidelity"
    )
    assert result["total"] == sum_other_axes


def test_grounding_result_present_in_eval_output():
    report = _high_score_report()
    rubric = _full_rubric(grounding_enabled=True)

    result = eval_agent.evaluate(report, rubric)

    assert "grounding" in result
    g = result["grounding"]
    for key in (
        "verified_claim_ratio",
        "unsupported_critical_claim_count",
        "per_claim_verdict",
        "total_claims",
        "supported",
        "partial",
        "unsupported",
        "provenance_failures",
    ):
        assert key in g, f"grounding 결과에 {key} 누락"


def test_lockdown_audit_called_on_gate_decision(tmp_path, monkeypatch):
    report = _high_score_report()
    rubric = _full_rubric(grounding_enabled=True)

    calls = []

    class FakeLockdown:
        @staticmethod
        def audit_log(decision, context=None):
            calls.append({"decision": decision, "context": context})
            return tmp_path / "audit.jsonl"

    monkeypatch.setattr(eval_agent, "_load_lockdown", lambda: FakeLockdown)

    eval_agent.evaluate(report, rubric)

    assert len(calls) == 1
    assert calls[0]["decision"] == "grounding_gate"
    ctx = calls[0]["context"]
    assert ctx["council_id"] == "council-pass-candidate"
    assert "decision" in ctx
