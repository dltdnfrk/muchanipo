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
from src.muchanipo.events import KNOWN_EVENTS, emit
from src.muchanipo.server import serve


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
        ["--topic", "test", "--no-wait", "--report-path", str(report)],
    )
    assert proc.returncode == 0, proc.stderr
    events = _parse_lines(proc.stdout)
    phase_order = [e["phase"] for e in events if e["event"] == "phase_change"]
    assert phase_order == ["STARTUP", "INTERVIEW", "COUNCIL", "REPORT"]
    assert any(e["event"] == "done" for e in events)
    assert report.exists()


def test_serve_every_event_type_is_known(tmp_path: Path) -> None:
    proc = _run_serve(
        ["--topic", "x", "--no-wait", "--report-path", str(tmp_path / "R.md")],
    )
    assert proc.returncode == 0, proc.stderr
    events = _parse_lines(proc.stdout)
    assert events, "expected at least one event line"
    for ev in events:
        assert ev["event"] in KNOWN_EVENTS, f"unknown event: {ev}"


def test_serve_advances_after_interview_answer(tmp_path: Path) -> None:
    answer = json.dumps({"action": "interview_answer", "q_id": "Q1", "answer": "A"})
    proc = _run_serve(
        ["--topic", "wired", "--report-path", str(tmp_path / "R.md")],
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
        ["--topic", "stop", "--report-path", str(tmp_path / "R.md")],
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
    )

    events = _parse_lines(stdout.getvalue())
    assert rc == 1
    assert events[-2]["event"] == "error"
    assert events[-2]["kind"] == "live_mode_violation"
    assert events[-1] == {"event": "done", "pipeline": "stub", "aborted": True}
    assert not report.exists()
