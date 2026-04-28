"""Offline cost simulator for one research run."""

from __future__ import annotations

from typing import Any

from src.governance.budget import estimate_cost_usd


DEFAULT_RESEARCH_BUDGET_USD = 0.50


def simulate_research_cost(
    brief: str,
    num_rounds: int = 10,
    num_personas: int = 5,
    *,
    max_usd: float = DEFAULT_RESEARCH_BUDGET_USD,
) -> dict[str, Any]:
    """Estimate one end-to-end research run without making model calls.

    The assumptions mirror PRD §8.1 routing: Gemini Flash for intake,
    targeting, and web research planning; Kimi for evidence-heavy passes;
    Anthropic Sonnet for interview/report-style synthesis; Anthropic Opus for
    council deliberation.
    """

    rounds = max(int(num_rounds), 1)
    personas = max(int(num_personas), 1)
    brief_tokens = max(len(brief) // 4, 40)

    breakdown = {
        "intake": _cost("gemini-2.5-flash", brief_tokens + 80, 60),
        "interview": _cost("claude-sonnet-4-6", brief_tokens + 220, 260),
        "targeting": _cost("gemini-2.5-flash", brief_tokens + 140, 120),
        "research": rounds * (
            _cost("gemini-2.5-flash", brief_tokens + 180, 260)
            + _cost("kimi-k2-0711-preview", brief_tokens + 220, 260)
        ),
        "evidence": rounds * _cost("kimi-k2-0711-preview", brief_tokens + 180, 180),
        "council": rounds
        * personas
        * _cost("claude-opus-4-7", min(brief_tokens, 140) + 40, 110),
        "report": _cost("claude-sonnet-4-6", brief_tokens + 500, 900),
    }
    rounded = {stage: round(cost, 4) for stage, cost in breakdown.items()}
    total = round(sum(breakdown.values()), 4)
    return {
        "total_usd": total,
        "breakdown": rounded,
        "budget_ok": total <= float(max_usd),
        "max_usd": float(max_usd),
        "assumptions": {
            "brief_tokens": brief_tokens,
            "num_rounds": rounds,
            "num_personas": personas,
            "routing": {
                "intake": "gemini-2.5-flash",
                "interview": "claude-sonnet-4-6",
                "targeting": "gemini-2.5-flash",
                "research": ["gemini-2.5-flash", "kimi-k2-0711-preview"],
                "evidence": "kimi-k2-0711-preview",
                "council": "claude-opus-4-7",
                "report": "claude-sonnet-4-6",
            },
        },
    }


def _cost(model: str, input_tokens: int, output_tokens: int) -> float:
    return estimate_cost_usd(model, input_tokens, output_tokens)
