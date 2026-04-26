"""Profile resolution for science-loop runs."""
from __future__ import annotations

import os


def resolve_profile(explicit: str | None = None, env: dict[str, str] | None = None) -> str:
    env_map = os.environ if env is None else env
    return explicit or env_map.get("MUCHANIPO_PROFILE") or "dev"
