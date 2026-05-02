"""Planning-question contract shared by interview prompt and projection code."""
from __future__ import annotations


def planning_question_contract() -> list[dict[str, str]]:
    """Question-to-planning-artifact mapping used by tests and UI copy."""
    return [
        {
            "id": "Q1_research_question",
            "brief_key": "research_question",
            "planning_target": "prd.overview",
            "label": "PRD 개요",
        },
        {
            "id": "Q2_purpose",
            "brief_key": "purpose",
            "planning_target": "prd.core_value",
            "label": "핵심 가치",
        },
        {
            "id": "Q3_context",
            "brief_key": "context",
            "planning_target": "prd.target_scenarios",
            "label": "타겟 및 시나리오",
        },
        {
            "id": "Q4_known",
            "brief_key": "known",
            "planning_target": "prd.background_and_constraints",
            "label": "기존 정보·제약",
        },
        {
            "id": "Q5_deliverable",
            "brief_key": "deliverable_type",
            "planning_target": "feature_hierarchy",
            "label": "요구사항→기능→상세기능",
        },
        {
            "id": "Q6_quality",
            "brief_key": "quality_bar",
            "planning_target": "prd.success_metrics",
            "label": "성공 지표·검증 기준",
        },
    ]
