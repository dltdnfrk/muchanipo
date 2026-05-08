from src.interview.ontology_state import (
    InterviewOntologyState,
    build_interview_ontology_state,
    question_quality_gate,
)


def test_ontology_state_serializes_and_preserves_unknown_entropy_order() -> None:
    state = build_interview_ontology_state(
        "한국 65세 이상 1인 가구 재택의료 SaaS",
        {"context": "65세 이상 1인 가구"},
    )

    restored = InterviewOntologyState.from_dict(state.to_dict())
    ordered = restored.sorted_unknowns()

    assert restored.topic == state.topic
    assert ordered
    assert ordered[0].entropy >= ordered[-1].entropy
    assert any(unknown.kind == "ambiguous_term" for unknown in ordered)
    assert any("재택의료" in unknown.label for unknown in ordered)


def test_ontology_unknown_detection_covers_actor_workflow_boundary_and_evidence() -> None:
    state = build_interview_ontology_state("한국 65세 이상 1인 가구 재택의료 SaaS")
    kinds = {unknown.kind for unknown in state.unknowns}
    labels = " ".join(unknown.label for unknown in state.unknowns)

    assert "ambiguous_term" in kinds
    assert "missing_workflow" in kinds
    assert "boundary_gap" in kinds
    assert "evidence_gap" in kinds
    assert "재택의료" in labels
    assert 0 <= state.coverage < 1


def test_question_quality_gate_requires_named_target_unknown() -> None:
    state = build_interview_ontology_state("한국 65세 이상 1인 가구 재택의료 SaaS")
    target = state.sorted_unknowns()[0]

    passed = question_quality_gate(
        question=f"{target.label}의 포함/제외 의미를 먼저 갈라야 합니다. 어디까지 포함하나요?",
        unknowns=state.unknowns,
        targets_unknown_ids=[target.id],
    )
    failed = question_quality_gate(
        question="답을 얻은 뒤 어떤 결정이나 산출물을 만들 계획인가요?",
        unknowns=state.unknowns,
        targets_unknown_ids=[],
    )

    assert passed["passed"] is True
    assert passed["target_unknown_labels"] == [target.label]
    assert failed["passed"] is False
    assert "generic_form_question" in failed["reasons"]
    assert "missing_target_unknown" in failed["reasons"]
