"""DiversityMap (MAP-Elites 2D) 단위 테스트.

PRD-v2 §5.5 — risk_tolerance × innovation_orientation 2축 다양성 강제.
"""

from __future__ import annotations

import pytest

from src.council.diversity_mapper import DiversityMap, _as_float


# ---- bucketing ----------------------------------------------------------


def test_bucket_clamps_below_zero_to_first_cell():
    dmap = DiversityMap(bins_per_axis=4)
    coord = dmap.coord_for({"risk_tolerance": -0.3, "innovation_orientation": 0.0})
    assert coord == (0, 0)


def test_bucket_clamps_above_one_to_last_cell():
    dmap = DiversityMap(bins_per_axis=4)
    coord = dmap.coord_for({"risk_tolerance": 1.5, "innovation_orientation": 1.0})
    assert coord == (3, 3)


def test_bucket_quantizes_to_correct_bin():
    dmap = DiversityMap(bins_per_axis=4)
    # 0.0~0.25 -> bin 0, 0.25~0.50 -> bin 1, 0.50~0.75 -> bin 2, 0.75~1.0 -> bin 3
    assert dmap.coord_for({"risk_tolerance": 0.1, "innovation_orientation": 0.4}) == (0, 1)
    assert dmap.coord_for({"risk_tolerance": 0.6, "innovation_orientation": 0.9}) == (2, 3)


def test_default_axes_when_missing_use_midpoint():
    dmap = DiversityMap(bins_per_axis=4)
    coord = dmap.coord_for({})
    # 0.5 with bins=4 -> bucket 2
    assert coord == (2, 2)


# ---- admit / coverage ---------------------------------------------------


def test_admit_to_empty_cell_succeeds():
    dmap = DiversityMap(bins_per_axis=4)
    accepted = dmap.admit(
        "persona-001",
        {"risk_tolerance": 0.1, "innovation_orientation": 0.1},
        fitness=0.7,
    )
    assert accepted is True
    assert dmap.is_occupied({"risk_tolerance": 0.1, "innovation_orientation": 0.1})
    assert (0, 0) in dmap.occupied_coords()


def test_admit_with_lower_fitness_to_occupied_cell_rejected():
    dmap = DiversityMap(bins_per_axis=4)
    dmap.admit("persona-A", {"risk_tolerance": 0.1, "innovation_orientation": 0.1}, fitness=0.9)
    accepted = dmap.admit(
        "persona-B",
        {"risk_tolerance": 0.15, "innovation_orientation": 0.05},  # 같은 셀
        fitness=0.5,
    )
    assert accepted is False
    cell = dmap.cells[(0, 0)]
    assert cell.persona_id == "persona-A"


def test_admit_with_higher_fitness_replaces():
    dmap = DiversityMap(bins_per_axis=4)
    dmap.admit("persona-A", {"risk_tolerance": 0.1, "innovation_orientation": 0.1}, fitness=0.4)
    accepted = dmap.admit(
        "persona-B",
        {"risk_tolerance": 0.2, "innovation_orientation": 0.05},
        fitness=0.85,
    )
    assert accepted is True
    assert dmap.cells[(0, 0)].persona_id == "persona-B"


def test_admit_equal_fitness_does_not_replace():
    """결정성 보장 — 동일 fitness시 선등록자 유지."""
    dmap = DiversityMap(bins_per_axis=4)
    dmap.admit("persona-A", {"risk_tolerance": 0.1, "innovation_orientation": 0.1}, fitness=0.7)
    accepted = dmap.admit(
        "persona-B",
        {"risk_tolerance": 0.2, "innovation_orientation": 0.05},
        fitness=0.7,
    )
    assert accepted is False


# ---- coverage / free / redirect ----------------------------------------


def test_coverage_reflects_filled_cells():
    dmap = DiversityMap(bins_per_axis=4)  # 16 cells
    assert dmap.coverage() == 0.0

    dmap.admit("p1", {"risk_tolerance": 0.0, "innovation_orientation": 0.0})
    dmap.admit("p2", {"risk_tolerance": 1.0, "innovation_orientation": 1.0})
    dmap.admit("p3", {"risk_tolerance": 0.5, "innovation_orientation": 0.5})
    dmap.admit("p4", {"risk_tolerance": 0.0, "innovation_orientation": 1.0})

    assert dmap.coverage() == pytest.approx(4 / 16)
    assert len(dmap.free_coords()) == 12


def test_suggest_redirect_returns_axes_in_free_cell():
    dmap = DiversityMap(bins_per_axis=4)
    dmap.admit("p", {"risk_tolerance": 0.0, "innovation_orientation": 0.0})

    redirect = dmap.suggest_redirect()
    assert redirect is not None
    # 점유 안 된 셀 좌표가 추천돼야 함
    assert not dmap.is_occupied(redirect)


def test_suggest_redirect_returns_none_when_full():
    dmap = DiversityMap(bins_per_axis=2)  # 4 cells
    for i, (r, n) in enumerate([(0.0, 0.0), (0.0, 1.0), (1.0, 0.0), (1.0, 1.0)]):
        dmap.admit(f"p{i}", {"risk_tolerance": r, "innovation_orientation": n})
    assert dmap.coverage() == 1.0
    assert dmap.suggest_redirect() is None


# ---- serialization ------------------------------------------------------


def test_to_dict_includes_coords_and_coverage():
    dmap = DiversityMap(bins_per_axis=4)
    dmap.admit("p1", {"risk_tolerance": 0.1, "innovation_orientation": 0.9}, fitness=0.8)

    snap = dmap.to_dict()
    assert snap["bins_per_axis"] == 4
    assert snap["coverage"] == pytest.approx(1 / 16)
    assert len(snap["cells"]) == 1
    cell = snap["cells"][0]
    assert cell["persona_id"] == "p1"
    assert cell["coord"] == [0, 3]


# ---- helper -------------------------------------------------------------


def test_invalid_bins_per_axis_raises():
    with pytest.raises(ValueError):
        DiversityMap(bins_per_axis=1)


def test_as_float_helper_handles_garbage():
    assert _as_float(None, default=0.5) == 0.5
    assert _as_float("not-a-number", default=0.3) == 0.3
    assert _as_float("0.7") == 0.7
    assert _as_float(True) == 1.0  # bool은 int 호환
