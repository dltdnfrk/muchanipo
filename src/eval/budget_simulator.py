"""Markdown budget report for council routing versus a single Opus pass."""

from __future__ import annotations

import argparse
from typing import Any

from src.governance.budget import estimate_cost_usd
from src.governance.cost_simulator import simulate_research_cost


def compare_council_vs_single_opus(
    brief: str,
    *,
    num_rounds: int = 10,
    num_personas: int = 5,
    max_usd: float = 0.50,
) -> dict[str, Any]:
    council = simulate_research_cost(
        brief,
        num_rounds=num_rounds,
        num_personas=num_personas,
        max_usd=max_usd,
    )
    brief_tokens = council["assumptions"]["brief_tokens"]
    single_opus_cost = estimate_cost_usd(
        "claude-opus-4-7",
        input_tokens=brief_tokens + (num_rounds * 180) + 400,
        output_tokens=1800,
    )
    return {
        "council": council,
        "single_opus": {
            "total_usd": round(single_opus_cost, 4),
            "budget_ok": single_opus_cost <= max_usd,
            "model": "claude-opus-4-7",
        },
        "max_usd": max_usd,
    }


def render_markdown_report(
    brief: str,
    *,
    num_rounds: int = 10,
    num_personas: int = 5,
    max_usd: float = 0.50,
) -> str:
    comparison = compare_council_vs_single_opus(
        brief,
        num_rounds=num_rounds,
        num_personas=num_personas,
        max_usd=max_usd,
    )
    council = comparison["council"]
    single = comparison["single_opus"]
    lines = [
        "# Budget Simulation",
        "",
        f"- Budget cap: ${max_usd:.2f}",
        f"- Rounds: {num_rounds}",
        f"- Personas: {num_personas}",
        "",
        "| Configuration | Estimated cost | Budget OK |",
        "| --- | ---: | :---: |",
        f"| Council routing | ${council['total_usd']:.4f} | {_yes_no(council['budget_ok'])} |",
        f"| Single Opus | ${single['total_usd']:.4f} | {_yes_no(single['budget_ok'])} |",
        "",
        "## Council Breakdown",
        "",
        "| Stage | Estimated cost |",
        "| --- | ---: |",
    ]
    for stage, cost in council["breakdown"].items():
        lines.append(f"| {stage} | ${cost:.4f} |")
    lines.extend(
        [
            "",
            "## Brief",
            "",
            brief.strip() or "(empty brief)",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brief", nargs="?", default="Korea agtech market entry research")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--personas", type=int, default=5)
    parser.add_argument("--max-usd", type=float, default=0.50)
    args = parser.parse_args(argv)
    print(
        render_markdown_report(
            args.brief,
            num_rounds=args.rounds,
            num_personas=args.personas,
            max_usd=args.max_usd,
        ),
        end="",
    )
    return 0


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


if __name__ == "__main__":
    raise SystemExit(main())
