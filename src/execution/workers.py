"""Worker orchestration placeholder."""
from __future__ import annotations

from .task import TaskResult, TaskSpec


def run_inline_task(task: TaskSpec) -> TaskResult:
    return TaskResult(text=task.prompt)
