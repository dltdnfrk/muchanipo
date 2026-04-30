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
from src.runtime.live_mode import LiveModeViolation


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


def _fake_run_pipeline(topic, *, progress_callback=None, offline=None, require_live=None):
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


def test_terminal_run_persists_canonical_stage_order_to_events_jsonl(tmp_path: Path, monkeypatch):
    def full_stage_run(topic, *, progress_callback=None, offline=None, require_live=None):
        assert progress_callback is not None
        for stage in terminal_mod.STAGE_ORDER:
            progress_callback({"event": "stage_started", "stage": stage})
            progress_callback({"event": "stage_completed", "stage": stage})
        return {
            "report_md": "# stage ordered\n",
            "rounds": [],
            "brief": type("Brief", (), {"id": "brief-stage"})(),
            "vault_path": Path("/tmp/stage-vault.md"),
        }

    monkeypatch.setattr(terminal_mod, "run_pipeline", full_stage_run)

    result = terminal_mod.terminal_run(
        "단계 순서 검증",
        stdout=io.StringIO(),
        run_dir=tmp_path / "run",
        offline=True,
    )

    events = [json.loads(line) for line in result.events_path.read_text(encoding="utf-8").splitlines()]
    stage_events = [event for event in events if event.get("stage")]
    expected = [
        {"event": event_name, "stage": stage}
        for stage in terminal_mod.STAGE_ORDER
        for event_name in ("stage_started", "stage_completed")
    ]
    assert [{"event": event["event"], "stage": event["stage"]} for event in stage_events] == expected
    assert events[0]["event"] == "terminal_run_started"
    assert events[-1]["event"] == "terminal_run_done"
    assert set(result.stage_status.values()) == {"done"}


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


def test_conduct_interview_merges_show_prd_answers_into_pipeline_input():
    stdout = io.StringIO()

    capture = terminal_mod.conduct_interview(
        "딸기 무병묘 시장성",
        stdin=io.StringIO(
            "한국 딸기 농가용 무병묘 시장 규모\n"
            "투자 검토\n"
            "한국 AgTech\n"
            "기존 조직배양 업체는 알고 있음\n"
            "정량 수치 + 출처\n"
            "학술 논문과 정부 통계 우선\n"
        ),
        stdout=stdout,
    )

    assert capture.original_topic == "딸기 무병묘 시장성"
    assert capture.mode == "deep"
    assert capture.answered == 6
    assert "[원 요청] 딸기 무병묘 시장성" in capture.pipeline_input
    assert "[Q1_research_question] 한국 딸기 농가용 무병묘 시장 규모" in capture.pipeline_input
    assert "아이디어 심층 인터뷰" in stdout.getvalue()


def test_terminal_run_failure_saves_summary_and_error_event(tmp_path: Path, monkeypatch):
    def boom(topic, *, progress_callback=None, offline=None, require_live=None):
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


def test_run_online_live_violation_fails_closed_and_persists_failure_artifacts(tmp_path: Path, monkeypatch, capsys):
    def live_gate_failure(topic, *, progress_callback=None, offline=None, require_live=None):
        assert offline is False
        assert require_live is True
        if progress_callback:
            progress_callback({"event": "stage_started", "stage": "evidence"})
        raise LiveModeViolation("live evidence missing")

    monkeypatch.setattr(terminal_mod, "run_pipeline", live_gate_failure)
    run_dir = tmp_path / "online-failed"

    rc = server_mod.main([
        "run",
        "live gate topic",
        "--online",
        "--run-dir",
        str(run_dir),
    ])

    assert rc == 1
    assert "muchanipo: run failed: LiveModeViolation: live evidence missing" in capsys.readouterr().err
    assert not (run_dir / "REPORT.md").exists()
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert summary["status"] == "failed"
    assert summary["offline"] is False
    assert summary["require_live"] is True
    assert summary["error_type"] == "LiveModeViolation"
    assert events[-1]["event"] == "terminal_run_error"


def test_terminal_run_keyboard_interrupt_saves_interrupted_summary(tmp_path: Path, monkeypatch):
    def interrupt(topic, *, progress_callback=None, offline=None, require_live=None):
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


def test_terminal_app_supports_slash_exit():
    stdout = io.StringIO()

    rc = terminal_mod.terminal_app(stdin=io.StringIO("/exit\n"), stdout=stdout)

    assert rc == 0
    assert "bye" in stdout.getvalue()


def test_terminal_app_supports_slash_help_and_clear():
    stdout = io.StringIO()

    rc = terminal_mod.terminal_app(stdin=io.StringIO("/help\n/clear\n/exit\n"), stdout=stdout)

    text = stdout.getvalue()
    assert rc == 0
    assert "Interactive slash commands" in text
    assert text.count("Muchanipo") >= 2


