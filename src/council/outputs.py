"""Council output formatting."""
from __future__ import annotations

def next_actions_from_disagreements(disagreements: list[str]) -> list[str]:
    return [f"Investigate: {item}" for item in disagreements]
