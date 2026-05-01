"""tmux/smux orchestration contracts for Muchanipo multi-agent work.

The downloaded orchestration prompt describes a window-0 operator hub and
worker windows 1-4. This module turns that into a machine-readable local
contract and a small tmux control surface. It deliberately protects window 0.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Sequence


PROTECTED_WINDOW_INDEX = 0
WORKER_WINDOW_INDICES: tuple[int, ...] = (1, 2, 3, 4)
WORKER_OWNERSHIP_MARKER_PREFIX = "muchanipo-worker:"


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess]


@dataclass(frozen=True)
class OperatorSpec:
    pane: str
    agent: str
    mode: str
    assigned_window: int
    role: str
    launch_command: str
    model_requirement: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pane": self.pane,
            "agent": self.agent,
            "mode": self.mode,
            "assigned_window": self.assigned_window,
            "role": self.role,
            "launch_command": self.launch_command,
            "ownership_marker": f"{WORKER_OWNERSHIP_MARKER_PREFIX}{self.agent}",
            "model_requirement": self.model_requirement,
        }


@dataclass(frozen=True)
class TmuxWindow:
    index: int
    name: str
    active: bool
    pane_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "active": self.active,
            "pane_count": self.pane_count,
        }


@dataclass(frozen=True)
class TmuxPane:
    target: str
    active: bool
    command: str
    title: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "active": self.active,
            "command": self.command,
            "title": self.title,
        }


@dataclass(frozen=True)
class CleanupAction:
    target: str
    action: str
    status: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {"target": self.target, "action": self.action, "status": self.status}
        if self.error:
            payload["error"] = self.error
        return payload


DEFAULT_OPERATORS: tuple[OperatorSpec, ...] = (
    OperatorSpec(
        pane="0.0",
        agent="claude",
        mode="OMC --dangerously-skip-permissions",
        assigned_window=1,
        role="architecture, core logic, code review",
        launch_command="claude --dangerously-skip-permissions",
    ),
    OperatorSpec(
        pane="0.1",
        agent="codex",
        mode="OMX --approval-mode full-auto",
        assigned_window=2,
        role="implementation, tests, CI/CD",
        launch_command="codex --approval-mode full-auto",
    ),
    OperatorSpec(
        pane="0.2",
        agent="kimi",
        mode="swarm",
        assigned_window=3,
        role="research, documentation, dependency analysis",
        launch_command="kimi",
    ),
    OperatorSpec(
        pane="0.3",
        agent="opencode",
        mode="OMO auto-approve",
        assigned_window=4,
        role="utilities, refactoring, linting",
        launch_command="opencode",
        model_requirement="Hephaestus - Deep Agent - GPT-5.5 only",
    ),
)

EXPECTED_WORKER_NAMES: dict[int, str] = {
    operator.assigned_window: operator.agent for operator in DEFAULT_OPERATORS
}


PHASES: tuple[dict[str, Any], ...] = (
    {
        "phase": 1,
        "name": "project inventory and environment",
        "operators": ["codex", "kimi"],
        "completion": ["package/runtime manifest present", "docs inventory present"],
    },
    {
        "phase": 2,
        "name": "core architecture",
        "operators": ["claude"],
        "completion": ["interfaces/contracts present", "operator rules documented"],
    },
    {
        "phase": 3,
        "name": "parallel core implementation",
        "operators": ["claude", "codex", "kimi", "opencode"],
        "completion": ["core modules implemented", "type/test checks pass"],
    },
    {
        "phase": 4,
        "name": "integration and tests",
        "operators": ["claude", "codex"],
        "completion": ["entrypoint works", "tests pass"],
    },
    {
        "phase": 5,
        "name": "quality and documentation",
        "operators": ["opencode", "kimi"],
        "completion": ["lint clean", "README/docs updated"],
    },
    {
        "phase": 6,
        "name": "build and release prep",
        "operators": ["codex"],
        "completion": ["build artifact created", "worker windows cleaned"],
    },
)


def orchestration_plan() -> dict[str, Any]:
    """Return the static operator/phase contract."""

    return {
        "protected_window": PROTECTED_WINDOW_INDEX,
        "worker_windows": list(WORKER_WINDOW_INDICES),
        "operators": [operator.to_dict() for operator in DEFAULT_OPERATORS],
        "phases": list(PHASES),
        "rules": [
            "window 0 is the operator hub and must never be killed by cleanup",
            "worker windows are 1-4 and may be removed after completion",
            "all delegated agents run YOLO/Ralph-style for assigned non-destructive work",
            "OpenCode must use Hephaestus - Deep Agent - GPT-5.5",
            "destructive cleanup requires --force and a worker pane title marker",
            "after tmux send-keys, submit with Enter and verify capture-pane output",
            "if a worker is silent for 30 seconds, send Enter; then C-c and restart if needed",
        ],
    }


class TmuxController:
    def __init__(
        self,
        *,
        session: str = "muni",
        runner: CommandRunner | None = None,
    ) -> None:
        self.session = session
        self.runner = runner or _run_tmux

    def list_windows(self) -> list[TmuxWindow]:
        proc = self.runner([
            "list-windows",
            "-t",
            self.session,
            "-F",
            "#{window_index}:#{window_name} active=#{window_active} panes=#{window_panes}",
        ])
        if proc.returncode != 0:
            raise RuntimeError(_first_error_line(proc.stderr) or f"tmux list-windows failed: {proc.returncode}")
        return [_parse_window_line(line) for line in proc.stdout.splitlines() if line.strip()]

    def list_panes(self, *, window: int | None = None) -> list[TmuxPane]:
        args = ["list-panes"]
        if window is None:
            args.extend(["-s", "-t", self.session])
        else:
            args.extend(["-t", f"{self.session}:{window}"])
        args.extend([
            "-F",
            "#{window_index}.#{pane_index}:#{pane_title} active=#{pane_active} command=#{pane_current_command}",
        ])
        proc = self.runner(args)
        if proc.returncode != 0:
            raise RuntimeError(_first_error_line(proc.stderr) or f"tmux list-panes failed: {proc.returncode}")
        return [_parse_pane_line(line) for line in proc.stdout.splitlines() if line.strip()]

    def capture_pane(self, target: str, *, lines: int = 20) -> str:
        proc = self.runner([
            "capture-pane",
            "-t",
            f"{self.session}:{target}" if ":" not in target else target,
            "-p",
            "-S",
            f"-{max(1, int(lines))}",
        ])
        if proc.returncode != 0:
            raise RuntimeError(_first_error_line(proc.stderr) or f"tmux capture-pane failed: {proc.returncode}")
        return proc.stdout

    def cleanup_worker_windows(
        self,
        *,
        windows: Sequence[int] = WORKER_WINDOW_INDICES,
        dry_run: bool = False,
        force: bool = False,
    ) -> list[CleanupAction]:
        window_by_index = {window.index: window for window in self.list_windows()}
        actions: list[CleanupAction] = []
        for index in sorted({int(value) for value in windows}, reverse=True):
            target = f"{self.session}:{index}"
            if index == PROTECTED_WINDOW_INDEX:
                actions.append(CleanupAction(target=target, action="kill-window", status="skipped_protected"))
                continue
            window = window_by_index.get(index)
            if window is None:
                actions.append(CleanupAction(target=target, action="kill-window", status="missing"))
                continue
            expected_name = EXPECTED_WORKER_NAMES.get(index)
            if expected_name and not _matches_expected_worker_name(window.name, expected_name):
                actions.append(
                    CleanupAction(
                        target=target,
                        action="kill-window",
                        status="skipped_unverified",
                        error=f"window name '{window.name}' does not match expected worker '{expected_name}'",
                    )
                )
                continue
            if expected_name and not self._worker_window_has_ownership_marker(index, expected_name):
                actions.append(
                    CleanupAction(
                        target=target,
                        action="kill-window",
                        status="skipped_unverified",
                        error=(
                            f"window '{window.name}' is missing pane title marker "
                            f"'{WORKER_OWNERSHIP_MARKER_PREFIX}{expected_name}'"
                        ),
                    )
                )
                continue
            if dry_run:
                actions.append(CleanupAction(target=target, action="kill-window", status="dry_run"))
                continue
            if not force:
                actions.append(
                    CleanupAction(
                        target=target,
                        action="kill-window",
                        status="requires_force",
                        error="destructive cleanup requires --force",
                    )
                )
                continue
            proc = self.runner(["kill-window", "-t", target])
            if proc.returncode == 0:
                actions.append(CleanupAction(target=target, action="kill-window", status="done"))
            else:
                actions.append(
                    CleanupAction(
                        target=target,
                        action="kill-window",
                        status="error",
                        error=_first_error_line(proc.stderr) or f"exit {proc.returncode}",
                    )
                )
        return actions

    def _worker_window_has_ownership_marker(self, index: int, expected_name: str) -> bool:
        marker = f"{WORKER_OWNERSHIP_MARKER_PREFIX}{expected_name}".lower()
        try:
            panes = self.list_panes(window=index)
        except Exception:
            return False
        return any(
            pane.target.startswith(f"{index}.") and pane.title.strip().lower() == marker
            for pane in panes
        )


def orchestration_status(
    *,
    session: str = "muni",
    runner: CommandRunner | None = None,
    include_capture: bool = False,
) -> dict[str, Any]:
    """Return tmux status for the configured operator/worker layout."""

    controller = TmuxController(session=session, runner=runner)
    report: dict[str, Any] = {
        "session": session,
        "plan": orchestration_plan(),
        "tmux_available": True,
        "ok": True,
        "windows": [],
        "panes": [],
        "warnings": [],
    }
    try:
        windows = controller.list_windows()
    except Exception as exc:
        report["tmux_available"] = False
        report["ok"] = False
        report["warnings"].append(f"tmux session unavailable: {exc}")
        return report

    report["windows"] = [window.to_dict() for window in windows]
    window_by_index = {window.index: window for window in windows}
    if PROTECTED_WINDOW_INDEX not in window_by_index:
        report["ok"] = False
        report["warnings"].append("protected window 0 is missing")
    elif window_by_index[PROTECTED_WINDOW_INDEX].pane_count < len(DEFAULT_OPERATORS):
        report["ok"] = False
        report["warnings"].append("window 0 has fewer panes than configured operators")

    try:
        panes = controller.list_panes()
    except Exception as exc:
        panes = []
        report["warnings"].append(f"pane status unavailable: {exc}")
    report["panes"] = [pane.to_dict() for pane in panes]

    operator_status = []
    pane_targets = {pane.target for pane in panes}
    for operator in DEFAULT_OPERATORS:
        target = f"{PROTECTED_WINDOW_INDEX}.{operator.pane.split('.', 1)[-1]}"
        operator_status.append({
            **operator.to_dict(),
            "operator_pane_present": target in pane_targets,
            "worker_window_present": operator.assigned_window in window_by_index,
        })
    report["operators"] = operator_status

    if include_capture:
        captures: dict[str, str] = {}
        for index in [PROTECTED_WINDOW_INDEX, *WORKER_WINDOW_INDICES]:
            if index not in window_by_index:
                continue
            try:
                captures[str(index)] = _redact_capture_text(controller.capture_pane(str(index), lines=12))
            except Exception as exc:
                captures[str(index)] = _redact_capture_text(f"<capture failed: {exc}>")
        report["captures"] = captures
        report["capture_redacted"] = True
    return report


def cleanup_workers_report(
    *,
    session: str = "muni",
    runner: CommandRunner | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    controller = TmuxController(session=session, runner=runner)
    try:
        actions = controller.cleanup_worker_windows(dry_run=dry_run, force=force)
    except Exception as exc:
        return {
            "session": session,
            "ok": False,
            "dry_run": dry_run,
            "force": force,
            "actions": [],
            "warnings": [f"cleanup failed: {exc}"],
        }
    return {
        "session": session,
        "ok": not any(action.status in {"error", "requires_force", "skipped_unverified"} for action in actions),
        "dry_run": dry_run,
        "force": force,
        "actions": [action.to_dict() for action in actions],
        "warnings": [],
    }


def _run_tmux(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["tmux", *args],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _parse_window_line(line: str) -> TmuxWindow:
    head, _, rest = line.partition(" ")
    raw_index, _, name = head.partition(":")
    fields = _parse_key_values(rest)
    return TmuxWindow(
        index=int(raw_index),
        name=name,
        active=fields.get("active") == "1",
        pane_count=int(fields.get("panes") or 0),
    )


def _parse_pane_line(line: str) -> TmuxPane:
    head, _, rest = line.partition(" ")
    target, _, title = head.partition(":")
    fields = _parse_key_values(rest)
    return TmuxPane(
        target=target,
        title=title,
        active=fields.get("active") == "1",
        command=fields.get("command") or "",
    )


def _parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for part in text.split():
        key, sep, value = part.partition("=")
        if sep:
            values[key] = value
    return values


def _matches_expected_worker_name(name: str, expected: str) -> bool:
    cleaned = name.strip().lower()
    expected = expected.strip().lower()
    return cleaned == expected or cleaned.startswith(f"{expected}-") or cleaned.startswith(f"{expected}_")


def _redact_capture_text(text: str) -> str:
    try:
        from src.safety.lockdown import redact

        return redact(text)
    except Exception:
        return "[REDACTION_FAILED_CAPTURE_OMITTED]"


def _first_error_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:200]
    return ""
