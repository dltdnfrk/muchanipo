"""Task contracts for future worker orchestration."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TaskSpec:
    stage: str
    prompt: str


@dataclass
class TaskResult:
    text: str
    ok: bool = True
