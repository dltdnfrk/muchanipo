from pathlib import Path

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
    assert all(stage["ready_count"] <= stage["implemented_count"] for stage in report["stages"])
    assert report["stages"][0]["ready"] is True
    assert all(stage["ready"] for stage in report["stages"])
    assert all(stage["product_standard_ready"] for stage in report["stages"])
    assert all(
        stage["product_standard_covered_count"] == stage["reference_count"]
        for stage in report["stages"]
    )
    assert all(not stage["not_product_standard_covered_references"] for stage in report["stages"])
    assert report["not_stage_contract_covered_references"] == []
    assert set(report["valid_categories"]) == set(VALID_CATEGORIES)
    assert all(item["category"] in VALID_CATEGORIES for item in report["references"])
    show_prd = next(item for item in report["references"] if item["name"] == "GPTaku show-me-the-prd")
    assert show_prd["category"] == "vendored code"
    assert show_prd["ready"] is True
    assert show_prd["claim_level"] == "runtime_with_compliance_warning"
    assert "src/interview/show_me_the_prd_port.py" in show_prd["code_paths"]
    plannotator = next(item for item in report["references"] if item["name"] == "Plannotator")
    assert plannotator["category"] == "vendored code"
    assert plannotator["ready"] is True
    assert plannotator["claim_level"] == "runtime_ready"
    assert "third_party/plannotator/packages/editor/App.tsx" in plannotator["code_paths"]
    assert (
        "app/muchanipo-tauri/src/components/PlannotatorPlanEditor.tsx"
        in plannotator["code_paths"]
    )
    assert "app/muchanipo-tauri/src/plannotator-port/parser.ts" in plannotator["code_paths"]
    warnings = {item["name"]: item["warning"] for item in report["license_warnings"]}
    assert "GPTaku show-me-the-prd" in warnings
    assert "standalone LICENSE" in warnings["GPTaku show-me-the-prd"]
    assert "MiroFish" in warnings
    assert "AGPL-3.0" in warnings["MiroFish"]
    assert "InsightForge" in warnings
    assert "Nemotron-Personas-Korea" in warnings
    assert "GBrain 지식 구조" not in warnings
    gbrain_structure = next(item for item in report["references"] if item["name"] == "GBrain 지식 구조")
    assert gbrain_structure["ready"] is True
    assert gbrain_structure["license"] == "MIT"
    assert gbrain_structure["claim_level"] == "runtime_ready"
    assert "src/wiki/gbrain_runtime.py" in gbrain_structure["code_paths"]
    gbrain_events = next(item for item in report["references"] if item["name"] == "GBrain 현재 결론 + 사건 기록")
    assert gbrain_events["ready"] is True
    assert gbrain_events["claim_level"] == "runtime_ready"
    gbrain_report = next(item for item in report["references"] if item["name"] == "GBrain")
    assert gbrain_report["ready"] is True
    assert gbrain_report["claim_level"] == "runtime_ready"
    mempalace = next(item for item in report["references"] if item["name"] == "MemPalace")
    assert mempalace["ready"] is True
    assert mempalace["claim_level"] == "runtime_ready"
    assert mempalace["license"].startswith("MIT")
    assert mempalace["source_url"] == "https://github.com/MemPalace/mempalace"
    assert "src/research/mempalace.py" in mempalace["code_paths"]
    oasis = next(item for item in report["references"] if item["name"] == "OASIS / CAMEL-AI")
    assert oasis["ready"] is True
    assert oasis["claim_level"] == "runtime_ready"
    assert "src/council/oasis_camel_runtime.py" in oasis["code_paths"]
    mirofish = next(item for item in report["references"] if item["name"] == "MiroFish")
    assert mirofish["ready"] is True
    assert mirofish["product_standard_covered"] is True
    assert mirofish["product_standard_reason"] == "runtime_behavior"
    assert mirofish["claim_level"] == "runtime_with_compliance_warning"
    assert mirofish["gap_type"] == ""
    assert "src/council/council-runner.py" in mirofish["code_paths"]
    assert "tests/test_mirofish_runtime.py" in mirofish["test_paths"]
    insight_forge = next(item for item in report["references"] if item["name"] == "InsightForge")
    assert insight_forge["ready"] is True
    assert insight_forge["claim_level"] == "runtime_with_compliance_warning"
    assert insight_forge["gap_type"] == ""
    react = next(item for item in report["references"] if item["name"] == "ReACT 보고서 작성 패턴")
    assert react["ready"] is True
    assert react["claim_level"] == "runtime_ready"
    assert react["source_url"] == "https://react-lm.github.io"
    assert "tests/test_react_report_executor.py" in react["test_paths"]
    wiki = next(item for item in report["references"] if item["name"] == "Karpathy LLM Wiki Pattern")
    assert wiki["ready"] is True
    assert wiki["claim_level"] == "runtime_ready"
    assert "src/wiki/governance.py" in wiki["code_paths"]
    hachimi = next(item for item in report["references"] if item["name"] == "HACHIMI")
    assert hachimi["license"] == "MIT"
    assert hachimi["source_url"] == "https://github.com/ZeroLoss-Lab/HACHIMI"
    assert "SimHash" in hachimi["implementation_notes"]
    map_elites = next(item for item in report["references"] if item["name"] == "MAP-Elites")
    assert map_elites["source_url"] == "https://github.com/EvoAgentX/EvoAgentX"


def test_reference_inventory_paths_exist_for_runtime_backed_items():
    report = reference_readiness_report()

    for item in report["references"]:
        if not item["implemented"]:
            continue
        assert item["present_paths"] == item["code_paths"], item["name"]


def test_reference_inventory_declared_tests_exist_for_runtime_backed_items():
    report = reference_readiness_report()

    for item in report["references"]:
        if not item["implemented"]:
            continue
        for test_path in item["test_paths"]:
            assert Path(test_path).exists(), f"{item['name']}: {test_path}"


def test_vendored_reference_projects_have_third_party_notices():
    notices = Path("THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    assert "## GPTaku show-me-the-prd" in notices
    assert "7b22b070a685115a8687ea95fb95d398e4daf043" in notices
    assert "third_party/show-me-the-prd/" in notices
    assert "## Plannotator" in notices
    assert "6324a0c859f06030b47d71c02b7c6fed09fa0b92" in notices
    assert "third_party/plannotator/" in notices
    assert "app/muchanipo-tauri/src/plannotator-port/" in notices


def test_provider_runtime_inventory_includes_opencode_adapter_and_tests():
    report = reference_readiness_report()
    provider_items = [
        item
        for item in report["references"]
        if item["name"] == "Claude, Gemini, Codex, Kimi, OpenCode CLI 제공자"
    ]

    assert provider_items
    provider_item = provider_items[0]
    assert "src/execution/providers/opencode.py" in provider_item["code_paths"]
    assert "tests/test_provider_opencode.py" in provider_item["test_paths"]
    assert provider_item["ready"] is True


def test_reference_inventory_does_not_mark_gap_items_ready():
    report = reference_readiness_report()

    for item in report["references"]:
        if item["gap"]:
            assert item["ready"] is False
            assert item["claim_level"] in {"implemented_with_gap", "concept_only"}
            assert item["gap_type"] in {
                "partial/minified behavior",
                "license/compliance blocked",
                "test-only claim",
                "",
            }
            if item["gap_type"] == "license/compliance blocked":
                assert item["product_standard_covered"] is True
                assert item["product_standard_reason"] == "explicit_license_boundary"
            else:
                assert item["product_standard_covered"] is False
                assert item["product_standard_reason"] in {"unresolved_gap", "not_runtime_claim"}
