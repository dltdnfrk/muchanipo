"""Terminal-first Muchanipo runtime.

The Python pipeline is the product core. Tauri can remain a viewer/control
shell, but local personal usage should also work directly from a terminal:

    python3 -m muchanipo run "topic"
    python3 -m muchanipo tui "topic"
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, IO

from src.pipeline.runner import run_pipeline


STAGE_LABELS: dict[str, str] = {
    "intake": "아이디어 접수",
    "interview": "인터뷰 / 요구사항 정리",
    "targeting": "목표 설정 / 연구 지도",
    "research": "자료 수집 / 자동 연구",
    "evidence": "근거 검증 / 지식 정리",
    "council": "Council / 다중 관점 토론",
    "report": "보고서 작성",
    "vault": "학습 축적 / Vault",
    "agents": "에이전트 기록",
    "finalize": "완료",
}

STAGE_ORDER: tuple[str, ...] = tuple(STAGE_LABELS)


@dataclass
class TerminalRunPaths:
    run_id: str
    run_dir: Path
    events_path: Path
    report_path: Path
    summary_path: Path


@dataclass
class TerminalRunResult:
    topic: str
    run_id: str
    report_path: Path
    events_path: Path
    summary_path: Path
    offline: bool | None
    stage_status: dict[str, str] = field(default_factory=dict)


def terminal_run(
    topic: str,
    *,
    stdout: IO[str] | None = None,
    report_path: Path | None = None,
    run_dir: Path | None = None,
    offline: bool | None = None,
    jsonl: bool = False,
    dashboard: bool = False,
) -> TerminalRunResult:
    """Run the full pipeline as a terminal-native command.

    `jsonl=True` preserves the machine-readable event stream for scripts.
    `dashboard=True` redraws a compact terminal dashboard without adding a
    dependency on a TUI framework.
    """
    out = stdout or sys.stdout
    paths = _resolve_paths(topic=topic, run_dir=run_dir, report_path=report_path)
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    events_file = paths.events_path.open("w", encoding="utf-8")
    status = {stage: "pending" for stage in STAGE_ORDER}
    started_at = time.time()

    def emit_terminal(event: dict[str, Any]) -> None:
        _write_event(events_file, event)
        stage = str(event.get("stage") or "")
        if stage in status:
            if event.get("event") == "stage_started":
                status[stage] = "active"
            elif event.get("event") == "stage_completed":
                status[stage] = "done"
        if jsonl:
            out.write(json.dumps(event, ensure_ascii=False) + "\n")
            out.flush()
        elif dashboard:
            _render_dashboard(out, topic=topic, paths=paths, status=status, event=event)
        else:
            _render_plain_event(out, event)

    _write_event(
        events_file,
        {
            "event": "terminal_run_started",
            "topic": topic,
            "run_id": paths.run_id,
            "report_path": str(paths.report_path),
            "events_path": str(paths.events_path),
            "offline": offline,
            "created_at": _now_iso(),
        },
    )
    if not jsonl and not dashboard:
        out.write(f"Muchanipo run started: {topic}\n")
        out.write(f"Run dir: {paths.run_dir}\n")
        out.flush()
    if dashboard:
        _render_dashboard(out, topic=topic, paths=paths, status=status, event=None)

    try:
        result = run_pipeline(topic, progress_callback=emit_terminal, offline=offline)
    except Exception as exc:
        status["finalize"] = "error"
        error_event = {
            "event": "terminal_run_error",
            "topic": topic,
            "run_id": paths.run_id,
            "message": str(exc),
            "error_type": type(exc).__name__,
        }
        _write_event(events_file, error_event)
        if jsonl:
            out.write(json.dumps(error_event, ensure_ascii=False) + "\n")
        else:
            out.write(f"\nERROR: {type(exc).__name__}: {exc}\n")
        out.flush()
        raise
    finally:
        events_file.flush()
        events_file.close()

    report_md = str(result.get("report_md") or "")
    paths.report_path.parent.mkdir(parents=True, exist_ok=True)
    paths.report_path.write_text(report_md, encoding="utf-8")
    summary = {
        "topic": topic,
        "run_id": paths.run_id,
        "report_path": str(paths.report_path),
        "events_path": str(paths.events_path),
        "offline": offline,
        "duration_sec": round(time.time() - started_at, 3),
        "round_count": len(result.get("rounds") or []),
        "brief_id": getattr(result.get("brief"), "id", None),
        "vault_path": str(result.get("vault_path") or ""),
        "completed_at": _now_iso(),
    }
    paths.summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    done_event = {"event": "terminal_run_done", **summary}
    with paths.events_path.open("a", encoding="utf-8") as append_events:
        _write_event(append_events, done_event)
    if jsonl:
        out.write(json.dumps(done_event, ensure_ascii=False) + "\n")
    elif dashboard:
        status.update({stage: "done" for stage in STAGE_ORDER})
        _render_dashboard(out, topic=topic, paths=paths, status=status, event=done_event)
        out.write("\n")
    else:
        out.write(f"Report: {paths.report_path}\n")
        out.write(f"Events: {paths.events_path}\n")
        out.write("Muchanipo run completed.\n")
    out.flush()

    return TerminalRunResult(
        topic=topic,
        run_id=paths.run_id,
        report_path=paths.report_path,
        events_path=paths.events_path,
        summary_path=paths.summary_path,
        offline=offline,
        stage_status=dict(status),
    )


def _resolve_paths(
    *,
    topic: str,
    run_dir: Path | None,
    report_path: Path | None,
) -> TerminalRunPaths:
    run_id = _new_run_id(topic)
    base = run_dir or _default_runs_dir() / run_id
    report = report_path or base / "REPORT.md"
    return TerminalRunPaths(
        run_id=run_id,
        run_dir=base,
        events_path=base / "events.jsonl",
        report_path=report,
        summary_path=base / "summary.json",
    )


def _default_runs_dir() -> Path:
    return Path(os.environ.get("MUCHANIPO_RUNS_DIR", Path.home() / ".local" / "share" / "muchanipo" / "runs"))


def _new_run_id(topic: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in topic).strip("-")
    slug = "-".join(part for part in slug.split("-") if part)[:48] or "run"
    return f"{ts}-{slug}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_event(stream: IO[str], event: dict[str, Any]) -> None:
    stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    stream.flush()


def _render_plain_event(out: IO[str], event: dict[str, Any]) -> None:
    stage = str(event.get("stage") or "")
    if not stage:
        return
    label = STAGE_LABELS.get(stage, stage)
    if event.get("event") == "stage_started":
        out.write(f"[>] {label}\n")
    elif event.get("event") == "stage_completed":
        out.write(f"[✓] {label}\n")
    out.flush()


def _render_dashboard(
    out: IO[str],
    *,
    topic: str,
    paths: TerminalRunPaths,
    status: dict[str, str],
    event: dict[str, Any] | None,
) -> None:
    if hasattr(out, "isatty") and out.isatty():
        out.write("\x1b[2J\x1b[H")
    out.write("Muchanipo Terminal Core\n")
    out.write(f"Topic : {topic}\n")
    out.write(f"Run   : {paths.run_id}\n")
    out.write(f"Report: {paths.report_path}\n\n")
    for stage in STAGE_ORDER:
        marker = {"pending": " ", "active": ">", "done": "✓", "error": "!"}.get(status.get(stage, "pending"), " ")
        out.write(f"[{marker}] {STAGE_LABELS[stage]}\n")
    if event:
        out.write(f"\nLast event: {event.get('event')}")
        if event.get("stage"):
            out.write(f" / {event.get('stage')}")
        out.write("\n")
    out.flush()
