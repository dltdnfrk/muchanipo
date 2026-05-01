from __future__ import annotations

import subprocess
from collections.abc import Sequence

from src.muchanipo.orchestration import (
    PROTECTED_WINDOW_INDEX,
    cleanup_workers_report,
    orchestration_plan,
    orchestration_status,
)


class FakeTmux:
    def __init__(
        self,
        *,
        windows: str = "",
        panes: str = "",
        capture_text: str = "",
        fail_windows: bool = False,
    ) -> None:
        self.windows = windows
        self.panes = panes
        self.capture_text = capture_text
        self.fail_windows = fail_windows
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        command = list(args)
        self.calls.append(command)
        if command[0] == "list-windows":
            if self.fail_windows:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="can't find session\n")
            return subprocess.CompletedProcess(command, 0, stdout=self.windows, stderr="")
        if command[0] == "list-panes":
            return subprocess.CompletedProcess(command, 0, stdout=self.panes, stderr="")
        if command[0] == "capture-pane":
            text = self.capture_text or f"capture for {command[2]}\n"
            return subprocess.CompletedProcess(command, 0, stdout=text, stderr="")
        if command[0] == "kill-window":
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 127, stdout="", stderr="unknown tmux command\n")


WINDOWS_OK = "\n".join(
    [
        "0:operators active=1 panes=4",
        "1:claude active=0 panes=1",
        "2:codex active=0 panes=1",
        "3:kimi active=0 panes=1",
        "4:opencode active=0 panes=1",
    ]
)

PANES_OK = "\n".join(
    [
        "0.0:claude active=1 command=zsh",
        "0.1:codex active=0 command=zsh",
        "0.2:kimi active=0 command=zsh",
        "0.3:opencode active=0 command=zsh",
        "1.0:worker active=0 command=zsh",
    ]
)

PANES_OWNED_WORKERS = "\n".join(
    [
        "0.0:claude active=1 command=zsh",
        "0.1:codex active=0 command=zsh",
        "0.2:kimi active=0 command=zsh",
        "0.3:opencode active=0 command=zsh",
        "1.0:muchanipo-worker:claude active=0 command=zsh",
        "2.0:muchanipo-worker:codex active=0 command=zsh",
        "3.0:muchanipo-worker:kimi active=0 command=zsh",
        "4.0:muchanipo-worker:opencode active=0 command=zsh",
    ]
)


def test_orchestration_plan_preserves_window0_and_opencode_contract() -> None:
    plan = orchestration_plan()

    assert plan["protected_window"] == PROTECTED_WINDOW_INDEX == 0
    assert plan["worker_windows"] == [1, 2, 3, 4]
    opencode = next(item for item in plan["operators"] if item["agent"] == "opencode")
    assert opencode["model_requirement"] == "Hephaestus - Deep Agent - GPT-5.5 only"
    assert opencode["ownership_marker"] == "muchanipo-worker:opencode"
    assert any("window 0" in rule and "must never be killed" in rule for rule in plan["rules"])


def test_orchestration_status_reads_tmux_layout_and_operator_presence() -> None:
    runner = FakeTmux(windows=WINDOWS_OK, panes=PANES_OK)

    report = orchestration_status(session="muni", runner=runner)

    assert report["ok"] is True
    assert report["tmux_available"] is True
    assert report["warnings"] == []
    assert [window["index"] for window in report["windows"]] == [0, 1, 2, 3, 4]
    assert all(operator["operator_pane_present"] for operator in report["operators"])
    assert all(operator["worker_window_present"] for operator in report["operators"])
    assert runner.calls[1][0:4] == ["list-panes", "-s", "-t", "muni"]


def test_orchestration_status_warns_when_operator_hub_is_underpopulated() -> None:
    runner = FakeTmux(
        windows="0:operators active=1 panes=3\n1:claude active=0 panes=1\n",
        panes="0.0:claude active=1 command=zsh\n",
    )

    report = orchestration_status(session="muni", runner=runner)

    assert report["ok"] is False
    assert "window 0 has fewer panes than configured operators" in report["warnings"]


def test_orchestration_status_reports_missing_tmux_session() -> None:
    report = orchestration_status(session="missing", runner=FakeTmux(fail_windows=True))

    assert report["ok"] is False
    assert report["tmux_available"] is False
    assert report["warnings"][0].startswith("tmux session unavailable:")


