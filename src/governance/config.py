"""Configuration placeholders for governance plane."""
from __future__ import annotations

def default_run_budget(profile: str) -> float:
    return 50.0 if profile == "prod" else 5.0
