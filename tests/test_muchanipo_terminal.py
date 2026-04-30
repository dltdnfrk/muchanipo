from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.muchanipo import server as server_mod
from src.muchanipo import terminal as terminal_mod


REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_muchanipo(
    args: list[str],
    *,
    stdin_text: str = "",
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + existing if existing else "")
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "muchanipo", *args],
        input=stdin_text,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=15,
        check=False,
    )


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


def test_terminal_run_failure_saves_summary_and_error_event(tmp_path: Path, monkeypatch):
    def boom(topic, *, progress_callback=None, offline=None):
        if progress_callback:
            progress_callback({"event": "stage_started", "stage": "research"})
        raise RuntimeError("provider blocked")

    monkeypatch.setattr(terminal_mod, "run_pipeline", boom)
    stdout = io.StringIO()
    run_dir = tmp_path / "failed"

    with pytest.raises(RuntimeError, match="provider blocked"):
        terminal_mod.terminal_run("실패 보존 테스트", stdout=stdout, run_dir=run_dir, offline=False)

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert summary["status"] == "failed"
    assert summary["error_type"] == "RuntimeError"
    assert events[-1]["event"] == "terminal_run_error"
    assert "Partial artifacts were saved." in stdout.getvalue()


def test_terminal_run_keyboard_interrupt_saves_interrupted_summary(tmp_path: Path, monkeypatch):
    def interrupt(topic, *, progress_callback=None, offline=None):
        raise KeyboardInterrupt

    monkeypatch.setattr(terminal_mod, "run_pipeline", interrupt)
    stdout = io.StringIO()
    run_dir = tmp_path / "interrupted"

    with pytest.raises(KeyboardInterrupt):
        terminal_mod.terminal_run("중단 보존 테스트", stdout=stdout, run_dir=run_dir, offline=None)

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert summary["status"] == "interrupted"
    assert events[-1]["event"] == "terminal_run_interrupted"
    assert "INTERRUPTED" in stdout.getvalue()


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


def test_terminal_app_quits_cleanly_on_q():
    stdout = io.StringIO()

    rc = terminal_mod.terminal_app(stdin=io.StringIO("q\n"), stdout=stdout)

    assert rc == 0
    assert "Muchanipo" in stdout.getvalue()
    assert "bye" in stdout.getvalue()


def test_terminal_app_exits_cleanly_on_piped_eof():
    stdout = io.StringIO()

    rc = terminal_mod.terminal_app(stdin=io.StringIO(""), stdout=stdout)

    assert rc == 0
    assert "Muchanipo" in stdout.getvalue()
    assert "bye" in stdout.getvalue()


def test_terminal_app_new_research_uses_terminal_run(monkeypatch):
    calls = []

    def fake_terminal_run(topic, **kwargs):
        calls.append((topic, kwargs))

    monkeypatch.setattr(terminal_mod, "terminal_run", fake_terminal_run)
    stdout = io.StringIO()

    rc = terminal_mod.terminal_app(
        stdin=io.StringIO("1\n딸기 시장성\noffline\nq\n"),
        stdout=stdout,
    )

    assert rc == 0
    assert calls[0][0] == "딸기 시장성"
    assert calls[0][1]["offline"] is True


def test_terminal_app_treats_unknown_nonempty_input_as_topic(monkeypatch):
    calls = []

    def fake_terminal_run(topic, **kwargs):
        calls.append((topic, kwargs))

    monkeypatch.setattr(terminal_mod, "terminal_run", fake_terminal_run)

    rc = terminal_mod.terminal_app(
        stdin=io.StringIO("딸기 시장성 바로 시작\nq\n"),
        stdout=io.StringIO(),
    )

    assert rc == 0
    assert calls[0][0] == "딸기 시장성 바로 시작"
    assert calls[0][1]["offline"] is None


