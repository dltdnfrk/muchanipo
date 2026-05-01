from datetime import datetime, timedelta, timezone

import pytest

from src.research.autoresearch_runtime import (
    OBSERVED_DEEP_RESEARCH_MAX_USAGE,
    TokenUsageLedger,
    interaction_is_stale,
    runtime_contract_for_profile,
)
from src.research.depth import depth_profile


def test_max_runtime_contract_exposes_async_trace_and_usage_ledger() -> None:
    contract = runtime_contract_for_profile(depth_profile("max"))

    assert contract.execution_mode == "background_async_max"
    assert contract.async_background is True
    assert contract.hitl_plan_gate_enforced is True
    assert contract.observed_max_usage == OBSERVED_DEEP_RESEARCH_MAX_USAGE
    assert "content.delta:thought_summary" in contract.stream_event_types
    assert "total_tool_use_tokens" in contract.usage_ledger_fields
    assert "total_thought_tokens" in contract.usage_ledger_fields
    assert contract.phase_trace_template()[0]["phase"] == "Broadening the Investigation"


def test_inline_runtime_contract_still_requires_state_gate() -> None:
    contract = runtime_contract_for_profile(depth_profile("shallow"))

    assert contract.execution_mode == "inline_local"
    assert contract.async_background is False
    assert contract.hitl_plan_gate_enforced is True
    assert contract.observed_max_usage is None
    assert contract.phase_trace_template()[0]["source"] == "muchanipo_local_runtime"


def test_usage_ledger_parses_interactions_usage_and_ignores_bad_values() -> None:
    ledger = TokenUsageLedger.from_interactions_usage(
        {
            "total_tokens": "699116",
            "total_input_tokens": None,
            "total_output_tokens": 16222,
            "total_tool_use_tokens": 618481,
            "total_thought_tokens": "bad",
        }
    )

    assert ledger.to_dict() == {
        "total_tokens": 699_116,
        "total_input_tokens": 0,
        "total_output_tokens": 16_222,
        "total_tool_use_tokens": 618_481,
        "total_thought_tokens": 0,
    }


def test_usage_ledger_rejects_negative_values() -> None:
    with pytest.raises(ValueError, match="total_tokens must be >= 0"):
        TokenUsageLedger(total_tokens=-1)


def test_interaction_stale_detection_only_applies_in_progress() -> None:
    now = datetime(2026, 5, 1, 0, 10, tzinfo=timezone.utc)
    old = now - timedelta(seconds=181)

    assert interaction_is_stale(
        status="in_progress",
        updated_at=old,
        now=now,
        stale_after_seconds=180,
    )
    assert not interaction_is_stale(
        status="completed",
        updated_at=old,
        now=now,
        stale_after_seconds=180,
    )