def test_terminal_app_supports_slash_status_and_runs(monkeypatch):
    calls = []

    def fake_render_runs(**kwargs):
        calls.append(("runs", kwargs))
        kwargs["stdout"].write("fake runs\n")
        return []

    def fake_render_cli_status(**kwargs):
        calls.append(("status", kwargs))
        kwargs["stdout"].write("fake status\n")
        return []

    monkeypatch.setattr(terminal_mod, "render_runs", fake_render_runs)
    monkeypatch.setattr(terminal_mod, "render_cli_status", fake_render_cli_status)
    stdout = io.StringIO()

    rc = terminal_mod.terminal_app(stdin=io.StringIO("/runs\n/status\n/exit\n"), stdout=stdout)

    assert rc == 0
    assert [call[0] for call in calls] == ["runs", "status"]
    assert "fake runs" in stdout.getvalue()
    assert "fake status" in stdout.getvalue()


def test_terminal_app_supports_slash_doctor(monkeypatch):
    calls = []

    def fake_render_doctor(**kwargs):
        calls.append(kwargs)
        kwargs["stdout"].write("fake doctor\n")
        return {"ok": True}

    monkeypatch.setattr(terminal_mod, "render_doctor", fake_render_doctor)
    stdout = io.StringIO()

    rc = terminal_mod.terminal_app(stdin=io.StringIO("/doctor\n/exit\n"), stdout=stdout)

    assert rc == 0
    assert calls
    assert "fake doctor" in stdout.getvalue()


def test_terminal_app_unknown_slash_command_does_not_start_research(monkeypatch):
    def fail_terminal_run(*args, **kwargs):
        raise AssertionError("unknown slash commands must not start research")

    monkeypatch.setattr(terminal_mod, "terminal_run", fail_terminal_run)
    stdout = io.StringIO()

    rc = terminal_mod.terminal_app(stdin=io.StringIO("/wat\n/exit\n"), stdout=stdout)

    assert rc == 0
    assert "unknown command: /wat" in stdout.getvalue()
    assert "type /help for commands" in stdout.getvalue()


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
    assert "[Q1_research_question] q" in calls[0][1]["pipeline_input"]


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
    assert "[Q1_research_question] q" in calls[0][1]["pipeline_input"]


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


def test_home_snapshot_and_render_home_surface_recent_runs_and_last_failure(tmp_path: Path):
    root = tmp_path / "runs"
    completed = root / "completed"
    failed = root / "failed"
    older = root / "older"
    completed.mkdir(parents=True)
    failed.mkdir(parents=True)
    older.mkdir(parents=True)
    (older / "summary.json").write_text(
        json.dumps({
            "topic": "older topic",
            "run_id": "older",
            "status": "completed",
            "completed_at": "2026-01-01T00:00:00+00:00",
        }),
        encoding="utf-8",
    )
    (failed / "summary.json").write_text(
        json.dumps({
            "topic": "failed topic",
            "run_id": "failed",
            "status": "failed",
            "error_type": "RuntimeError",
            "message": "provider blocked",
            "completed_at": "2026-01-03T00:00:00+00:00",
        }),
        encoding="utf-8",
    )
    (completed / "summary.json").write_text(
        json.dumps({
            "topic": "completed topic",
            "run_id": "completed",
            "status": "completed",
            "completed_at": "2026-01-04T00:00:00+00:00",
        }),
        encoding="utf-8",
    )

    snapshot = terminal_mod.home_snapshot(runs_dir=root, recent_limit=2)
    stdout = io.StringIO()
    terminal_mod._render_home(stdout, runs_dir=root)

    assert snapshot["schema_version"] == 1
    assert [item["run_id"] for item in snapshot["recent_runs"]] == ["completed", "failed"]
    assert snapshot["last_failure"]["run_id"] == "failed"
    text = stdout.getvalue()
    assert "Recent runs" in text
    assert text.index("completed topic") < text.index("failed topic")
    assert "Last failure" in text
    assert "RuntimeError: provider blocked" in text


def test_render_home_handles_empty_run_history(tmp_path: Path):
    stdout = io.StringIO()

    terminal_mod._render_home(stdout, runs_dir=tmp_path / "runs")

    assert "Recent runs: none yet" in stdout.getvalue()


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


def test_main_direct_topic_shortcut_can_force_interview(monkeypatch):
    calls = []

    def fake_terminal_run(topic, **kwargs):
        calls.append((topic, kwargs))

    monkeypatch.setattr(sys, "stdin", io.StringIO("좁힌 질문\n투자 판단\n한국 농업\n없음\n비교표\n강한 출처\n"))
    monkeypatch.setattr(terminal_mod, "terminal_run", fake_terminal_run)

    assert server_mod.main(["딸기 시장성", "--interview"]) == 0
    assert calls[0][0] == "딸기 시장성"
    assert "[Q1_research_question] 좁힌 질문" in calls[0][1]["pipeline_input"]


