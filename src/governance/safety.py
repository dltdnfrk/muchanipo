"""Safety policy placeholder for pipeline wiring."""
from __future__ import annotations

def allow_stage(stage: str) -> bool:
    return bool(stage)
