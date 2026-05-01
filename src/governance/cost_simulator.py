"""Offline cost simulator for one research run."""

from __future__ import annotations

from typing import Any

from src.governance.budget import estimate_cost_usd
from src.research.autoresearch_runtime import runtime_contract_for_profile
from src.research.depth import depth_profile


DEFAULT_RESEARCH_BUDGET_USD = 0.50


def simulate_research_cost(
    brief: str,
    num_rounds: int | None = None,
    num_personas: int | None = None,
    *,
    max_usd: float = DEFAULT_RESEARCH_BUDGET_USD,
    depth: str = "deep",
) -> dict[str, Any]:
    """Estimate one end-to-end research run without making model calls.

    The assumptions mirror PRD §8.1 routing: Gemini Flash for intake,
    targeting, and web research planning; Kimi for evidence-heavy passes;
    Anthropic Sonnet for interview/report-style synthesis; Anthropic Opus for
    council deliberation.

    When ``depth`` is provided, query_limit and council_round_budget are
    taken from the depth profile so that shallow/deep/max produce distinct
    cost estimates. ``num_rounds`` only overrides the council round count;
    research/evidence query counts still come from the depth profile unless
    a future explicit num_queries override is added.
    """

    profile = depth_profile(depth)
    runtime_contract = runtime_contract_for_profile(profile)
    # Use depth profile budgets unless caller explicitly overrides rounds.
    if num_rounds is not None and int(num_rounds) < 1:
        raise ValueError("num_rounds must be >= 1")
    rounds = int(num_rounds) if num_rounds is not None else profile.council_round_budget
    queries = profile.query_limit
    personas = max(int(num_personas), 1) if num_personas is not None else profile.active_persona_count
    brief_tokens = max(len(brief) // 4, 40)

    breakdown = {
        "intake": _cost("gemini-2.5-flash", brief_tokens + 80, 60),
        "interview": _cost("claude-sonnet-4-6", brief_tokens + 220, 260),
        "targeting": _cost("gemini-2.5-flash", brief_tokens + 140, 120),
        "research": queries * (
            _cost("gemini-2.5-flash", brief_tokens + 180, 260)
            + _cost("kimi-k2-0711-preview", brief_tokens + 220, 260)
        ),
        "evidence": queries * _cost("kimi-k2-0711-preview", brief_tokens + 180, 180),
        "council": rounds
        * personas
        * _cost("claude-opus-4-7", min(brief_tokens, 140) + 40, 50),
        "report": _cost("claude-sonnet-4-6", brief_tokens + 500, 900),
    }
    rounded = {stage: round(cost, 4) for stage, cost in breakdown.items()}
    total = round(sum(breakdown.values()), 4)
    return {
        "total_usd": total,
        "breakdown": rounded,
        "budget_ok": total <= float(max_usd),
        "max_usd": float(max_usd),
        "depth": profile.name,
        "depth_profile": {
            "query_limit": profile.query_limit,
            "council_round_budget": profile.council_round_budget,
            "persona_pool_size": profile.persona_pool_size,
            "active_persona_count": profile.active_persona_count,
            "target_runtime_seconds": profile.target_runtime_seconds,
            "extended_test_time_compute": profile.extended_test_time_compute,
        },
        "autoresearch_runtime": runtime_contract.to_dict(),
        "assumptions": {
            "brief_tokens": brief_tokens,
            "query_limit": queries,
            "num_rounds": rounds,
            "num_personas": personas,
            "persona_pool_size": profile.persona_pool_size,
            "active_persona_count": personas,
            "routing": {
                "intake": "gemini-2.5-flash",
                "interview": "claude-sonnet-4-6",
                "targeting": "gemini-2.5-flash",
                "research": ["gemini-2.5-flash", "kimi-k2-0711-preview"],
                "evidence": "kimi-k2-0711-preview",
                "council": "claude-opus-4-7",
                "report": "claude-sonnet-4-6",
            },
            "council_turn_output_tokens": 50,
            "usage_ledger_fields": list(runtime_contract.usage_ledger_fields),
        },
    }


def _cost(model: str, input_tokens: int, output_tokens: int) -> float:
    return estimate_cost_usd(model, input_tokens, output_tokens)