def test_main_direct_topic_shortcut_forced_interview_runs_before_terminal_run(monkeypatch):
    calls = []

    def fake_conduct_interview(topic, **kwargs):
        calls.append(("conduct_interview", topic, kwargs))
        return terminal_mod.InterviewCapture(
            original_topic=topic,
            pipeline_input="[원 요청] 딸기 시장성\n[Q1_research_question] 좁힌 질문\n[Q6_quality] 강한 출처",
            mode="deep",
            answered=2,
        )

    def fake_terminal_run(topic, **kwargs):
        calls.append(("terminal_run", topic, kwargs))

    monkeypatch.setattr(terminal_mod, "conduct_interview", fake_conduct_interview)
    monkeypatch.setattr(terminal_mod, "terminal_run", fake_terminal_run)

    assert server_mod.main(["딸기 시장성", "--interview"]) == 0

    assert [call[0] for call in calls] == ["conduct_interview", "terminal_run"]
    assert calls[1][1] == "딸기 시장성"
    pipeline_input = calls[1][2]["pipeline_input"]
    assert pipeline_input != "딸기 시장성"
    assert "[원 요청] 딸기 시장성" in pipeline_input
    assert "[Q1_research_question] 좁힌 질문" in pipeline_input
    assert "[Q6_quality] 강한 출처" in pipeline_input


def test_main_direct_topic_shortcut_no_interview_keeps_raw_topic(monkeypatch):
    calls = []

    def fake_terminal_run(topic, **kwargs):
        calls.append((topic, kwargs))

    monkeypatch.setattr(terminal_mod, "terminal_run", fake_terminal_run)

    assert server_mod.main(["딸기 시장성", "--no-interview"]) == 0
    assert calls[0][0] == "딸기 시장성"
    assert calls[0][1]["pipeline_input"] is None


def test_main_direct_topic_shortcut_jsonl_disables_interview_and_never_reads_stdin(monkeypatch):
    calls = []

    def fail_interview(*args, **kwargs):
        raise AssertionError("jsonl shortcut must not conduct an interactive interview")

    def fake_terminal_run(topic, **kwargs):
        calls.append((topic, kwargs))

    monkeypatch.setattr(terminal_mod, "conduct_interview", fail_interview)
    monkeypatch.setattr(terminal_mod, "terminal_run", fake_terminal_run)

    assert server_mod.main(["딸기 시장성", "--jsonl"]) == 0

    assert calls[0][0] == "딸기 시장성"
    assert calls[0][1]["jsonl"] is True
    assert calls[0][1]["pipeline_input"] is None


def test_main_direct_topic_shortcut_accepts_online_and_report_path(tmp_path: Path, monkeypatch):
    calls = []

    def fake_terminal_run(topic, **kwargs):
        calls.append((topic, kwargs))

    monkeypatch.setattr(terminal_mod, "terminal_run", fake_terminal_run)

    assert server_mod.main([
        "딸기 시장성",
        "--online",
        "--report-path",
        str(tmp_path / "REPORT.md"),
    ]) == 0
    assert calls[0][1]["offline"] is False
    assert calls[0][1]["require_live"] is True
    assert calls[0][1]["report_path"] == tmp_path / "REPORT.md"


def test_main_direct_topic_shortcut_rejects_bad_flags(capsys):
    assert server_mod.main(["딸기", "--offline", "--online"]) == 2
    assert "--offline and --online are mutually exclusive" in capsys.readouterr().err

    assert server_mod.main(["딸기", "--unknown"]) == 2
    assert "unknown shortcut option: --unknown" in capsys.readouterr().err

    assert server_mod.main(["딸기", "--run-dir"]) == 2
    assert "--run-dir requires a value" in capsys.readouterr().err


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


def test_main_doctor_command_returns_report_status(monkeypatch):
    calls = []

    def fake_render_doctor(**kwargs):
        calls.append(kwargs)
        return {"ok": False}

    monkeypatch.setattr(terminal_mod, "render_doctor", fake_render_doctor)

    assert server_mod.main(["doctor"]) == 1
    assert calls


