"""Council round data helpers."""
from __future__ import annotations

def round_index(rounds: list[dict]) -> int:
    return len(rounds) + 1
