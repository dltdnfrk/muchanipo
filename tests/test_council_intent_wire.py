"""C23-A: council-runner.py에 ConsensusPlan ontology가 wire되는지 검증.

Phase 0d (ConsensusPlan.to_ontology) → council Step 4 (페르소나 선택) 진입을 확인.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# council-runner는 같은 디렉토리의 persona_sampler를 lazy import 함
sys.path.insert(0, str(ROOT / "src/council"))

from conftest import load_script_module

# 파일명에 hyphen이 있어 importlib 우회 로딩
council_runner = load_script_module(
    "council_runner_c23",
    "src/council/council-runner.py",
)


def _sample_consensus_ontology() -> dict:
    """ConsensusPlan.to_ontology() 모의 출력."""
    return {
        "roles": ["topic_owner", "evidence_reviewer", "contrarian", "agtech_farmer"],
        "intents": [
            "Topic: 한국 사과 농가 진단키트 가격 책정",
            "10-star: 한국 grounded persona seed로 검증된 결과",
            "Pain root: 가격 모호",
        ],
        "allowed_tools": ["read_file", "search_web", "search_vault"],
        "required_outputs": ["consensus", "dissent", "recommendations"],
        "value_axes": {
            "time_horizon": "mid",
            "risk_tolerance": 0.55,
            "stakeholder_priority": ["primary_user"],
            "innovation_orientation": 0.7,
        },
        "design_doc_brief": "# Design — 한국 AgTech 농가 진단키트",
        "ceo_mode": "selective",
        "feasibility": "medium",
    }


def test_select_personas_from_consensus_plan_uses_role_mapping():
    """추상 역할(evidence_reviewer 등)이 _PERSONA_POOL 구체 역할로 매핑된다."""
    onto = _sample_consensus_ontology()
    personas = council_runner._select_personas_from_consensus_plan(
        onto, count=4, topic="한국 사과 농가"
    )
    assert len(personas) == 4
    roles = {p["role"] for p in personas}
    # evidence_reviewer → 학술연구자 매핑이 들어왔거나 풀 보충 가능
    # 최소한 추상 역할이 그대로 남아 있지 않음 (agtech_farmer 제외)
    assert "evidence_reviewer" not in roles
    assert "topic_owner" not in roles


def test_select_personas_from_consensus_plan_injects_agtech_farmer_for_korean():
    """agtech_farmer role이 명시되면 KoreaPersonaSampler로 농가 페르소나가 들어간다."""
    onto = _sample_consensus_ontology()
    personas = council_runner._select_personas_from_consensus_plan(
        onto, count=4, topic="한국 사과 농가"
    )
    roles = [p["role"] for p in personas]
    assert any(r == "agtech_farmer" for r in roles), f"roles={roles}"
    # grounded_seed 또는 entity_type 필드가 농가 페르소나에 붙어야 함
    farmer = next(p for p in personas if p["role"] == "agtech_farmer")
    assert farmer.get("entity_type") == "agtech_farmer"
    assert "grounded_seed" in farmer


def test_select_personas_no_korean_skips_farmer():
    """한국 / agtech 신호가 없으면 농가 페르소나가 추가되지 않는다."""
    onto = {
        "roles": ["topic_owner", "evidence_reviewer", "comparison_judge"],
        "intents": ["Topic: LangGraph vs CrewAI"],
        "design_doc_brief": "# Tool comparison for multi-agent council",
    }
    personas = council_runner._select_personas_from_consensus_plan(
        onto, count=3, topic="LangGraph vs CrewAI"
    )
    assert len(personas) == 3
    assert all(p["role"] != "agtech_farmer" for p in personas)


def test_load_consensus_plan_ontology_supports_outer_wrapper(tmp_path: Path):
    """{"ontology_seed": {...}} 형식의 전체 ConsensusPlan 직렬화도 지원."""
    payload = {
        "consensus_score": 0.72,
        "gate_passed": True,
        "ontology_seed": _sample_consensus_ontology(),
    }
    f = tmp_path / "plan.json"
    f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    onto = council_runner._load_consensus_plan_ontology(f)
    assert "roles" in onto
    assert "topic_owner" in onto["roles"]
    # 외부 키는 제외
    assert "consensus_score" not in onto


def test_load_consensus_plan_ontology_accepts_flat_dict(tmp_path: Path):
    """to_ontology() 결과를 직접 덤프한 경우도 지원."""
    payload = _sample_consensus_ontology()
    f = tmp_path / "plan.json"
    f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    onto = council_runner._load_consensus_plan_ontology(f)
    assert onto["ceo_mode"] == "selective"
    assert onto["feasibility"] == "medium"
