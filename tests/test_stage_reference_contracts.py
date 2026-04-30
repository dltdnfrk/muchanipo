from src.pipeline.reference_contracts import CONTRACTS, contract_for_stage, references_for_stage
from src.pipeline.reference_inventory import VALID_CATEGORIES, reference_readiness_report
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


def test_reference_inventory_covers_all_stage_contract_references():
    report = reference_readiness_report()
    names = {
        value
        for item in report["references"]
        for value in [item["name"], *item["aliases"]]
    }

    for contract in CONTRACTS:
        for reference in contract.references:
            assert reference in names


def test_reference_readiness_report_surfaces_gaps_and_license_warnings():
    report = reference_readiness_report()

    assert report["schema_version"] == 1
    assert report["command"] == "muchanipo references"
    assert [stage["step"] for stage in report["stages"]] == [1, 2, 3, 4, 5, 6]
    assert set(report["valid_categories"]) == set(VALID_CATEGORIES)
    assert all(item["category"] in VALID_CATEGORIES for item in report["references"])
    assert not any(item["category"] == "vendored code" for item in report["references"])
    warnings = {item["name"]: item["warning"] for item in report["license_warnings"]}
    assert "MiroFish" in warnings
    assert "AGPL-3.0" in warnings["MiroFish"]
    assert "Nemotron-Personas-Korea" in warnings
    gaps = {item["name"]: item["gap"] for item in report["gaps"]}
    assert "OASIS / CAMEL-AI" in gaps
    assert "MemPalace" in gaps


def test_reference_inventory_paths_exist_for_runtime_backed_items():
    report = reference_readiness_report()

    for item in report["references"]:
        if not item["implemented"]:
            continue
        assert item["present_paths"] == item["code_paths"], item["name"]
