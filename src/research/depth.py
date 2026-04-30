"""Depth profiles for Muchanipo autoresearch runs."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchDepthProfile:
    name: str
    query_limit: int
    council_round_budget: int
    target_runtime_seconds: int
    extended_test_time_compute: bool
    description: str


DEPTH_PROFILES: dict[str, ResearchDepthProfile] = {
    "shallow": ResearchDepthProfile(
        name="shallow",
        query_limit=4,
        council_round_budget=6,
        target_runtime_seconds=120,
        extended_test_time_compute=False,
        description="Quick interactive autoresearch pass for 30s-2m answers.",
    ),
    "deep": ResearchDepthProfile(
        name="deep",
        query_limit=8,
        council_round_budget=10,
        target_runtime_seconds=900,
        extended_test_time_compute=False,
        description="Default six-stage Muchanipo research depth.",
    ),
    "max": ResearchDepthProfile(
        name="max",
        query_limit=12,
        council_round_budget=10,
        target_runtime_seconds=3600,
        extended_test_time_compute=True,
        description="Comprehensive background pass with extended test-time compute metadata.",
    ),
}

VALID_DEPTHS: tuple[str, ...] = tuple(DEPTH_PROFILES)


def normalize_depth(depth: str | None) -> str:
    value = (depth or "deep").strip().lower()
    if value not in DEPTH_PROFILES:
        valid = "|".join(VALID_DEPTHS)
        raise ValueError(f"depth must be one of: {valid}")
    return value


def depth_profile(depth: str | None) -> ResearchDepthProfile:
    return DEPTH_PROFILES[normalize_depth(depth)]
