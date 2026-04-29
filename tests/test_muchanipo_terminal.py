from __future__ import annotations

import io
import json
from pathlib import Path

from src.muchanipo import server as server_mod
from src.muchanipo import terminal as terminal_mod


def _fake_run_pipeline(topic, *, progress_callback=None, offline=None):
    assert topic
    assert offline is True
    if progress_callback:
        progress_callback({"event": "stage_started", "stage": "intake"})
        progress_callback({"event": "stage_completed", "stage": "intake"})
        progress_callback({"event": "stage_started", "stage": "finalize"})
        progress_callback({"event": "stage_completed", "stage": "finalize"})
    return {
        "report_md": f"# {topic}\n\n## Chapter 1\n\n테스트 보고서",
        "rounds": [object()],
        "brief": type("Brief", (), {"id": "brief-test"})(),
        "vault_path": Path("/tmp/muchanipo-vault-test.md"),
    }


def test_terminal_run_writes_report_events_and_summary(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(terminal_mod, "run_pipeline", _fake_run_pipeline)
    stdout = io.StringIO()

    result = terminal_mod.terminal_run(
        "터미널 중심 테스트",
        stdout=stdout,
        run_dir=tmp_path / "run",
        offline=True,
    )

    assert result.report_path.exists()
    assert result.events_path.exists()
    assert result.summary_path.exists()
    assert "Muchanipo run started" in stdout.getvalue()
    assert "Muchanipo run completed" in stdout.getvalue()
    assert result.report_path.read_text(encoding="utf-8").startswith("# 터미널 중심 테스트")
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert summary["brief_id"] == "brief-test"
    events = [json.loads(line) for line in result.events_path.read_text(encoding="utf-8").splitlines()]
    assert events[0]["event"] == "terminal_run_started"
    assert events[-1]["event"] == "terminal_run_done"


def test_terminal_run_jsonl_prints_machine_events(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(terminal_mod, "run_pipeline", _fake_run_pipeline)
    stdout = io.StringIO()

    terminal_mod.terminal_run(
        "jsonl 테스트",
        stdout=stdout,
        run_dir=tmp_path / "run",
        offline=True,
        jsonl=True,
    )

    printed = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [event["event"] for event in printed] == [
        "stage_started",
        "stage_completed",
        "stage_started",
        "stage_completed",
        "terminal_run_done",
    ]


def test_run_command_delegates_to_terminal_core(tmp_path: Path, monkeypatch):
    calls = []

    def fake_terminal_run(topic, **kwargs):
        calls.append((topic, kwargs))

    monkeypatch.setattr(terminal_mod, "terminal_run", fake_terminal_run)

    rc = server_mod.main([
        "run",
        "CLI core topic",
        "--offline",
        "--run-dir",
        str(tmp_path / "run"),
    ])

    assert rc == 0
    assert calls[0][0] == "CLI core topic"
    assert calls[0][1]["offline"] is True
    assert calls[0][1]["dashboard"] is False


def test_tui_command_uses_dashboard_unless_plain(tmp_path: Path, monkeypatch):
    calls = []

    def fake_terminal_run(topic, **kwargs):
        calls.append((topic, kwargs))

    monkeypatch.setattr(terminal_mod, "terminal_run", fake_terminal_run)

    assert server_mod.main(["tui", "--topic", "dashboard topic", "--run-dir", str(tmp_path / "run")]) == 0
    assert calls[-1][1]["dashboard"] is True

    assert server_mod.main(["tui", "plain topic", "--plain", "--run-dir", str(tmp_path / "run2")]) == 0
    assert calls[-1][1]["dashboard"] is False
