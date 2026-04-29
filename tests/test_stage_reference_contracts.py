from src.pipeline.reference_contracts import CONTRACTS, contract_for_stage, references_for_stage
from src.pipeline.stages import Stage


def test_all_six_reference_steps_are_declared():
    assert [contract.step for contract in CONTRACTS] == [1, 2, 3, 4, 5, 6]


def test_reference_contract_maps_runtime_stages():
    assert "GPTaku show-me-the-prd" in references_for_stage(Stage.INTERVIEW)
    assert "GStack plan-review" in references_for_stage(Stage.TARGETING)
    assert "Karpathy Autoresearch" in references_for_stage(Stage.RESEARCH)
    assert "출처 기반 연구 원칙" in references_for_stage(Stage.EVIDENCE)
    assert "HACHIMI" in references_for_stage(Stage.COUNCIL)
    assert "GStack learnings_log" in references_for_stage(Stage.DONE)


def test_stage_one_contract_keeps_show_prd_and_office_hours_distinct():
    contract = contract_for_stage(Stage.INTERVIEW)
    assert contract is not None
    notes = "\n".join(contract.notes)
    assert "show-me-the-prd" in notes
    assert "office-hours" in notes
