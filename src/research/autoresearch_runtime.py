"""Runtime contracts for Deep Research Max-style autoresearch.

This module does not clone Google's private implementation. It captures the
public/observed runtime shape that Muchanipo can enforce locally: async job
state, phase summaries, resumable stream cursors, stale-job guards, and a
token ledger that includes tool-use and thought tokens.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from src.research.depth import ResearchDepthProfile


MAX_OBSERVED_PHASES: tuple[str, ...] = (
    "Broadening the Investigation",
    "Synthesizing the Analysis",
    "Bringing It All Together",
    "Adding Finishing Touches",
)

MAX_STREAM_EVENT_TYPES: tuple[str, ...] = (
    "interaction.start",
    "interaction.status_update",
    "content.start",
    "content.delta:thought_summary",
    "interaction.complete",
)

USAGE_LEDGER_FIELDS: tuple[str, ...] = (
    "total_tokens",
    "total_input_tokens",
    "total_output_tokens",
    "total_tool_use_tokens",
    "total_thought_tokens",
)


@dataclass(frozen=True)
class TokenUsageLedger:
    """Provider-neutral token ledger for agentic research jobs."""

    total_tokens: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tool_use_tokens: int = 0
    total_thought_tokens: int = 0

    def __post_init__(self) -> None:
        for field_name in USAGE_LEDGER_FIELDS:
            if int(getattr(self, field_name)) < 0:
                raise ValueError(f"{field_name} must be >= 0")

    @classmethod
    def from_interactions_usage(cls, usage: dict[str, Any] | None) -> "TokenUsageLedger":
        usage = usage or {}
        return cls(
            total_tokens=_int_usage(usage, "total_tokens"),
            total_input_tokens=_int_usage(usage, "total_input_tokens"),
            total_output_tokens=_int_usage(usage, "total_output_tokens"),
            total_tool_use_tokens=_int_usage(usage, "total_tool_use_tokens"),
            total_thought_tokens=_int_usage(usage, "total_thought_tokens"),
        )

    def to_dict(self) -> dict[str, int]:
        return {field_name: int(getattr(self, field_name)) for field_name in USAGE_LEDGER_FIELDS}


@dataclass(frozen=True)
class AutoresearchRuntimeContract:
    """Depth-specific runtime behavior that must be visible in artifacts."""

    depth: str
    execution_mode: str
    async_background: bool
    hitl_plan_gate_enforced: bool
    phase_summaries: tuple[str, ...]
    stream_event_types: tuple[str, ...]
    usage_ledger_fields: tuple[str, ...]
    stale_after_seconds: int
    client_timeout_seconds: int
    observed_max_usage: TokenUsageLedger | None = None

    def phase_trace_template(self) -> list[dict[str, Any]]:
        return [
            {
                "index": idx,
                "phase": phase,
                "status": "pending",
                "source": "deep_research_max_observation"
                if self.async_background
                else "muchanipo_local_runtime",
            }
            for idx, phase in enumerate(self.phase_summaries, start=1)
        ]

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "depth": self.depth,
            "execution_mode": self.execution_mode,
            "async_background": self.async_background,
            "hitl_plan_gate_enforced": self.hitl_plan_gate_enforced,
            "phase_summaries": list(self.phase_summaries),
            "stream_event_types": list(self.stream_event_types),
            "usage_ledger_fields": list(self.usage_ledger_fields),
            "stale_after_seconds": self.stale_after_seconds,
            "client_timeout_seconds": self.client_timeout_seconds,
        }
        if self.observed_max_usage is not None:
            payload["observed_max_usage"] = self.observed_max_usage.to_dict()
        return payload


OBSERVED_DEEP_RESEARCH_MAX_USAGE = TokenUsageLedger(
    total_tokens=699_116,
    total_input_tokens=0,
    total_output_tokens=16_222,
    total_tool_use_tokens=618_481,
    total_thought_tokens=64_413,
)


def runtime_contract_for_profile(profile: ResearchDepthProfile) -> AutoresearchRuntimeContract:
    """Return the runtime contract enforced for a research depth profile."""

    if profile.extended_test_time_compute:
        return AutoresearchRuntimeContract(
            depth=profile.name,
            execution_mode="background_async_max",
            async_background=True,
            hitl_plan_gate_enforced=True,
            phase_summaries=MAX_OBSERVED_PHASES,
            stream_event_types=MAX_STREAM_EVENT_TYPES,
            usage_ledger_fields=USAGE_LEDGER_FIELDS,
            stale_after_seconds=180,
            client_timeout_seconds=profile.target_runtime_seconds,
            observed_max_usage=OBSERVED_DEEP_RESEARCH_MAX_USAGE,
        )
    return AutoresearchRuntimeContract(
        depth=profile.name,
        execution_mode="inline_local",
        async_background=False,
        hitl_plan_gate_enforced=True,
        phase_summaries=(
            "Plan Review",
            "Search and Read",
            "Evidence Grounding",
            "Council Synthesis",
            "Report Finalization",
        ),
        stream_event_types=(
            "stage_started",
            "stage_completed",
            "warning",
            "complete",
        ),
        usage_ledger_fields=USAGE_LEDGER_FIELDS,
        stale_after_seconds=max(30, min(profile.target_runtime_seconds, 180)),
        client_timeout_seconds=profile.target_runtime_seconds,
    )


def interaction_is_stale(
    *,
    status: str,
    updated_at: datetime,
    now: datetime | None = None,
    stale_after_seconds: int,
) -> bool:
    """Return true when an async interaction has not advanced recently."""

    if status != "in_progress":
        return False
    now = now or datetime.now(timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return (now - updated_at).total_seconds() >= stale_after_seconds


def normalize_phase_summaries(values: Iterable[str]) -> tuple[str, ...]:
    phases = tuple(value.strip() for value in values if value and value.strip())
    return phases or ("Unspecified Research Phase",)


def _int_usage(usage: dict[str, Any], key: str) -> int:
    try:
        return max(0, int(usage.get(key) or 0))
    except (TypeError, ValueError):
        return 0
