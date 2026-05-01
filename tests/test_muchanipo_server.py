"""Worker-1 acceptance: subprocess + JSON-line parsing for `muchanipo serve`."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.muchanipo import parse_action
from src.muchanipo import server as server_mod
from src.muchanipo.events import KNOWN_EVENTS, emit
from src.muchanipo.server import _detect_offline_mode, serve


REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_serve(args: list[str], *, stdin_text: str = "") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Ensure the project root is on PYTHONPATH so `python -m muchanipo` resolves
    # the top-level shim package without requiring `pip install -e .`.
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + existing if existing else "")
    return subprocess.run(
        [sys.executable, "-m", "muchanipo", "serve", *args],
        input=stdin_text,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=15,
        check=False,
    )


def _parse_lines(stdout: str) -> list[dict]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def test_serve_emits_canonical_phase_order(tmp_path: Path) -> None:
    report = tmp_path / "REPORT.md"
    proc = _run_serve(
        ["--topic", "test", "--pipeline", "stub", "--no-wait", "--report-path", str(report)],
    )
    assert proc.returncode == 0, proc.stderr
    events = _parse_lines(proc.stdout)
    phase_order = [e["phase"] for e in events if e["event"] == "phase_change"]
    assert phase_order == ["STARTUP", "INTERVIEW", "COUNCIL", "REPORT"]
    assert any(e["event"] == "done" for e in events)
    assert report.exists()


def test_serve_every_event_type_is_known(tmp_path: Path) -> None:
    proc = _run_serve(
        ["--topic", "x", "--pipeline", "stub", "--no-wait", "--report-path", str(tmp_path / "R.md")],
    )
    assert proc.returncode == 0, proc.stderr
    events = _parse_lines(proc.stdout)
    assert events, "expected at least one event line"
    for ev in events:
        assert ev["event"] in KNOWN_EVENTS, f"unknown event: {ev}"


def test_serve_advances_after_interview_answer(tmp_path: Path) -> None:
    answer = json.dumps({"action": "interview_answer", "q_id": "Q1", "answer": "A"})
    proc = _run_serve(
        ["--topic", "wired", "--pipeline", "stub", "--report-path", str(tmp_path / "R.md")],
        stdin_text=answer + "\n",
    )
    assert proc.returncode == 0, proc.stderr
    events = _parse_lines(proc.stdout)
    # After the answer, COUNCIL + REPORT phases must run.
    phases = [e["phase"] for e in events if e["event"] == "phase_change"]
    assert "COUNCIL" in phases
    assert "REPORT" in phases


def test_serve_aborts_cleanly_on_abort_action(tmp_path: Path) -> None:
    proc = _run_serve(
        ["--topic", "stop", "--pipeline", "stub", "--report-path", str(tmp_path / "R.md")],
        stdin_text=json.dumps({"action": "abort"}) + "\n",
    )
    assert proc.returncode == 0, proc.stderr
    events = _parse_lines(proc.stdout)
    assert events[-1]["event"] == "done"
    assert events[-1].get("aborted") is True


def test_emit_writes_json_line_and_flushes() -> None:
    buf = io.StringIO()
    emit("phase_change", stream=buf, phase="INTERVIEW", data={"q": 1})
    line = buf.getvalue()
    assert line.endswith("\n")
    obj = json.loads(line)
    assert obj == {"event": "phase_change", "phase": "INTERVIEW", "data": {"q": 1}}


def test_parse_action_round_trips() -> None:
    a = parse_action(json.dumps({"action": "interview_answer", "q_id": "Q1", "answer": "B"}))
    assert a is not None
    assert a.action == "interview_answer"
    assert a.fields == {"q_id": "Q1", "answer": "B"}

    assert parse_action("") is None
    assert parse_action("not-json") is None
    assert parse_action(json.dumps({"no_action_key": 1})) is None


def test_serve_in_process_writes_report(tmp_path: Path) -> None:
    report = tmp_path / "R.md"
    rc = serve(
        "in-process",
        report_path=report,
        wait_for_input=False,
        stdout=io.StringIO(),
        stdin=io.StringIO(),
        pipeline="stub",
    )
    assert rc == 0
    assert report.read_text(encoding="utf-8").startswith("# in-process")


def test_serve_rejects_stub_pipeline_when_live_requested(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MUCHANIPO_REQUIRE_LIVE", "1")
    report = tmp_path / "R.md"
    stdout = io.StringIO()

    rc = serve(
        "live-stub",
        report_path=report,
        wait_for_input=False,
        stdout=stdout,
        stdin=io.StringIO(),
        pipeline="stub",
    )

    events = _parse_lines(stdout.getvalue())
    assert rc == 1
    assert events[-2]["event"] == "error"
    assert events[-2]["kind"] == "live_mode_violation"
    assert events[-1] == {"event": "done", "pipeline": "stub", "aborted": True}
    assert not report.exists()


def test_serve_subcommand_accepts_depth_for_full_pipeline(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict] = []

    def fake_serve(topic, *, report_path, wait_for_input, stdout, stdin, pipeline="full", depth="deep"):
        calls.append(
            {
                "topic": topic,
                "report_path": report_path,
                "wait_for_input": wait_for_input,
                "pipeline": pipeline,
                "depth": depth,
            }
        )
        return 0

    monkeypatch.setattr(server_mod, "serve", fake_serve)

    rc = server_mod.main([
        "serve",
        "--topic",
        "depth bridge",
        "--pipeline",
        "full",
        "--depth",
        "shallow",
        "--report-path",
        str(tmp_path / "R.md"),
        "--no-wait",
    ])

    assert rc == 0
    assert calls == [
        {
            "topic": "depth bridge",
            "report_path": tmp_path / "R.md",
            "wait_for_input": False,
            "pipeline": "full",
            "depth": "shallow",
        }
    ]


def test_serve_subcommand_defaults_to_full_pipeline(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict] = []

    def fake_serve(topic, *, report_path, wait_for_input, stdout, stdin, pipeline="full", depth="deep"):
        calls.append(
            {
                "topic": topic,
                "report_path": report_path,
                "wait_for_input": wait_for_input,
                "pipeline": pipeline,
                "depth": depth,
            }
        )
        return 0

    monkeypatch.setattr(server_mod, "serve", fake_serve)

    rc = server_mod.main([
        "serve",
        "--topic",
        "default full",
        "--report-path",
        str(tmp_path / "R.md"),
        "--no-wait",
    ])

    assert rc == 0
    assert calls == [
        {
            "topic": "default full",
            "report_path": tmp_path / "R.md",
            "wait_for_input": False,
            "pipeline": "full",
            "depth": "deep",
        }
    ]


def test_detect_offline_mode_treats_local_cli_as_online(monkeypatch):
    monkeypatch.delenv("MUCHANIPO_OFFLINE", raising=False)
    monkeypatch.delenv("MUCHANIPO_ONLINE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    monkeypatch.setenv("MUCHANIPO_PREFER_CLI", "1")

    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/claude" if name == "claude" else None)

    assert _detect_offline_mode() is False


def test_detect_offline_mode_treats_opencode_cli_as_online(monkeypatch):
    monkeypatch.delenv("MUCHANIPO_OFFLINE", raising=False)
    monkeypatch.delenv("MUCHANIPO_ONLINE", raising=False)
    monkeypatch.setenv("MUCHANIPO_PREFER_CLI", "1")

    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/opencode" if name == "opencode" else None)

    assert _detect_offline_mode() is False


def test_detect_offline_mode_treats_opencode_api_key_as_online(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("MUCHANIPO_OFFLINE", raising=False)
    monkeypatch.delenv("MUCHANIPO_ONLINE", raising=False)
    monkeypatch.setenv("MUCHANIPO_PREFER_CLI", "0")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "oc-test")

    import shutil

    monkeypatch.setattr(shutil, "which", lambda _name: None)

    assert _detect_offline_mode() is False


def test_detect_offline_mode_can_disable_cli_preference(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_PREFER_CLI", "0")
    monkeypatch.delenv("MUCHANIPO_USE_CLI", raising=False)
    monkeypatch.delenv("ANTHROPIC_USE_CLI", raising=False)
    monkeypatch.delenv("OPENCODE_USE_CLI", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)

    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/claude")

    assert _detect_offline_mode() is True


def test_detect_offline_mode_keeps_pytest_offline_despite_host_keys(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "server-test")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "host-token")
    monkeypatch.delenv("MUCHANIPO_PREFER_CLI", raising=False)
    monkeypatch.delenv("MUCHANIPO_USE_CLI", raising=False)
    monkeypatch.delenv("MUCHANIPO_ONLINE", raising=False)
    monkeypatch.delenv("MUCHANIPO_OFFLINE", raising=False)

    assert _detect_offline_mode() is True