def test_main_runs_status_and_doctor_json(monkeypatch, capsys):
    monkeypatch.setattr(
        terminal_mod,
        "list_runs",
        lambda **kwargs: [{"run_id": "run-json", "topic": "json topic"}],
    )
    monkeypatch.setattr(
        terminal_mod,
        "cli_statuses",
        lambda: [{"name": "claude", "installed": True, "path": "/bin/claude"}],
    )
    monkeypatch.setattr(
        terminal_mod,
        "doctor_report",
        lambda: {"schema_version": 1, "ok": True, "status": "ok", "runs_dir": "/tmp/runs", "checks": []},
    )

    assert server_mod.main(["runs", "--json"]) == 0
    runs = json.loads(capsys.readouterr().out)
    assert runs["schema_version"] == 1
    assert runs["command"] == "muchanipo runs"
    assert runs["runs"][0]["run_id"] == "run-json"

    assert server_mod.main(["status", "--json"]) == 0
    statuses = json.loads(capsys.readouterr().out)
    assert statuses["schema_version"] == 1
    assert statuses["command"] == "muchanipo status"
    assert statuses["providers"][0]["name"] == "claude"

    assert server_mod.main(["doctor", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["schema_version"] == 1


def test_main_contracts_json_documents_cli_json_contracts(capsys):
    assert server_mod.main(["contracts", "--json"]) == 0

    report = json.loads(capsys.readouterr().out)
    contracts = report["contracts"]
    assert report["schema_version"] == 1
    assert report["command"] == "muchanipo contracts"
    assert set(contracts) == {"muchanipo doctor", "muchanipo status", "muchanipo runs"}
    assert contracts["muchanipo doctor"]["required_top_level_keys"] == [
        "schema_version",
        "command",
        "ok",
        "status",
        "runs_dir",
        "checks",
        "cli_statuses",
        "recommendations",
    ]


def test_cli_json_reports_satisfy_documented_contracts(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        terminal_mod,
        "cli_statuses",
        lambda: [{"name": "codex", "installed": True, "path": "/bin/codex"}],
    )
    reports = {
        "muchanipo doctor": terminal_mod.doctor_report(runs_dir=tmp_path / "runs"),
        "muchanipo status": terminal_mod.status_report(),
        "muchanipo runs": terminal_mod.runs_report(runs_dir=tmp_path / "runs"),
    }
    contracts = terminal_mod.json_contracts_report()["contracts"]

    for command, report in reports.items():
        contract = contracts[command]
        assert report["schema_version"] == contract["schema_version"]
        assert report["command"] == command
        assert set(contract["required_top_level_keys"]).issubset(report)


def test_render_json_contracts_formats_human_summary():
    stdout = io.StringIO()

    report = terminal_mod.render_json_contracts(stdout=stdout)

    assert report["schema_version"] == 1
    text = stdout.getvalue()
    assert "CLI JSON contracts" in text
    assert "muchanipo doctor --json" in text
    assert "required keys: schema_version, command, ok" in text


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


def test_cli_statuses_records_oserror_without_crashing(monkeypatch):
    def fake_resolve(name, env_var):
        return f"/fake/{name}" if name == "codex" else None

    def fake_run(args, **kwargs):
        raise OSError("Exec format error")

    monkeypatch.setattr(terminal_mod, "_resolve_cli_path", fake_resolve)
    monkeypatch.setattr(terminal_mod.subprocess, "run", fake_run)

    codex = next(item for item in terminal_mod.cli_statuses() if item["name"] == "codex")
    assert codex["installed"] is True
    assert "Exec format error" in codex["error"]


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


def test_render_doctor_reports_runs_dir_and_warning(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(terminal_mod, "cli_statuses", lambda: [])
    stdout = io.StringIO()

    report = terminal_mod.render_doctor(stdout=stdout, runs_dir=tmp_path / "runs")

    text = stdout.getvalue()
    assert report["ok"] is True
    assert report["schema_version"] == 1
    assert report["command"] == "muchanipo doctor"
    assert report["status"] == "warning"
    assert "Doctor" in text
    assert "[OK] runs_dir" in text
    assert "[WARN] provider_clis" in text


def test_doctor_report_marks_provider_probe_failures_as_warning(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        terminal_mod,
        "cli_statuses",
        lambda: [
            {
                "name": "claude",
                "installed": True,
                "path": "/bin/claude",
                "version": None,
                "error": "auth missing",
            }
        ],
    )

    report = terminal_mod.doctor_report(runs_dir=tmp_path / "runs")

    probe = next(item for item in report["checks"] if item["name"] == "provider_probe")
    assert report["ok"] is True
    assert report["status"] == "warning"
    assert probe["ok"] is False
    assert "auth missing" in probe["detail"]


def test_status_and_runs_reports_have_stable_json_shape(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        terminal_mod,
        "cli_statuses",
        lambda: [{"name": "codex", "installed": True, "path": "/bin/codex"}],
    )
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(
        json.dumps({"run_id": "r1", "topic": "shape test", "completed_at": "2026-04-30T00:00:00+00:00"}),
        encoding="utf-8",
    )

    status = terminal_mod.status_report()
    runs = terminal_mod.runs_report(runs_dir=tmp_path / "runs", limit=5)

    assert status["schema_version"] == 1
    assert status["providers"][0]["name"] == "codex"
    assert runs["schema_version"] == 1
    assert runs["limit"] == 5
    assert runs["runs"][0]["run_id"] == "r1"


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
