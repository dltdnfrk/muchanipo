import json

from src.execution.models import ModelResult
from src.interview.counselling import ask_prd_counselling_question


class FakeGateway:
    def __init__(self, text: str) -> None:
        self.text = text
        self.prompts: list[str] = []

    def call(self, stage: str, prompt: str, **kwargs):
        self.prompts.append(prompt)
        return ModelResult(text=self.text, provider="fake-llm", model="counsellor-test")


class RaisingGateway:
    def call(self, stage: str, prompt: str, **kwargs):
        raise RuntimeError("model unavailable")


def test_prd_counselling_uses_llm_question_and_reference_metadata() -> None:
    payload = {
        "ontology_delta": {
            "entities": [{"id": "actor:farm", "label": "농가", "kind": "actor"}],
            "relations": [],
            "excluded_meanings": ["단순 작물 모니터링"],
            "evidence_boundaries": ["현장 의사결정 근거"],
        },
        "unknowns": [
            {
                "id": "ambiguous:농업-온톨로지",
                "kind": "ambiguous_term",
                "label": "농업 온톨로지",
                "why_it_matters": "기술 구현과 농가 행동 변화가 다른 ontology를 요구한다.",
                "candidate_interpretations": ["대사체 데이터 추출", "농가 의사결정"],
                "entropy": 0.91,
            }
        ],
        "next_question": {
            "question": "참고한 농업 온톨로지 자료를 기준으로, 농업 온톨로지는 대사체 데이터 추출 자동화와 농가 의사결정 중 무엇을 먼저 안정화해야 하나요?",
            "rationale": "사용자가 준 참고자료가 기술 구현과 구매 의사결정을 동시에 암시하므로 먼저 wedge를 좁혀야 한다.",
            "targets_unknown_ids": ["ambiguous:농업-온톨로지"],
        },
        "reference_insights": ["농업 온톨로지", "대사체 데이터", "농가 의사결정"],
        "assumptions_to_test": ["온톨로지 추출 결과가 실제 농가 행동을 바꾼다"],
        "prd_impact": "ontology.target_scenarios and capability_graph",
        "options": [
            {"label": "대사체 데이터 추출", "description": "기술 상태/데이터 ontology", "recommended": "true"},
            {"label": "농가 의사결정", "description": "actor/workflow ontology"},
        ],
    }
    gateway = FakeGateway(json.dumps(payload, ensure_ascii=False))

    framed = ask_prd_counselling_question(
        "Q3_context",
        "농업 온톨로지 데이터 추출 기반 대사체 농업",
        {
            "known": "참고자료: 농업 온톨로지 논문, 대사체 데이터 파이프라인, 농가 상담 사례",
            "purpose": "실제 PRD로 만들 수 있는 첫 제품 wedge 결정",
        },
        gateway=gateway,
    )

    assert "농업 온톨로지" in framed["question"]
    assert "무엇을 먼저 안정화" in framed["question"]
    assert framed["options"][0]["label"] == "대사체 데이터 추출"
    counselling = framed["counselling"]
    assert counselling["mode"] == "llm_counselling"
    assert counselling["provider"] == "fake-llm"
    assert "농업 온톨로지" in counselling["reference_insights"]
    assert "target_scenarios" in counselling["prd_impact"]
    assert framed["targets_unknown_ids"] == ["ambiguous:농업-온톨로지"]
    assert framed["question_quality_gate"]["passed"] is True
    assert framed["unknowns"][0]["label"] == "농업 온톨로지"
    assert framed["ontology_delta"]["excluded_meanings"] == ["단순 작물 모니터링"]
    assert "Reference/background material" in gateway.prompts[0]
    assert "ontology extraction" in gateway.prompts[0]
    assert "really asking" in gateway.prompts[0]
    assert "ONE incisive follow-up" in gateway.prompts[0]
    assert "entities, actors, actions, triggers" in gateway.prompts[0]
    assert "generic decision-form" in gateway.prompts[0]
    assert "Open unknowns, ordered by entropy" in gateway.prompts[0]
    assert "targets_unknown_ids" in gateway.prompts[0]
    assert "고정" not in framed["question"]


