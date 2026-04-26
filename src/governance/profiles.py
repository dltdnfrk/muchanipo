"""Environment profile resolution for execution governance."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class GovernanceProfile:
    name: str
    budget_limit_usd: float
    default_provider: str
    stage_routes: dict[str, str]
    allow_real_providers: bool


PROFILES: dict[str, GovernanceProfile] = {
    "dev": GovernanceProfile(
        name="dev",
        budget_limit_usd=1.0,
        default_provider="mock",
        stage_routes={"interview": "mock", "research": "mock", "council": "mock", "report": "mock"},
        allow_real_providers=False,
    ),
    "staging": GovernanceProfile(
        name="staging",
        budget_limit_usd=10.0,
        default_provider="openai",
        stage_routes={"interview": "openai", "research": "openai", "council": "anthropic", "report": "openai"},
        allow_real_providers=True,
    ),
    "prod": GovernanceProfile(
        name="prod",
        budget_limit_usd=50.0,
        default_provider="anthropic",
        stage_routes={"interview": "openai", "research": "openai", "council": "anthropic", "report": "anthropic"},
        allow_real_providers=True,
    ),
}


def resolve_profile(name: str | None = None) -> GovernanceProfile:
    selected = (os.environ.get("MUCHANIPO_PROFILE") or name or "dev").strip().lower()
    try:
        return PROFILES[selected]
    except KeyError as exc:
        raise ValueError(f"unknown MUCHANIPO_PROFILE: {selected}") from exc
