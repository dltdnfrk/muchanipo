"""Tests for depth-aware cost simulation (Council Blocker 4 fix)."""
from __future__ import annotations

import pytest

from src.governance.cost_simulator import simulate_research_cost
from src.research.depth import ResearchDepthProfile


def test_cost_simulator_uses_depth_profile_budgets() -> None:
    shallow = simulate_research_cost("딸기 진단키트", depth="shallow")
    deep = simulate_research_cost("딸기 진단키트", depth="deep")
    max_ = simulate_research_cost("딸기 진단키트", depth="max")

    # Shallow has fewer queries and rounds -> lower research & council cost
    assert shallow["depth"] == "shallow"
    assert deep["depth"] == "deep"
    assert max_["depth"] == "max"

    assert shallow["depth_profile"]["query_limit"] == 4
    assert deep["depth_profile"]["query_limit"] == 8
    assert max_["depth_profile"]["query_limit"] == 12

    assert shallow["depth_profile"]["council_round_budget"] == 6
    assert deep["depth_profile"]["council_round_budget"] == 10
    assert max_["depth_profile"]["council_round_budget"] == 10
    assert shallow["depth_profile"]["persona_pool_size"] == 24
    assert deep["depth_profile"]["persona_pool_size"] == 80
    assert max_["depth_profile"]["persona_pool_size"] == 160
    assert shallow["depth_profile"]["active_persona_count"] == 6
    assert deep["depth_profile"]["active_persona_count"] == 10
    assert max_["depth_profile"]["active_persona_count"] == 16

    assert shallow["depth_profile"]["extended_test_time_compute"] is False
    assert max_["depth_profile"]["extended_test_time_compute"] is True
    assert shallow["autoresearch_runtime"]["execution_mode"] == "inline_local"
    assert max_["autoresearch_runtime"]["execution_mode"] == "background_async_max"
    assert max_["autoresearch_runtime"]["async_background"] is True
    assert max_["autoresearch_runtime"]["hitl_plan_gate_enforced"] is True
    assert max_["autoresearch_runtime"]["observed_max_usage"]["total_tokens"] == 699_116
    assert max_["autoresearch_runtime"]["observed_max_usage"]["total_tool_use_tokens"] == 618_481
    assert "total_tool_use_tokens" in max_["assumptions"]["usage_ledger_fields"]
    assert "total_thought_tokens" in max_["assumptions"]["usage_ledger_fields"]

    # Research cost scales with query_limit
    assert shallow["breakdown"]["research"] < deep["breakdown"]["research"]
    assert deep["breakdown"]["research"] < max_["breakdown"]["research"]

    # Council cost scales by active speaker count as well as round budget.
    assert shallow["breakdown"]["council"] < deep["breakdown"]["council"]
    assert deep["breakdown"]["council"] < max_["breakdown"]["council"]
    assert deep["assumptions"]["query_limit"] == 8
    assert deep["assumptions"]["persona_pool_size"] == 80


def test_cost_simulator_explicit_num_rounds_overrides_depth() -> None:
    # When num_rounds is explicitly given, it should still work
    result = simulate_research_cost("topic", num_rounds=3, depth="deep")
    assert result["assumptions"]["num_rounds"] == 3
    assert result["assumptions"]["query_limit"] == 8
    assert result["depth"] == "deep"


def test_cost_simulator_rejects_nonpositive_num_rounds() -> None:
    with pytest.raises(ValueError, match="num_rounds must be >= 1"):
        simulate_research_cost("topic", num_rounds=0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("query_limit", 0),
        ("council_round_budget", 0),
        ("persona_pool_size", 0),
        ("active_persona_count", 0),
        ("target_runtime_seconds", 0),
    ],
)
def test_research_depth_profile_rejects_nonpositive_budgets(field: str, value: int) -> None:
    kwargs = {
        "name": "bad",
        "query_limit": 1,
        "council_round_budget": 1,
        "persona_pool_size": 1,
        "active_persona_count": 1,
        "target_runtime_seconds": 1,
        "extended_test_time_compute": False,
        "description": "invalid profile",
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match=f"{field} must be >= 1"):
        ResearchDepthProfile(**kwargs)


def test_research_depth_profile_rejects_active_count_above_pool() -> None:
    with pytest.raises(ValueError, match="active_persona_count must be <= persona_pool_size"):
        ResearchDepthProfile(
            name="bad",
            query_limit=1,
            council_round_budget=1,
            persona_pool_size=2,
            active_persona_count=3,
            target_runtime_seconds=1,
            extended_test_time_compute=False,
            description="invalid profile",
        )


def test_research_depth_profile_rejects_blank_name() -> None:
    with pytest.raises(ValueError, match="name must not be empty"):
        ResearchDepthProfile(
            name=" ",
            query_limit=1,
            council_round_budget=1,
            persona_pool_size=1,
            active_persona_count=1,
            target_runtime_seconds=1,
            extended_test_time_compute=False,
            description="invalid profile",
        )
