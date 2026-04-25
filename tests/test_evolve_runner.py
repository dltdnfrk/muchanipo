import pytest

from src.eval.evolve_runner import MAPElitesArchive, SEWOptimizer


def test_map_elites_keeps_best_candidate_per_behavior_cell():
    archive = MAPElitesArchive(["novelty", "cost"], bins=5)

    assert archive.add(
        {"id": "baseline", "proposal": {"actions": ["add_axis_note:novelty"]}},
        performance=0.62,
        behavior={"novelty": 0.22, "cost": 0.18},
    )
    assert not archive.add(
        {"id": "weaker", "proposal": {"actions": ["add_axis_note:novelty"]}},
        performance=0.4,
        behavior={"novelty": 0.21, "cost": 0.19},
    )
    assert archive.add(
        {"id": "stronger", "proposal": {"actions": ["add_axis_note:novelty"]}},
        performance=0.91,
        behavior={"novelty": 0.2, "cost": 0.19},
    )

    elites = archive.get_elites()
    assert len(elites) == 1
    assert elites[0].candidate["id"] == "stronger"
    assert elites[0].performance == 0.91


def test_map_elites_preserves_diverse_cells_and_reports_coverage():
    archive = MAPElitesArchive(["novelty"], bins=4)

    archive.add({"id": "low"}, 0.6, {"novelty": 0.1})
    archive.add({"id": "high"}, 0.5, {"novelty": 0.9})

    assert {elite.candidate["id"] for elite in archive.get_elites()} == {"low", "high"}
    assert archive.coverage() == 0.5


def test_map_elites_rejects_immutable_axis_evolution():
    archive = MAPElitesArchive(["novelty"])

    with pytest.raises(ValueError, match="immutable axis"):
        archive.add(
            {
                "id": "unsafe",
                "proposal": {
                    "changes": [
                        {"action": "modify_axis_weight", "axis": "citation_fidelity"}
                    ]
                },
            },
            performance=0.8,
            behavior={"novelty": 0.4},
        )


def test_sew_optimizer_balances_quality_and_diversity():
    archive = MAPElitesArchive(["novelty"], bins=10)
    archive.add({"id": "existing"}, 0.8, {"novelty": 0.1})

    optimizer = SEWOptimizer(quality_weight=0.4, diversity_weight=0.6)
    ranked = optimizer.rank(
        [
            {"id": "near", "performance": 0.95, "behavior": {"novelty": 0.12}},
            {"id": "far", "performance": 0.7, "behavior": {"novelty": 0.95}},
        ],
        archive,
    )

    assert ranked[0]["candidate"]["id"] == "far"
    assert optimizer.select([item["candidate"] for item in ranked], archive)[0]["id"] == "far"


def test_archive_validates_behavior_and_score_inputs():
    archive = MAPElitesArchive(["novelty"])

    with pytest.raises(ValueError, match="behavior missing dims"):
        archive.add({"id": "missing"}, 0.5, {})

    with pytest.raises(ValueError, match="performance"):
        archive.add({"id": "bad-score"}, 1.2, {"novelty": 0.5})