def test_prd_counselling_fallback_still_uses_references_not_bare_template() -> None:
    framed = ask_prd_counselling_question(
        "Q4_known",
        "농업 온톨로지 데이터 추출 기반 대사체 농업",
        {
            "known": "작물 생육 단계 온톨로지; LC-MS 대사체 데이터; 농가별 처방 리포트",
            "context": "국내 스마트팜 농가",
        },
        gateway=None,
    )

    assert "참고자료" in framed["question"] or "배경" in framed["question"]
    assert "정의가 흔들리는 용어" in framed["question"]
    assert "개념" in framed["question"]
    counselling = framed["counselling"]
    assert counselling["mode"] == "heuristic_counselling_fallback"
    assert any("온톨로지" in item for item in counselling["reference_insights"])
    assert counselling["assumptions_to_test"]
    assert counselling["prd_impact"]


def test_prd_counselling_fallback_avoids_generic_decision_form_questions() -> None:
    framed = ask_prd_counselling_question(
        "Q2_purpose",
        "한국 65세 이상 1인 가구 재택의료 SaaS",
        {
            "Q1_research_question": "노인 1인 가구가 재택의료를 신청하지 못하는 이유를 알고 싶다",
        },
        gateway=None,
    )

    question = framed["question"]
    assert "실제로 어떤 결정을" not in question
    assert "PRD가 왜 실행 불가능" not in question
    assert "서로 다른 해석" in question
    assert "사용자가 겪는 문제 구조" in question
    assert "기술/데이터가 판별해야 하는 상태" in question


def test_prd_counselling_rejects_model_generic_form_question_and_falls_back() -> None:
    payload = {
        "question": "답을 얻은 뒤 어떤 결정이나 산출물을 만들 계획인가요?",
        "rationale": "generic form",
        "reference_insights": [],
        "assumptions_to_test": [],
        "prd_impact": "generic",
        "options": [],
    }
    framed = ask_prd_counselling_question(
        "Q2_purpose",
        "한국 65세 이상 1인 가구 재택의료 SaaS",
        {"Q1_research_question": "노인 1인 가구가 재택의료를 신청하지 못하는 이유"},
        gateway=FakeGateway(json.dumps(payload, ensure_ascii=False)),
    )

    assert framed["question"]
    assert "답을 얻은 뒤 어떤 결정" not in framed["question"]
    assert "어떤 결정이나 산출물" not in framed["question"]
    assert "서로 다른 해석" in framed["question"]
    assert framed["counselling"]["mode"] == "heuristic_counselling_fallback"


def test_prd_counselling_rejects_question_that_does_not_target_unknown() -> None:
    payload = {
        "unknowns": [
            {
                "id": "ambiguous:재택의료",
                "kind": "ambiguous_term",
                "label": "재택의료",
                "why_it_matters": "서비스 범위가 actor/workflow를 바꾼다.",
                "candidate_interpretations": ["방문진료", "원격 모니터링"],
                "entropy": 0.95,
            }
        ],
        "next_question": {
            "question": "사용자의 목표를 조금 더 설명해 주세요.",
            "rationale": "too generic",
            "targets_unknown_ids": [],
        },
    }
    framed = ask_prd_counselling_question(
        "Q1_research_question",
        "한국 65세 이상 1인 가구 재택의료 SaaS",
        {},
        gateway=FakeGateway(json.dumps(payload, ensure_ascii=False)),
    )

    assert framed["counselling"]["mode"] == "heuristic_counselling_fallback"
    assert "재택의료" in framed["question"]
    assert framed["targets_unknown_ids"]
    assert framed["question_quality_gate"]["passed"] is True


def test_prd_counselling_gateway_failure_keeps_ontology_fallback() -> None:
    framed = ask_prd_counselling_question(
        "Q5_deliverable",
        "개발팀 AI 코드 변경 보안 게이트웨이",
        {
            "Q1_research_question": "AI가 만든 코드 변경을 승인 전 검증하는 흐름",
            "context": "기업 개발팀, Pull Request, 보안 리뷰",
        },
        gateway=RaisingGateway(),
    )

    assert "개념 지도" in framed["question"]
    assert "핵심 엔티티" in framed["question"]
    assert "금지해야 할 오해" in framed["question"]
    assert "ontology.entity_relation_map" in framed["counselling"]["prd_impact"]
    assert framed["counselling"]["fallback_reason"] == "model unavailable"
