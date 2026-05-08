"""Planning-question contract shared by interview prompt and projection code."""
from __future__ import annotations


def planning_question_contract() -> list[dict[str, str]]:
    """Question-to-planning-artifact mapping used by tests and UI copy."""
    return [
        {
            "id": "Q1_research_question",
            "brief_key": "research_question",
            "planning_target": "prd.overview",
            "label": "핵심 개체·질문",
        },
        {
            "id": "Q2_purpose",
            "brief_key": "purpose",
            "planning_target": "prd.core_value",
            "label": "해석 경계",
        },
        {
            "id": "Q3_context",
            "brief_key": "context",
            "planning_target": "prd.target_scenarios",
            "label": "행위자·트리거·워크플로우",
        },
        {
            "id": "Q4_known",
            "brief_key": "known",
            "planning_target": "prd.background_and_constraints",
            "label": "정의·제약·참고근거",
        },
        {
            "id": "Q5_deliverable",
            "brief_key": "deliverable_type",
            "planning_target": "feature_hierarchy",
            "label": "개념 지도·관계 구조",
        },
        {
            "id": "Q6_quality",
            "brief_key": "quality_bar",
            "planning_target": "prd.success_metrics",
            "label": "증거 경계·반례 기준",
        },
    ]