def test_orchestration_status_can_include_pane_captures() -> None:
    runner = FakeTmux(
        windows=WINDOWS_OK,
        panes=PANES_OK,
        capture_text="token sk-proj-abcdefghijklmnopqrst email user@example.com\n",
    )

    report = orchestration_status(session="muni", runner=runner, include_capture=True)

    assert sorted(report["captures"]) == ["0", "1", "2", "3", "4"]
    assert report["capture_redacted"] is True
    assert "sk-proj-abcdefghijklmnopqrst" not in report["captures"]["0"]
    assert "user@example.com" not in report["captures"]["0"]
    assert "[REDACTED_OPENAI_KEY]" in report["captures"]["0"]
    capture_calls = [call for call in runner.calls if call[0] == "capture-pane"]
    assert [call[2] for call in capture_calls] == ["muni:0", "muni:1", "muni:2", "muni:3", "muni:4"]


def test_orchestration_capture_redaction_fails_closed(monkeypatch) -> None:
    import src.safety.lockdown as lockdown

    def fail_redact(text: str) -> str:
        raise RuntimeError("redactor unavailable")

    monkeypatch.setattr(lockdown, "redact", fail_redact)
    runner = FakeTmux(
        windows=WINDOWS_OK,
        panes=PANES_OK,
        capture_text="token sk-proj-abcdefghijklmnopqrst email user@example.com\n",
    )

    report = orchestration_status(session="muni", runner=runner, include_capture=True)

    assert report["capture_redacted"] is True
    assert set(report["captures"].values()) == {"[REDACTION_FAILED_CAPTURE_OMITTED]"}


def test_cleanup_worker_windows_requires_force_before_kill() -> None:
    runner = FakeTmux(windows=WINDOWS_OK, panes=PANES_OWNED_WORKERS)

    report = cleanup_workers_report(session="muni", runner=runner)

    assert report["ok"] is False
    assert [action["status"] for action in report["actions"]] == [
        "requires_force",
        "requires_force",
        "requires_force",
        "requires_force",
    ]
    assert not any(call[0] == "kill-window" for call in runner.calls)


def test_cleanup_worker_windows_never_kills_protected_window0() -> None:
    runner = FakeTmux(windows=WINDOWS_OK, panes=PANES_OWNED_WORKERS)

    report = cleanup_workers_report(session="muni", runner=runner, force=True)

    assert report["ok"] is True
    assert report["force"] is True
    assert [action["target"] for action in report["actions"]] == ["muni:4", "muni:3", "muni:2", "muni:1"]
    kill_calls = [call for call in runner.calls if call[0] == "kill-window"]
    assert [call[-1] for call in kill_calls] == ["muni:4", "muni:3", "muni:2", "muni:1"]
    assert "muni:0" not in [call[-1] for call in kill_calls]


def test_cleanup_worker_windows_dry_run_only_reports_actions() -> None:
    runner = FakeTmux(windows=WINDOWS_OK, panes=PANES_OWNED_WORKERS)

    report = cleanup_workers_report(session="muni", runner=runner, dry_run=True)

    assert [action["status"] for action in report["actions"]] == ["dry_run", "dry_run", "dry_run", "dry_run"]
    assert not any(call[0] == "kill-window" for call in runner.calls)


def test_cleanup_worker_windows_skips_unverified_worker_names_even_with_force() -> None:
    runner = FakeTmux(
        windows="\n".join(
            [
                "0:operators active=1 panes=4",
                "1:unrelated active=0 panes=1",
                "2:codex active=0 panes=1",
            ]
        ),
        panes=PANES_OWNED_WORKERS,
    )

    report = cleanup_workers_report(session="muni", runner=runner, force=True)

    assert report["ok"] is False
    assert report["actions"][0]["status"] == "missing"
    assert report["actions"][1]["status"] == "missing"
    assert report["actions"][2]["status"] == "done"
    assert report["actions"][3]["status"] == "skipped_unverified"
    kill_calls = [call for call in runner.calls if call[0] == "kill-window"]
    assert [call[-1] for call in kill_calls] == ["muni:2"]


def test_cleanup_worker_windows_skips_name_only_windows_without_marker() -> None:
    runner = FakeTmux(windows=WINDOWS_OK, panes=PANES_OK)

    report = cleanup_workers_report(session="muni", runner=runner, force=True)

    assert report["ok"] is False
    assert [action["status"] for action in report["actions"]] == [
        "skipped_unverified",
        "skipped_unverified",
        "skipped_unverified",
        "skipped_unverified",
    ]
    assert not any(call[0] == "kill-window" for call in runner.calls)
