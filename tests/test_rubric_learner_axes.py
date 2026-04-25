import json

from conftest import load_script_module


rubric_learner = load_script_module("rubric_learner", "src/eval/rubric-learner.py")


def test_axes_tuple_has_expected_11_axes():
    assert rubric_learner.AXES == (
        "usefulness",
        "reliability",
        "novelty",
        "actionability",
        "completeness",
        "evidence_quality",
        "perspective_diversity",
        "coherence",
        "depth",
        "impact",
        "citation_fidelity",
    )


def test_config_rubric_declares_same_axes(repo_root):
    with open(repo_root / "config/rubric.json", "r", encoding="utf-8") as f:
        rubric = json.load(f)

    assert tuple(rubric["axes"].keys()) == rubric_learner.AXES
    assert rubric["version"] == "2.1.0"


def test_citation_fidelity_penalizes_unsupported_critical_claim(repo_root):
    with open(repo_root / "config/rubric.json", "r", encoding="utf-8") as f:
        rubric = json.load(f)

    matching_rules = [
        rule
        for rule in rubric["bonus_rules"]
        if rule["condition"] == "unsupported_critical_claim_count > 0"
    ]

    assert matching_rules == [
        {
            "condition": "unsupported_critical_claim_count > 0",
            "axis": "citation_fidelity",
            "bonus": -3,
        }
    ]