def test_terminal_app_returns_home_after_run_failure(monkeypatch):
    def fail_terminal_run(topic, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(terminal_mod, "terminal_run", fail_terminal_run)
    stdout = io.StringIO()

    rc = terminal_mod.terminal_app(stdin=io.StringIO("실패 후 홈\nq\n"), stdout=stdout)

    text = stdout.getvalue()
    assert rc == 0
    assert "Run failed; returning to Muchanipo home" in text
    assert text.count("Muchanipo") >= 2


def test_render_runs_lists_summaries_newest_first(tmp_path: Path):
    root = tmp_path / "runs"
    older = root / "older"
    newer = root / "newer"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    (older / "summary.json").write_text(
        json.dumps({
            "topic": "older topic",
            "run_id": "older",
            "report_path": "/tmp/older.md",
            "completed_at": "2026-01-01T00:00:00+00:00",
        }),
        encoding="utf-8",
    )
    (newer / "summary.json").write_text(
        json.dumps({
            "topic": "newer topic",
            "run_id": "newer",
            "report_path": "/tmp/newer.md",
            "completed_at": "2026-01-02T00:00:00+00:00",
        }),
        encoding="utf-8",
    )
    stdout = io.StringIO()

    records = terminal_mod.render_runs(stdout=stdout, runs_dir=root)

    assert [record["run_id"] for record in records] == ["newer", "older"]
    text = stdout.getvalue()
    assert text.index("newer topic") < text.index("older topic")


def test_main_no_args_opens_terminal_app(monkeypatch):
    calls = []

    def fake_terminal_app(**kwargs):
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(terminal_mod, "terminal_app", fake_terminal_app)

    assert server_mod.main([]) == 0
    assert calls


def test_main_direct_topic_shortcut_delegates_to_terminal_run(monkeypatch):
    calls = []

    def fake_terminal_run(topic, **kwargs):
        calls.append((topic, kwargs))

    monkeypatch.setattr(terminal_mod, "terminal_run", fake_terminal_run)

    assert server_mod.main(["딸기", "시장성"]) == 0
    assert calls[0][0] == "딸기 시장성"


def test_main_direct_topic_shortcut_uses_dashboard_when_stdout_is_tty(monkeypatch):
    calls = []

    class TtyStdout(io.StringIO):
        def isatty(self):
            return True

    def fake_terminal_run(topic, **kwargs):
        calls.append((topic, kwargs))

    monkeypatch.setattr(sys, "stdout", TtyStdout())
    monkeypatch.setattr(terminal_mod, "terminal_run", fake_terminal_run)

    assert server_mod.main(["딸기"]) == 0
    assert calls[0][1]["dashboard"] is True


def test_main_does_not_treat_dash_help_as_topic(capsys):
    with pytest.raises(SystemExit) as excinfo:
        server_mod.main(["--help"])

    assert excinfo.value.code == 0
    assert "usage: muchanipo" in capsys.readouterr().out


def test_main_direct_topic_shortcut_accepts_common_flags(tmp_path: Path, monkeypatch):
    calls = []

    def fake_terminal_run(topic, **kwargs):
        calls.append((topic, kwargs))

    monkeypatch.setattr(terminal_mod, "terminal_run", fake_terminal_run)

    assert server_mod.main([
        "딸기 시장성",
        "--offline",
        "--run-dir",
        str(tmp_path / "runs"),
        "--plain",
    ]) == 0
    assert calls[0][0] == "딸기 시장성"
    assert calls[0][1]["offline"] is True
    assert calls[0][1]["run_dir"] == tmp_path / "runs"
    assert calls[0][1]["dashboard"] is False


def test_main_terminal_failure_returns_exit_code(monkeypatch, capsys):
    def fail_terminal_run(topic, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(terminal_mod, "terminal_run", fail_terminal_run)

    assert server_mod.main(["딸기"]) == 1
    assert "muchanipo: run failed: RuntimeError: provider unavailable" in capsys.readouterr().err


def test_main_terminal_interrupt_returns_130(monkeypatch, capsys):
    def interrupt_terminal_run(topic, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(terminal_mod, "terminal_run", interrupt_terminal_run)

    assert server_mod.main(["딸기"]) == 130
    assert "muchanipo: interrupted" in capsys.readouterr().err


def test_main_runs_and_status_commands(monkeypatch):
    calls = []

    def fake_render_runs(**kwargs):
        calls.append(("runs", kwargs))
        return []

    def fake_render_cli_status(**kwargs):
        calls.append(("status", kwargs))
        return []

    monkeypatch.setattr(terminal_mod, "render_runs", fake_render_runs)
    monkeypatch.setattr(terminal_mod, "render_cli_status", fake_render_cli_status)

    assert server_mod.main(["runs", "--limit", "3"]) == 0
    assert server_mod.main(["status"]) == 0
    assert calls[0][0] == "runs"
    assert calls[0][1]["limit"] == 3
    assert calls[1][0] == "status"


def test_cli_statuses_records_nonzero_version_probe(monkeypatch):
    def fake_resolve(name, env_var):
        return f"/fake/{name}" if name == "claude" else None

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 2, stdout="", stderr="auth missing\nextra")

    monkeypatch.setattr(terminal_mod, "_resolve_cli_path", fake_resolve)
    monkeypatch.setattr(terminal_mod.subprocess, "run", fake_run)

    statuses = terminal_mod.cli_statuses()
    claude = next(item for item in statuses if item["name"] == "claude")
    codex = next(item for item in statuses if item["name"] == "codex")
    assert claude["installed"] is True
    assert claude["error"] == "auth missing"
    assert codex["installed"] is False


def test_cli_statuses_records_timeout(monkeypatch):
    def fake_resolve(name, env_var):
        return f"/fake/{name}" if name == "kimi" else None

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, timeout=5)

    monkeypatch.setattr(terminal_mod, "_resolve_cli_path", fake_resolve)
    monkeypatch.setattr(terminal_mod.subprocess, "run", fake_run)

    kimi = next(item for item in terminal_mod.cli_statuses() if item["name"] == "kimi")
    assert kimi["installed"] is True
    assert "timed out" in kimi["error"]


def test_render_cli_status_formats_installed_errors_and_missing(monkeypatch):
    monkeypatch.setattr(
        terminal_mod,
        "cli_statuses",
        lambda: [
            {"name": "claude", "installed": True, "path": "/bin/claude", "version": "1.0", "error": None},
            {"name": "kimi", "installed": True, "path": "/bin/kimi", "version": None, "error": "auth missing"},
            {"name": "codex", "installed": False, "path": None, "version": None, "error": None},
        ],
    )
    stdout = io.StringIO()

    terminal_mod.render_cli_status(stdout=stdout)

    text = stdout.getvalue()
    assert "[OK] claude" in text
    assert "installed; version probe failed: auth missing" in text
    assert "[--] codex" in text


def test_subprocess_no_args_menu_quits_without_hanging(tmp_path: Path):
    proc = _run_muchanipo(
        [],
        stdin_text="q\n",
        env_overrides={"MUCHANIPO_RUNS_DIR": str(tmp_path / "runs")},
    )

    assert proc.returncode == 0, proc.stderr
    assert "Muchanipo" in proc.stdout
    assert "bye" in proc.stdout


def test_subprocess_no_args_menu_can_start_offline_run(tmp_path: Path):
    runs_dir = tmp_path / "runs"
    proc = _run_muchanipo(
        [],
        stdin_text="1\n서브프로세스 메뉴 실행\noffline\nq\n",
        env_overrides={"MUCHANIPO_RUNS_DIR": str(runs_dir)},
    )

    assert proc.returncode == 0, proc.stderr
    assert "Muchanipo run started: 서브프로세스 메뉴 실행" in proc.stdout
    assert "Muchanipo run completed." in proc.stdout
    assert list(runs_dir.glob("*/summary.json"))


def test_subprocess_direct_topic_shortcut_can_force_offline(tmp_path: Path):
    run_dir = tmp_path / "direct"
    proc = _run_muchanipo([
        "서브프로세스 직접 실행",
        "--offline",
        "--run-dir",
        str(run_dir),
        "--plain",
    ])

    assert proc.returncode == 0, proc.stderr
    assert "Muchanipo run started: 서브프로세스 직접 실행" in proc.stdout
    assert (run_dir / "REPORT.md").exists()
