"""Serializable pipeline state for resumable Idea-to-Council runs."""
from __future__ import annotations

from dataclasses import dataclass, field

from .stages import Stage


@dataclass
class PipelineState:
    run_id: str
    stage: Stage = Stage.IDEA_DUMP
    artifacts: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def advance(self, next_stage: Stage) -> "PipelineState":
        self.stage = next_stage
        return self

    def record_artifact(self, key: str, artifact_id: str) -> None:
        if not key.strip():
            raise ValueError("artifact key must not be empty")
        self.artifacts[key] = artifact_id
