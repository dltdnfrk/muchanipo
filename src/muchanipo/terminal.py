"""Terminal-first Muchanipo runtime.

The Python pipeline is the product core. Tauri can remain a viewer/control
shell, but local personal usage should also work directly from a terminal:

    python3 -m muchanipo run "topic"
    python3 -m muchanipo tui "topic"
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
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


@dataclass
class InterviewCapture:
    original_topic: str
    pipeline_input: str
    mode: str
    answered: int


def terminal_app(
    *,
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
) -> int:
    """Interactive Muchanipo home for `muchanipo` with no arguments."""
    inp = stdin or sys.stdin
    out = stdout or sys.stdout
    _render_home(out)
    while True:
        raw_choice = _read_prompt(inp, out, "muchanipo> ")
        if raw_choice is None:
            out.write("bye\n")
            out.flush()
            return 0
        topic_or_choice = raw_choice.strip()
        choice = topic_or_choice.lower()
        if choice == "":
            _render_home(out)
            continue
        if choice in {"q", "quit", "exit", "5"}:
            out.write("bye\n")
            out.flush()
            return 0
        if choice in {"1", "new", "n"}:
            raw_topic = _read_prompt(inp, out, "topic> ")
            if raw_topic is None:
                out.write("bye\n")
                out.flush()
                return 0
            topic = raw_topic.strip()
            if not topic:
                out.write("topic is required\n")
                out.flush()
                continue
            raw_mode = _read_prompt(inp, out, "mode [auto/offline/online] (auto)> ")
            mode = (raw_mode or "").strip().lower()
            offline = _offline_from_mode(mode)
            _run_from_app(topic, inp=inp, out=out, offline=offline, interview=True)
            _render_home(out)
            continue
        if choice in {"2", "runs", "r"}:
            render_runs(stdout=out)
            continue
        if choice in {"3", "status", "s"}:
            render_cli_status(stdout=out)
            continue
        if choice in {"4", "help", "h", "?"}:
            _render_help(out)
            continue
        _run_from_app(topic_or_choice, inp=inp, out=out, offline=None, interview=True)
        _render_home(out)


def terminal_run(
    topic: str,
    *,
    stdout: IO[str] | None = None,
    report_path: Path | None = None,
    run_dir: Path | None = None,
    offline: bool | None = None,
    jsonl: bool = False,
    dashboard: bool = False,
    pipeline_input: str | None = None,
    require_live: bool = False,
) -> TerminalRunResult:
    """Run the full pipeline as a terminal-native command.

    `jsonl=True` preserves the machine-readable event stream for scripts.
    `dashboard=True` redraws a compact terminal dashboard without adding a
    dependency on a TUI framework.
    """
    out = stdout or sys.stdout
    pipeline_topic = pipeline_input or topic
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
            "require_live": require_live,
            "pipeline_input": pipeline_topic if pipeline_topic != topic else None,
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
        result = run_pipeline(
            pipeline_topic,
            progress_callback=emit_terminal,
            offline=offline,
            require_live=require_live,
        )
    except KeyboardInterrupt as exc:
        status["finalize"] = "error"
        _record_terminal_failure(
            paths=paths,
            events_file=events_file,
            out=out,
            status=status,
            started_at=started_at,
            topic=topic,
            offline=offline,
            jsonl=jsonl,
            dashboard=dashboard,
            require_live=require_live,
            event_name="terminal_run_interrupted",
            error_type="KeyboardInterrupt",
            message="interrupted by user",
        )
        raise exc
    except Exception as exc:
        status["finalize"] = "error"
        _record_terminal_failure(
            paths=paths,
            events_file=events_file,
            out=out,
            status=status,
            started_at=started_at,
            topic=topic,
            offline=offline,
            jsonl=jsonl,
            dashboard=dashboard,
            require_live=require_live,
            event_name="terminal_run_error",
            error_type=type(exc).__name__,
            message=str(exc),
        )
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
        "status": "completed",
        "pipeline_input": pipeline_topic if pipeline_topic != topic else None,
        "report_path": str(paths.report_path),
        "events_path": str(paths.events_path),
        "offline": offline,
        "require_live": require_live,
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


def conduct_interview(
    topic: str,
    *,
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
) -> InterviewCapture:
    """Run the show-me-the-prd style intake interview before research starts."""
    from src.intake.idea_dump import IdeaDump
    from src.intent.interview_prompts import forcing_questions_korean, merge_answers_to_text
    from src.interview.session import InterviewSession

    inp = stdin or sys.stdin
    out = stdout or sys.stdout
    session = InterviewSession.from_idea(IdeaDump(raw_text=topic))
    plan = session.plan
    mode = plan.mode if plan is not None else "deep"
    if mode == "quick":
        questions = session.clarifications_for_quick_mode()
    else:
        questions = forcing_questions_korean()

    out.write("\n아이디어 심층 인터뷰\n")
    out.write("------------------\n")
    out.write("show-me-the-prd 방식으로 요구사항을 먼저 좁힌 뒤 리서치를 시작합니다.\n")
    out.write("빈 줄 또는 'skip'은 해당 질문을 건너뜁니다.\n\n")
    out.flush()

    qa_pairs: list[dict[str, str]] = []
    for idx, item in enumerate(questions, start=1):
        qid = str(item.get("id") or f"Q{idx}")
        question = str(item.get("question") or "").strip()
        out.write(f"{question}\n")
        answer = _read_prompt(inp, out, "answer> ")
        if answer is None:
            out.write("\n인터뷰 입력이 종료되어 현재 답변까지만 반영합니다.\n")
            out.flush()
            break
        cleaned = answer.strip()
        if not cleaned or cleaned.lower() in {"skip", "pass", "건너뛰기"}:
            out.write("skipped\n\n")
            out.flush()
            continue
        label = _interview_answer_label(qid)
        if label:
            session.answer(label, cleaned)
        qa_pairs.append({"id": qid, "answer": cleaned})
        out.write("\n")
        out.flush()

    if not qa_pairs:
        out.write("인터뷰 답변이 없어 원 토픽으로 진행합니다.\n\n")
        out.flush()
        return InterviewCapture(original_topic=topic, pipeline_input=topic, mode=mode, answered=0)

    pipeline_input = merge_answers_to_text(topic, qa_pairs)
    out.write(f"인터뷰 반영 완료: {len(qa_pairs)}개 답변, coverage={session.coverage_score:.2f}\n")
    out.write("이제 리서치 파이프라인을 시작합니다.\n\n")
    out.flush()
    return InterviewCapture(
        original_topic=topic,
        pipeline_input=pipeline_input,
        mode=mode,
        answered=len(qa_pairs),
    )


def _run_from_app(
    topic: str,
    *,
    inp: IO[str],
    out: IO[str],
    offline: bool | None,
    interview: bool,
    require_live: bool = False,
) -> None:
    try:
        capture = conduct_interview(topic, stdin=inp, stdout=out) if interview else None
        terminal_run(
            topic,
            stdout=out,
            offline=offline,
            dashboard=_supports_dashboard(out),
            pipeline_input=capture.pipeline_input if capture else None,
            require_live=require_live,
        )
    except KeyboardInterrupt:
        out.write("\nRun interrupted; returning to Muchanipo home.\n")
        out.flush()
    except Exception as exc:
        out.write(f"\nRun failed; returning to Muchanipo home: {type(exc).__name__}: {exc}\n")
    out.flush()


def _interview_answer_label(qid: str) -> str | None:
    return {
        "Q1_research_question": "research_question",
        "Q2_purpose": "purpose",
        "Q3_context": "context",
        "Q5_deliverable": "deliverable_type",
        "Q6_quality": "quality_bar",
        "clarify_timeframe": "quality_bar",
        "clarify_domain": "context",
        "clarify_evaluation": "quality_bar",
        "clarify_comparison": "context",
    }.get(qid)


def _record_terminal_failure(
    *,
    paths: TerminalRunPaths,
    events_file: IO[str],
    out: IO[str],
    status: dict[str, str],
    started_at: float,
    topic: str,
    offline: bool | None,
    jsonl: bool,
    dashboard: bool,
    require_live: bool,
    event_name: str,
    error_type: str,
    message: str,
) -> None:
    event = {
        "event": event_name,
        "topic": topic,
        "run_id": paths.run_id,
        "message": message,
        "error_type": error_type,
        "created_at": _now_iso(),
    }
    _write_event(events_file, event)
    failure_status = "interrupted" if event_name == "terminal_run_interrupted" else "failed"
    summary = {
        "topic": topic,
        "run_id": paths.run_id,
        "status": failure_status,
        "report_path": str(paths.report_path),
        "events_path": str(paths.events_path),
        "offline": offline,
        "require_live": require_live,
        "duration_sec": round(time.time() - started_at, 3),
        "error_type": error_type,
        "message": message,
        "completed_at": _now_iso(),
    }
    paths.summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if jsonl:
        out.write(json.dumps(event, ensure_ascii=False) + "\n")
    elif dashboard:
        _render_dashboard(out, topic=topic, paths=paths, status=status, event=event)
        out.write("\n")
    elif event_name == "terminal_run_interrupted":
        out.write("\nINTERRUPTED: run stopped by user. Partial artifacts were saved.\n")
    else:
        out.write(f"\nERROR: {error_type}: {message}\n")
        out.write("Partial artifacts were saved.\n")
    out.flush()

def cli_statuses() -> list[dict[str, Any]]:
    """Return installed/version status for local provider CLIs."""
    specs = [
        ("claude", "CLAUDE_BIN", ["--version"]),
        ("codex", "CODEX_BIN", ["--version"]),
        ("gemini", "GEMINI_BIN", ["--version"]),
        ("kimi", "KIMI_BIN", ["--version"]),
        ("opencode", "OPENCODE_BIN", ["--version"]),
    ]
    statuses: list[dict[str, Any]] = []
    for name, env_var, version_args in specs:
        path = _resolve_cli_path(name, env_var)
        record: dict[str, Any] = {
            "name": name,
            "installed": bool(path),
            "path": path,
            "version": None,
            "error": None,
        }
        if path:
            try:
                proc = subprocess.run(
                    [path, *version_args],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                text = (proc.stdout or proc.stderr or "").strip()
                if proc.returncode == 0:
                    record["version"] = text.splitlines()[0] if text else "installed"
                else:
                    record["error"] = _first_error_line(text) or f"exit {proc.returncode}"
            except Exception as exc:  # pragma: no cover - host CLI behavior varies.
                record["error"] = _first_error_line(str(exc))
        statuses.append(record)
    return statuses


def render_cli_status(*, stdout: IO[str] | None = None) -> list[dict[str, Any]]:
    out = stdout or sys.stdout
    statuses = cli_statuses()
    out.write("\nCLI status\n")
    out.write("----------\n")
    for item in statuses:
        marker = "OK" if item["installed"] else "--"
        detail = item.get("version")
        if not detail and item["installed"] and item.get("error"):
            detail = f"installed; version probe failed: {item['error']}"
        detail = detail or "not found"
        path = item.get("path") or "-"
        out.write(f"[{marker}] {item['name']:<8} {detail}\n")
        out.write(f"     {path}\n")
    out.write("\n")
    out.flush()
    return statuses


def list_runs(*, runs_dir: Path | None = None, limit: int = 10) -> list[dict[str, Any]]:
    root = runs_dir or _default_runs_dir()
    if not root.exists():
        return []
    records: list[dict[str, Any]] = []
    for summary_path in root.glob("*/summary.json"):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(summary, dict):
            summary.setdefault("run_dir", str(summary_path.parent))
            records.append(summary)
    records.sort(key=lambda item: str(item.get("completed_at") or item.get("run_id") or ""), reverse=True)
    return records[:limit]


def render_runs(
    *,
    stdout: IO[str] | None = None,
    runs_dir: Path | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    out = stdout or sys.stdout
    records = list_runs(runs_dir=runs_dir, limit=limit)
    out.write("\nRuns\n")
    out.write("----\n")
    if not records:
        out.write("No runs yet.\n\n")
        out.flush()
        return records
    for idx, item in enumerate(records, start=1):
        out.write(f"{idx}. {item.get('topic', '(untitled)')}\n")
        out.write(f"   run: {item.get('run_id', '-')}\n")
        out.write(f"   report: {item.get('report_path', '-')}\n")
    out.write("\n")
    out.flush()
    return records


def _resolve_cli_path(name: str, env_var: str) -> str | None:
    explicit = os.environ.get(env_var)
    if explicit:
        return explicit
    if name == "codex":
        for candidate in ("/opt/homebrew/bin/codex", "/usr/local/bin/codex", shutil.which("codex")):
            if candidate and Path(candidate).exists():
                return candidate
        return None
    return shutil.which(name)


def _first_error_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:160]
    return ""


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


def _render_home(out: IO[str]) -> None:
    out.write("\nMuchanipo\n")
    out.write("---------\n")
    out.write(f"Runs dir: {_default_runs_dir()}\n")
    out.write("Tip: type a topic directly to start research.\n\n")
    out.write("1. New research\n")
    out.write("2. Runs\n")
    out.write("3. CLI status\n")
    out.write("4. Help\n")
    out.write("q. Quit\n\n")
    out.flush()


def _render_help(out: IO[str]) -> None:
    out.write("\nCommands\n")
    out.write("--------\n")
    out.write("muchanipo                         open this terminal app\n")
    out.write("muchanipo \"topic\"                 start a dashboard run\n")
    out.write("muchanipo run \"topic\"             line-by-line run\n")
    out.write("muchanipo tui \"topic\"             dashboard run\n")
    out.write("muchanipo runs                    list previous runs\n")
    out.write("muchanipo status                  show local CLI provider status\n\n")
    out.flush()


def _read_prompt(inp: IO[str], out: IO[str], prompt: str) -> str | None:
    out.write(prompt)
    out.flush()
    line = inp.readline()
    return line if line else None


def _offline_from_mode(mode: str) -> bool | None:
    if mode in {"offline", "off", "mock", "m"}:
        return True
    if mode in {"online", "live", "on", "l"}:
        return False
    return None


def _supports_dashboard(out: IO[str]) -> bool:
    return bool(getattr(out, "isatty", lambda: False)())


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
