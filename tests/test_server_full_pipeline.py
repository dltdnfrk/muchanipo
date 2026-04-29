"""server.py --pipeline=full smoke test (US-TAURI-BRIDGE)."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.muchanipo.server import serve_full, _build_demo_rounds
from src.report.chapter_mapper import ChapterMapper, RoundDigest
from src.report.pyramid_formatter import PyramidFormatter
from src.runtime.live_mode import LiveModeViolation


def _writable_tmp(name: str) -> Path:
    base = os.environ.get("TMPDIR") or "/tmp"
    return Path(base) / name


def test_serve_full_writes_six_chapters_to_report_md(tmp_path):
    report = tmp_path / "REPORT.md"
    stdout = io.StringIO()
    rc = serve_full("딸기 진단키트", report_path=report, stdout=stdout)
    assert rc == 0
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    for n in range(1, 7):
        assert f"## Chapter {n}" in text, f"Chapter {n} missing"


def test_serve_full_emits_all_pipeline_stages(tmp_path):
    stdout = io.StringIO()
    serve_full("test topic", report_path=tmp_path / "R.md", stdout=stdout)
    lines = [l for l in stdout.getvalue().splitlines() if l.strip()]
    events = [json.loads(l) for l in lines]
    stage_events = [e for e in events if e["event"] == "stage_started"]
    stages = [e["stage"] for e in stage_events]
    assert stages == [
        "intake", "interview", "targeting",
        "research", "evidence", "council",
        "report", "finalize",
    ]


def test_serve_full_emits_ten_council_rounds(tmp_path):
    stdout = io.StringIO()
    serve_full("topic", report_path=tmp_path / "R.md", stdout=stdout)
    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    starts = [e for e in events if e["event"] == "council_round_start"]
    assert len(starts) == 10
    assert [e["round"] for e in starts] == list(range(1, 11))


def test_serve_full_emits_six_report_chunks(tmp_path):
    stdout = io.StringIO()
    serve_full("topic", report_path=tmp_path / "R.md", stdout=stdout)
    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    chunks = [e for e in events if e["event"] == "report_chunk"]
    assert len(chunks) == 6
    assert [c["chapter_no"] for c in chunks] == [1, 2, 3, 4, 5, 6]


def test_serve_full_emits_final_report_event_with_markdown(tmp_path):
    stdout = io.StringIO()
    serve_full("topic", report_path=tmp_path / "R.md", stdout=stdout)
    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    finals = [e for e in events if e["event"] == "final_report"]
    assert len(finals) == 1
    assert finals[0]["chapter_count"] == 6
    assert "## Chapter 1" in finals[0]["markdown"]
    assert "## Chapter 6" in finals[0]["markdown"]


def test_serve_full_emits_done_at_end(tmp_path):
    stdout = io.StringIO()
    serve_full("topic", report_path=tmp_path / "R.md", stdout=stdout)
    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    assert events[-1]["event"] == "done"
    assert events[-1]["pipeline"] == "full"


def test_serve_full_emits_terminal_error_on_live_mode_violation(tmp_path, monkeypatch):
    import src.pipeline.runner as runner_mod

    def fail_live(*args, **kwargs):
        raise LiveModeViolation("live evidence missing")

    monkeypatch.setattr(runner_mod, "run_pipeline", fail_live)
    stdout = io.StringIO()

    rc = serve_full("topic", report_path=tmp_path / "R.md", stdout=stdout)

    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    assert rc == 1
    assert events[-2]["event"] == "error"
    assert events[-2]["kind"] == "live_mode_violation"
    assert "live evidence missing" in events[-2]["message"]
    assert events[-1] == {"event": "done", "pipeline": "full", "aborted": True}
    assert not (tmp_path / "R.md").exists()


def test_demo_rounds_produce_full_six_chapter_mapping():
    rounds = _build_demo_rounds("test topic")
    chapters = ChapterMapper().map(rounds)
    formatted = PyramidFormatter().reorder_all(chapters)
    assert len(formatted) == 6
    assert formatted[0].title == "Executive Summary"
    # SCR present in chapter 1
    assert formatted[0].scr is not None
    assert formatted[0].scr["situation"]
    assert formatted[0].scr["complication"]
    assert formatted[0].scr["resolution"]


def test_serve_subcommand_dispatches_to_full_pipeline_via_cli(tmp_path):
    """python -m muchanipo serve --pipeline full 으로 호출 시에도 동작."""
    report = _writable_tmp("smoke_report.md")
    proc = subprocess.run(
        [
            sys.executable, "-m", "muchanipo", "serve",
            "--topic", "smoke topic",
            "--pipeline", "full",
            "--report-path", str(report),
            "--no-wait",
        ],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    text = report.read_text(encoding="utf-8")
    for n in range(1, 7):
        assert f"## Chapter {n}" in text
    report.unlink(missing_ok=True)
