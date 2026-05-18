import json
from pathlib import Path

import pytest

from src.muchanipo import terminal as terminal_mod
from src.pipeline.goals_stages import (
    CANONICAL_GOALS_STAGES,
    INTERNAL_SUBSTEP_TO_CANONICAL_STAGE_MAP,
    LEGACY_TO_CANONICAL_STAGE_MAP,
    PUBLIC_GOALS_STAGE_IDS,
    goals_stage_by_id,
    goals_stage_contract_report,
    normalize_public_stage,
    public_stage_for_internal_substep,
    public_stage_for_legacy,
)
from src.pipeline.reference_inventory import reference_readiness_report
from src.pipeline.stages import Stage


EXPECTED_PUBLIC_STAGE_IDS = (
    "idea_dump",
    "deep_interview",
    "deep_research_max",
    "plannotator_review",
    "ontology_extraction",
    "persona_generation",
    "llm_council",
    "final_report_html_yaml",
)


def test_public_goals_stage_ids_are_exact_and_ordered():
    assert PUBLIC_GOALS_STAGE_IDS == EXPECTED_PUBLIC_STAGE_IDS
    assert tuple(stage.stage_id for stage in CANONICAL_GOALS_STAGES) == EXPECTED_PUBLIC_STAGE_IDS
    assert tuple(stage.order for stage in CANONICAL_GOALS_STAGES) == tuple(range(1, 9))

    for stage in CANONICAL_GOALS_STAGES:
        assert stage.label_en
        assert stage.label_ko
        assert stage.purpose
        assert goals_stage_by_id(stage.stage_id) == stage


def test_legacy_stage_mapping_is_explicit_and_public_only():
    assert LEGACY_TO_CANONICAL_STAGE_MAP == {
        "idea_dump": "idea_dump",
        "intake": "idea_dump",
        "interview": "deep_interview",
        "targeting": "deep_research_max",
        "research": "deep_research_max",
        "evidence": "deep_research_max",
        "council": "llm_council",
        "report": "final_report_html_yaml",
        "vault": "final_report_html_yaml",
        "agents": "persona_generation",
        "done": "final_report_html_yaml",
        "finalize": "final_report_html_yaml",
    }

    assert public_stage_for_legacy(Stage.RESEARCH) == "deep_research_max"
    assert public_stage_for_legacy("intake") == "idea_dump"
    assert normalize_public_stage("finalize") == "final_report_html_yaml"
    assert set(LEGACY_TO_CANONICAL_STAGE_MAP.values()) <= set(PUBLIC_GOALS_STAGE_IDS)


def test_internal_substep_mapping_covers_canonical_stages_without_public_aliases():
    assert public_stage_for_internal_substep("hitl_gate") == "plannotator_review"
    assert public_stage_for_internal_substep("ontology_state") == "ontology_extraction"
    assert public_stage_for_internal_substep("persona_admission") == "persona_generation"
    assert public_stage_for_internal_substep("critique_to_action") == "llm_council"
    assert normalize_public_stage("final_report") == "final_report_html_yaml"

    mapped = set(LEGACY_TO_CANONICAL_STAGE_MAP.values()) | set(
        INTERNAL_SUBSTEP_TO_CANONICAL_STAGE_MAP.values()
    )
    assert mapped == set(PUBLIC_GOALS_STAGE_IDS)


def test_stage_contract_report_is_serializable_and_exposed_on_existing_surfaces():
    contract = goals_stage_contract_report()
    assert contract["schema_version"] == 1
    assert contract["stage_ids"] == list(EXPECTED_PUBLIC_STAGE_IDS)
    assert [stage["stage_id"] for stage in contract["stages"]] == list(EXPECTED_PUBLIC_STAGE_IDS)
    assert contract["legacy_stage_map"]["research"] == "deep_research_max"

    contracts_report = terminal_mod.json_contracts_report()
    assert contracts_report["goals_stage_contract"] == contract

    references_report = reference_readiness_report(repo_root=Path.cwd())
    assert references_report["goals_stage_contract"] == contract


def test_unknown_stage_names_fail_closed():
    with pytest.raises(KeyError):
        goals_stage_by_id("research")
    with pytest.raises(KeyError):
        public_stage_for_legacy("unknown_legacy_stage")
    with pytest.raises(KeyError):
        public_stage_for_internal_substep("unknown_substep")


def test_public_contract_does_not_embed_fixture_topic_terms():
    payload = json.dumps(goals_stage_contract_report(), ensure_ascii=False).lower()
    forbidden_terms = (
        "b-1",
        "b1",
        "strawberry",
        "딸기",
        "erwinia",
        "amylovora",
        "fire blight",
    )
    assert not any(term in payload for term in forbidden_terms)
