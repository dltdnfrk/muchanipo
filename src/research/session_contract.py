"""Hermetic research-session contract for Muchanipo runs."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence
from uuid import uuid4


DEFAULT_MEMORY_POLICY = "no_implicit_cross_session_memory"


@dataclass(frozen=True)
class ResearchContract:
    """Run-scoped identity and memory/import policy.

    A contract is created per research session. Cross-session memory stays off
    by default; imported knowledge is empty unless a caller explicitly passes
    named refs with provenance.
    """

    research_session_id: str
    topic: str
    app_run_id: str = ""
    memory_policy: str = DEFAULT_MEMORY_POLICY
    imported_knowledge_refs: tuple[str, ...] = field(default_factory=tuple)
    benchmark_fixture_id: str | None = None

    def __post_init__(self) -> None:
        if not self.research_session_id.strip():
            raise ValueError("research_session_id must not be empty")
        if not self.topic.strip():
            raise ValueError("topic must not be empty")
        if not self.memory_policy.strip():
            raise ValueError("memory_policy must not be empty")

    @classmethod
    def new(
        cls,
        *,
        topic: str,
        app_run_id: str = "",
        memory_policy: str = DEFAULT_MEMORY_POLICY,
        imported_knowledge_refs: Sequence[str] | None = None,
        benchmark_fixture_id: str | None = None,
    ) -> "ResearchContract":
        return cls(
            research_session_id=f"research-{uuid4().hex}",
            topic=topic,
            app_run_id=app_run_id,
            memory_policy=memory_policy,
            imported_knowledge_refs=tuple(imported_knowledge_refs or ()),
            benchmark_fixture_id=benchmark_fixture_id,
        )

    def to_event_fields(self) -> dict[str, Any]:
        return {
            "research_session_id": self.research_session_id,
            "app_run_id": self.app_run_id,
            "memory_policy": self.memory_policy,
            "imported_knowledge_refs": list(self.imported_knowledge_refs),
        }

    def to_artifacts(self) -> dict[str, str]:
        artifacts = {
            "research_session_id": self.research_session_id,
            "app_run_id": self.app_run_id,
            "memory_policy": self.memory_policy,
            "imported_knowledge_refs": json.dumps(list(self.imported_knowledge_refs), ensure_ascii=False),
        }
        if self.benchmark_fixture_id is not None:
            artifacts["benchmark_fixture_id"] = self.benchmark_fixture_id
        return artifacts


def scope_event(event: Mapping[str, Any], contract: ResearchContract) -> dict[str, Any]:
    """Return event plus contract fields, rejecting stale cross-session identity."""

    scoped = dict(event)
    for key, value in contract.to_event_fields().items():
        if key in scoped and scoped[key] != value:
            raise ValueError(
                f"{key} mismatch: event has {scoped[key]!r}, "
                f"contract has {value!r}"
            )
        scoped[key] = value
    return scoped
