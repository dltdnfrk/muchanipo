from pathlib import Path

from src.interview.show_me_the_prd_port import (
    UPSTREAM_COMMIT,
    build_show_me_the_prd_plan,
    render_show_me_the_prd_documents,
    show_me_the_prd_document_manifest,
    show_me_the_prd_artifacts,
    vendored_paths_exist,
)
from src.interview.product_planning import build_product_planning_projection


def test_show_me_the_prd_plan_preserves_upstream_pin_and_documents() -> None:
    plan = build_show_me_the_prd_plan("한국 딸기 농가용 진단키트 시장성")

    assert plan.source.commit == UPSTREAM_COMMIT
    assert plan.source.license == "MIT"
    assert "third_party/show-me-the-prd/commands/show-me-the-prd.md" in plan.source.vendored_paths
    assert vendored_paths_exist(Path("."))
    assert plan.document_paths == (
        "PRD/01_PRD.md",
        "PRD/02_DATA_MODEL.md",
        "PRD/03_PHASES.md",
        "PRD/04_PROJECT_SPEC.md",
    )


def test_show_me_the_prd_plan_exposes_full_workflow_contract() -> None:
    plan = build_show_me_the_prd_plan("task manager app")

    assert 1 <= len(plan.initial_questions) <= 3
    assert len(plan.workflow_questions) == 6
    assert [batch.after_turn for batch in plan.research_batches] == [1, 2, 4]
    assert any("app features 2026" in query for batch in plan.research_batches for query in batch.queries)
    assert "feature_and_mvp_choice" in plan.evidence_markers
    assert "data_model_confirmation" in plan.evidence_markers
    assert "stack_and_auth_choice" in plan.evidence_markers
    assert "four_document_output" in plan.evidence_markers


def test_show_me_the_prd_artifacts_distinguish_synthetic_runtime() -> None:
    plan = build_show_me_the_prd_plan("agtech pricing research")
    artifacts = show_me_the_prd_artifacts(
        plan,
        user_answer_count=0,
        office_hours_fill_count=6,
    )

    assert artifacts["show_prd_source_commit"] == UPSTREAM_COMMIT
    assert artifacts["show_prd_runtime_mode"] == "synthetic_office_hours_fill"
    assert artifacts["show_prd_document_outputs"] == ",".join(plan.document_paths)
    assert "research_batch_before_feature_choice" in artifacts["show_prd_evidence_markers"]


def test_show_me_the_prd_renders_four_live_documents_from_answers() -> None:
    answers = {
        "research_question": "현장 농가가 진단키트를 구매할지 검증",
        "purpose": "제품화 go/no-go 결정",
        "context": "한국 딸기 농가",
        "known": "기존 진단은 느림",
        "deliverable_type": "6장 시장성 보고서",
        "quality_bar": "A/B급 출처",
    }
    plan = build_show_me_the_prd_plan("딸기 농가 진단키트", answers=answers)
    planning = build_product_planning_projection("딸기 농가 진단키트", answers)

    documents = render_show_me_the_prd_documents(plan, answers=answers, planning=planning)
    manifest = show_me_the_prd_document_manifest(documents)

    assert tuple(documents) == plan.document_paths
    assert "# Product Requirements Document" in documents["PRD/01_PRD.md"]
    assert "제품화 go/no-go 결정" in documents["PRD/01_PRD.md"]
    assert "# Data Model" in documents["PRD/02_DATA_MODEL.md"]
    assert "ResearchBrief" in documents["PRD/02_DATA_MODEL.md"]
    assert "# Build Phases" in documents["PRD/03_PHASES.md"]
    assert "6장 시장성 보고서" in documents["PRD/03_PHASES.md"]
    assert "# Project Specification" in documents["PRD/04_PROJECT_SPEC.md"]
    assert UPSTREAM_COMMIT in documents["PRD/04_PROJECT_SPEC.md"]
    assert [item["path"] for item in manifest] == list(plan.document_paths)
    assert all(int(item["chars"]) > 100 for item in manifest)
