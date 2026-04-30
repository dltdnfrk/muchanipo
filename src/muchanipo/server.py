"""Muchanipo command line entrypoint.

Modes:
    run
        Terminal-first full pipeline runner. Writes a report, event log, and
        summary under the local runs directory.
    tui
        Terminal dashboard wrapper around the same full pipeline core.
    --pipeline=stub  (default, legacy)
        Emits the canonical phase order (STARTUP → INTERVIEW → COUNCIL → REPORT
        → done) with placeholder council/report content.
    --pipeline=full
        PRD-v2 §2.1 8-stage pipeline:
        intake → interview → targeting → research → evidence → council →
        report → finalize. Council generates 10 RoundDigest entries; report
        composes a real MBB 6-chapter document via ChapterMapper +
        PyramidFormatter and writes it to REPORT.md.

Both modes use offline mock LLM providers (no network) so the Tauri shell
can be exercised end-to-end without API keys.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, IO, List, Sequence

from .events import Action, emit, parse_action


# ---- argparse ------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="muchanipo")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the full local CLI-first pipeline in the terminal")
    run.add_argument("topic_arg", nargs="?", help="Research topic")
    run.add_argument("--topic", dest="topic_opt", help="Research topic")
    run.add_argument(
        "--report-path",
        default=None,
        help="Where to write the final REPORT.md (defaults to the run directory)",
    )
    run.add_argument(
        "--run-dir",
        default=None,
        help="Run artifact directory (defaults to ~/.local/share/muchanipo/runs/<run-id>)",
    )
    run.add_argument("--jsonl", action="store_true", help="Print machine-readable JSONL progress")
    run.add_argument("--offline", action="store_true", help="Force deterministic offline/mock providers")
    run.add_argument("--online", action="store_true", help="Force live CLI/API provider detection")
    run.add_argument("--interview", action="store_true", help="Ask the PRD intake interview before running")
    run.add_argument("--no-interview", action="store_true", help="Skip the PRD intake interview")

    tui = sub.add_parser("tui", help="Run the terminal dashboard over the full pipeline")
    tui.add_argument("topic_arg", nargs="?", help="Research topic")
    tui.add_argument("--topic", dest="topic_opt", help="Research topic")
    tui.add_argument(
        "--report-path",
        default=None,
        help="Where to write the final REPORT.md (defaults to the run directory)",
    )
    tui.add_argument(
        "--run-dir",
        default=None,
        help="Run artifact directory (defaults to ~/.local/share/muchanipo/runs/<run-id>)",
    )
    tui.add_argument("--plain", action="store_true", help="Disable dashboard redraw; print line-by-line")
    tui.add_argument("--offline", action="store_true", help="Force deterministic offline/mock providers")
    tui.add_argument("--online", action="store_true", help="Force live CLI/API provider detection")
    tui.add_argument("--interview", action="store_true", help="Ask the PRD intake interview before running")
    tui.add_argument("--no-interview", action="store_true", help="Skip the PRD intake interview")

    runs = sub.add_parser("runs", help="List recent terminal runs")
    runs.add_argument("--limit", type=int, default=10, help="Maximum runs to show")

    sub.add_parser("status", help="Show local provider CLI status")

    serve = sub.add_parser("serve", help="Stream JSON-line events to stdout")
    serve.add_argument("--topic", required=True, help="Research topic")
    serve.add_argument(
        "--report-path",
        default=None,
        help="Where to write the final REPORT.md (defaults to ./REPORT.md)",
    )
    serve.add_argument(
        "--no-wait",
        action="store_true",
        help="Skip waiting for stdin (for smoke tests / piping)",
    )
    serve.add_argument(
        "--pipeline",
        choices=("stub", "full"),
        default="stub",
        help="stub = legacy 4-phase placeholder, full = PRD-v2 §2.1 8-stage MBB pipeline",
    )
    return parser


def _read_action(stdin: IO[str]) -> Action | None:
    line = stdin.readline()
    if not line:
        return None
    return parse_action(line)


# ---- stub pipeline (legacy, kept for back-compat tests) ------------------


def serve_stub(
    topic: str,
    *,
    report_path: Path,
    wait_for_input: bool,
    stdout: IO[str],
    stdin: IO[str],
) -> int:
    emit("phase_change", phase="STARTUP", stream=stdout, data={"topic": topic})

    emit("phase_change", phase="INTERVIEW", stream=stdout)
    emit(
        "interview_question",
        stream=stdout,
        data={
            "q_id": "Q1",
            "text": f"What outcome do you want from researching '{topic}'?",
            "options": ["A. ship a product", "B. write a report", "C. learn"],
        },
    )

    if wait_for_input:
        action = _read_action(stdin)
        if action is None:
            emit("error", stream=stdout, message="no interview answer received")
            return 1
        if action.action == "abort":
            emit("done", stream=stdout, report_path=None, aborted=True)
            return 0
        if action.action != "interview_answer":
            emit("error", stream=stdout, message=f"unexpected action: {action.action}")
            return 1

    emit("phase_change", phase="COUNCIL", stream=stdout)
    layers = [
        (1, "L1_intent"),
        (2, "L2_market"),
        (3, "L3_customer_jtbd"),
    ]
    for round_no, layer in layers:
        emit("council_round_start", stream=stdout, round=round_no, layer=layer)
        emit(
            "council_persona_token",
            stream=stdout,
            persona="이준혁",
            delta=f"[{layer}] preliminary signal…",
        )
        emit("council_round_done", stream=stdout, round=round_no, score=70 + round_no)

    emit("phase_change", phase="REPORT", stream=stdout)
    body = (
        f"# {topic}\n\n"
        "## Executive Summary\n\n"
        "Phase-1 stub report. Real council synthesis lands in Phase 2.\n"
    )
    emit("report_chunk", stream=stdout, section="executive_summary", markdown=body)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(body, encoding="utf-8")

    emit("done", stream=stdout, report_path=str(report_path))
    return 0


# ---- full pipeline (PRD-v2 §2.1) ----------------------------------------


PIPELINE_STAGES: Sequence[str] = (
    "intake",
    "interview",
    "targeting",
    "research",
    "evidence",
    "council",
    "report",
    "finalize",
)


def _build_demo_rounds(topic: str) -> list:
    """10 round 다이제스트 fixture — 실제 LLM 없이 6 chapter 생성용 시드.

    real council session이 wired되면 그 결과로 대체.
    """
    from src.report.chapter_mapper import RoundDigest

    return [
        RoundDigest(
            "L1_market_sizing",
            "시장 규모",
            f"'{topic}' 관련 국내 TAM 약 5조원, 연 22% CAGR",
            confidence=0.85,
            body_claims=[
                "국내 시장 규모 5조원 (KIET 2026 추정)",
                "연 평균 성장률 22%",
            ],
        ),
        RoundDigest(
            "L2_competition",
            "경쟁 환경",
            f"'{topic}' 시장의 5 forces 강도는 '보통'",
            confidence=0.7,
            body_claims=[
                "신규 진입 위협: 보통",
                "공급자 협상력: 낮음",
                "대체재 위협: 높음",
            ],
            framework="Porter",
        ),
        RoundDigest(
            "L3_jtbd",
            "JTBD",
            "사용자 핵심 JTBD: '빠르고 신뢰할 수 있는 결과'",
            confidence=0.8,
            body_claims=[
                "Functional: 정확도 + 속도",
                "Emotional: 안심 + 통제감",
                "Social: 동료 대비 우위",
            ],
            framework="JTBD",
        ),
        RoundDigest(
            "L4_finance",
            "재무 모델",
            "LTV/CAC = 3.5, payback 9개월",
            confidence=0.85,
            body_claims=[
                "Gross margin 65%",
                "단위 경제: payback 9 months",
                "초기 12개월 손익분기점 도달 가능",
            ],
        ),
        RoundDigest(
            "L5_risk",
            "리스크",
            "주요 리스크: 규제 + 공급망",
            confidence=0.6,
            body_claims=[
                "식약처/규제 신고 부담",
                "원자재 공급망 단일 의존도",
                "환불/교환 정책 미비",
            ],
        ),
        RoundDigest(
            "L6_roadmap",
            "실행 로드맵",
            "90일 MVP 출시 계획",
            confidence=0.75,
            body_claims=[
                "30일: alpha (내부 테스트)",
                "60일: beta (10 농가 파일럿)",
                "90일: 정식 출시 (KOL 확보)",
            ],
        ),
        RoundDigest(
            "L7_governance",
            "거버넌스",
            "주1회 KPI 리뷰 + 월1회 보드 보고",
            confidence=0.5,
            body_claims=[
                "주간 운영 미팅",
                "월간 보드 KPI 리뷰",
            ],
        ),
        RoundDigest(
            "L8_kpi",
            "KPI 트리",
            "North Star = MAU + retention D30",
            confidence=0.7,
            body_claims=[
                "Weekly active users",
                "30일 retention",
                "Net Promoter Score",
            ],
        ),
        RoundDigest(
            "L9_dissent",
            "반론",
            "소수 의견: TAM 과대 추정 가능",
            confidence=0.4,
            body_claims=[
                "표본 편향 — 실제 지불의향 검증 부족",
                "성장률 22%의 베이스라인 신뢰도 낮음",
            ],
        ),
        RoundDigest(
            "L10_executive_synthesis",
            "Executive Synthesis",
            "권고: Go (단, 90일 후 KPI 재검토)",
            confidence=0.85,
            body_claims=[
                f"국내 시장 5조원, 22% CAGR — '{topic}' 진입 매력적",
                "기존 솔루션 정확도 한계 + 규제 리스크 존재",
                "MVP 90일 출시 + 권고: Go (KPI 재검토 게이트)",
            ],
        ),
    ]


def _render_chapter_markdown(chapter) -> str:
    lines: List[str] = []
    lines.append(f"## Chapter {chapter.chapter_no}: {chapter.title}\n")
    lines.append(f"**{chapter.lead_claim}**\n")
    if chapter.scr:
        for key in ("situation", "complication", "resolution"):
            txt = chapter.scr.get(key, "").strip()
            if txt:
                lines.append(f"- _{key.title()}_: {txt}")
        lines.append("")
    if chapter.body_claims:
        for c in chapter.body_claims:
            if c.startswith(("[Situation]", "[Complication]", "[Resolution]")):
                continue  # SCR 블록은 위에서 이미 표시
            lines.append(f"- {c}")
        lines.append("")
    if chapter.framework:
        lines.append(f"_Framework: {chapter.framework}_\n")
    if chapter.source_layers:
        lines.append(f"_Sources: {', '.join(chapter.source_layers)}_\n")
    return "\n".join(lines)


def _detect_offline_mode() -> bool:
    """Decide whether to run the pipeline against mock providers.

    Online iff: (a) a local LLM CLI binary is available and CLI preference has
    not been disabled, OR (b) any provider API key is present in the
    environment. Otherwise fall back to offline mocks so the pipeline still
    produces a placeholder report instead of crashing.
    """
    import os
    import shutil

    if os.environ.get("MUCHANIPO_OFFLINE", "").strip().lower() in ("1", "true", "yes"):
        return True
    if os.environ.get("MUCHANIPO_ONLINE", "").strip().lower() in ("1", "true", "yes"):
        return False

    true_values = ("1", "true", "yes", "on")
    running_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    explicit_cli_preference = os.environ.get("MUCHANIPO_PREFER_CLI")
    default_prefer_cli = "0" if running_pytest else "1"
    prefer_cli = os.environ.get("MUCHANIPO_PREFER_CLI", default_prefer_cli).strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    cli_global = os.environ.get("MUCHANIPO_USE_CLI", "").strip().lower() in true_values
    provider_cli_requested = any(
        os.environ.get(flag, "").strip().lower() in true_values
        for flag in ("ANTHROPIC_USE_CLI", "GEMINI_USE_CLI", "KIMI_USE_CLI", "CODEX_USE_CLI")
    )
    if running_pytest and explicit_cli_preference is None and not cli_global and not provider_cli_requested:
        return True
    cli_pairs = [
        ("ANTHROPIC_USE_CLI", "CLAUDE_BIN", "claude"),
        ("GEMINI_USE_CLI", "GEMINI_BIN", "gemini"),
        ("KIMI_USE_CLI", "KIMI_BIN", "kimi"),
        ("CODEX_USE_CLI", "CODEX_BIN", "codex"),
    ]
    for use_flag, bin_var, bin_name in cli_pairs:
        local_flag = os.environ.get(use_flag, "").strip().lower() in true_values
        if not (prefer_cli or cli_global or local_flag):
            continue
        explicit = os.environ.get(bin_var)
        if explicit and os.path.exists(explicit):
            return False
        if shutil.which(bin_name):
            return False
    for key in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "KIMI_API_KEY",
        "MOONSHOT_API_KEY",
    ):
        if os.environ.get(key):
            return False
    return True


def serve_full(
    topic: str,
    *,
    report_path: Path,
    stdout: IO[str],
) -> int:
    """PRD-v2 §2.1 full pipeline — uses real LLM providers when configured."""
    from src.pipeline.runner import run_pipeline
    from src.report.chapter_mapper import ChapterMapper
    from src.report.pyramid_formatter import PyramidFormatter

    offline = _detect_offline_mode()
    emit(
        "phase_change",
        phase="STARTUP",
        stream=stdout,
        data={"topic": topic, "pipeline": "full", "offline": offline},
    )

    def emit_progress(event: dict[str, Any]) -> None:
        name = str(event.get("event") or "")
        fields = {key: value for key, value in event.items() if key != "event"}
        if name == "stage_started":
            emit("phase_change", phase=str(fields.get("stage", "")).upper(), stream=stdout, data={"stage": fields.get("stage")})
        emit(name, stream=stdout, **fields)

    try:
        pipeline_result = run_pipeline(topic, progress_callback=emit_progress, offline=offline)
    except Exception as exc:
        from src.runtime.live_mode import LiveModeViolation

        if not isinstance(exc, LiveModeViolation):
            raise
        emit(
            "error",
            stream=stdout,
            kind="live_mode_violation",
            message=str(exc),
            pipeline="full",
        )
        emit("done", stream=stdout, pipeline="full", aborted=True)
        return 1
    rounds = pipeline_result["rounds"]

    for round_no, digest in enumerate(rounds, start=1):
        emit("council_round_start", stream=stdout, round=round_no, layer=digest.layer_id)
        emit(
            "council_persona_token",
            stream=stdout,
            persona="agent",
            delta=digest.key_claim,
        )
        emit("council_round_done", stream=stdout, round=round_no, score=round(digest.confidence * 100))

    chapters = ChapterMapper().map(rounds)
    chapters = PyramidFormatter().reorder_all(chapters)

    md_parts: List[str] = [f"# {topic}\n"]
    for ch in chapters:
        chunk_md = _render_chapter_markdown(ch)
        md_parts.append(chunk_md)
        emit(
            "report_chunk",
            stream=stdout,
            chapter_no=ch.chapter_no,
            title=ch.title,
            markdown=chunk_md,
            source_layers=list(ch.source_layers),
        )

    final_md = str(pipeline_result.get("report_md") or "\n".join(md_parts))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(final_md, encoding="utf-8")

    emit(
        "final_report",
        stream=stdout,
        report_path=str(report_path),
        chapter_count=len(chapters),
        markdown=final_md,
    )
    emit("done", stream=stdout, report_path=str(report_path), pipeline="full")
    return 0


# ---- entrypoint ---------------------------------------------------------


def serve(
    topic: str,
    *,
    report_path: Path,
    wait_for_input: bool,
    stdout: IO[str],
    stdin: IO[str],
    pipeline: str = "stub",
) -> int:
    if pipeline == "full":
        return serve_full(topic, report_path=report_path, stdout=stdout)
    from src.runtime.live_mode import live_requested_from_env

    if live_requested_from_env():
        emit(
            "error",
            stream=stdout,
            kind="live_mode_violation",
            message="live mode does not allow the legacy stub pipeline; use --pipeline=full",
            pipeline="stub",
        )
        emit("done", stream=stdout, pipeline="stub", aborted=True)
        return 1
    return serve_stub(
        topic,
        report_path=report_path,
        wait_for_input=wait_for_input,
        stdout=stdout,
        stdin=stdin,
    )


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if not raw_argv:
        from src.muchanipo.terminal import terminal_app

        try:
            return terminal_app(stdin=sys.stdin, stdout=sys.stdout)
        except KeyboardInterrupt:
            sys.stderr.write("muchanipo: interrupted\n")
            return 130

    known_commands = {"run", "tui", "serve", "runs", "status"}
    if raw_argv[0] not in known_commands and not raw_argv[0].startswith("-"):
        topic, shortcut_options = _parse_topic_shortcut(raw_argv)
        if not topic:
            sys.stderr.write("muchanipo: topic is required\n")
            return 2
        if shortcut_options["error"]:
            sys.stderr.write(f"muchanipo: {shortcut_options['error']}\n")
            return 2
        return _run_terminal_safely(
            topic,
            report_path=shortcut_options["report_path"],
            run_dir=shortcut_options["run_dir"],
            offline=shortcut_options["offline"],
            jsonl=shortcut_options["jsonl"],
            dashboard=shortcut_options["dashboard"],
            interview=shortcut_options["interview"],
        )

    parser = _build_parser()
    args = parser.parse_args(raw_argv)
    if args.command in {"run", "tui"}:
        topic = (args.topic_opt or args.topic_arg or "").strip()
        if not topic:
            parser.error(f"{args.command} requires a topic")
        if args.offline and args.online:
            parser.error("--offline and --online are mutually exclusive")
        if args.interview and args.no_interview:
            parser.error("--interview and --no-interview are mutually exclusive")
        offline = True if args.offline else False if args.online else None
        default_interview = _default_interview_enabled(jsonl=bool(getattr(args, "jsonl", False)))
        interview = True if args.interview else False if args.no_interview else default_interview
        return _run_terminal_safely(
            topic,
            report_path=Path(args.report_path) if args.report_path else None,
            run_dir=Path(args.run_dir) if args.run_dir else None,
            offline=offline,
            jsonl=bool(getattr(args, "jsonl", False)),
            dashboard=(args.command == "tui" and not getattr(args, "plain", False)),
            interview=interview,
        )

    if args.command == "runs":
        from src.muchanipo.terminal import render_runs

        render_runs(stdout=sys.stdout, limit=max(1, args.limit))
        return 0

    if args.command == "status":
        from src.muchanipo.terminal import render_cli_status

        render_cli_status(stdout=sys.stdout)
        return 0

    if args.command != "serve":
        parser.error(f"unknown command: {args.command}")

    report_path = Path(args.report_path) if args.report_path else Path.cwd() / "REPORT.md"
    return serve(
        args.topic,
        report_path=report_path,
        wait_for_input=not args.no_wait,
        stdout=sys.stdout,
        stdin=sys.stdin,
        pipeline=args.pipeline,
    )


def _run_terminal_safely(
    topic: str,
    *,
    report_path: Path | None,
    run_dir: Path | None,
    offline: bool | None,
    jsonl: bool,
    dashboard: bool,
    interview: bool,
) -> int:
    from src.muchanipo.terminal import conduct_interview, terminal_run

    try:
        capture = (
            conduct_interview(topic, stdin=sys.stdin, stdout=sys.stdout)
            if interview
            else None
        )
        terminal_run(
            topic,
            stdout=sys.stdout,
            report_path=report_path,
            run_dir=run_dir,
            offline=offline,
            jsonl=jsonl,
            dashboard=dashboard,
            pipeline_input=capture.pipeline_input if capture else None,
        )
        return 0
    except KeyboardInterrupt:
        sys.stderr.write("muchanipo: interrupted\n")
        return 130
    except Exception as exc:
        sys.stderr.write(f"muchanipo: run failed: {type(exc).__name__}: {exc}\n")
        return 1


def _parse_topic_shortcut(argv: Sequence[str]) -> tuple[str, dict[str, Any]]:
    topic_parts: list[str] = []
    options: dict[str, Any] = {
        "offline": None,
        "run_dir": None,
        "report_path": None,
        "jsonl": False,
        "dashboard": bool(getattr(sys.stdout, "isatty", lambda: False)()),
        "interview": _default_interview_enabled(jsonl=False),
        "error": "",
    }
    idx = 0
    while idx < len(argv):
        arg = argv[idx]
        if arg == "--offline":
            if options["offline"] is False:
                options["error"] = "--offline and --online are mutually exclusive"
                break
            options["offline"] = True
        elif arg == "--online":
            if options["offline"] is True:
                options["error"] = "--offline and --online are mutually exclusive"
                break
            options["offline"] = False
        elif arg == "--jsonl":
            options["jsonl"] = True
            options["dashboard"] = False
            if "--interview" not in argv:
                options["interview"] = False
        elif arg == "--plain":
            options["dashboard"] = False
        elif arg == "--interview":
            if "--no-interview" in argv:
                options["error"] = "--interview and --no-interview are mutually exclusive"
                break
            options["interview"] = True
        elif arg == "--no-interview":
            if "--interview" in argv:
                options["error"] = "--interview and --no-interview are mutually exclusive"
                break
            options["interview"] = False
        elif arg in {"--run-dir", "--report-path"}:
            if idx + 1 >= len(argv):
                options["error"] = f"{arg} requires a value"
                break
            value = Path(argv[idx + 1])
            if arg == "--run-dir":
                options["run_dir"] = value
            else:
                options["report_path"] = value
            idx += 1
        elif arg.startswith("--"):
            options["error"] = f"unknown shortcut option: {arg}"
            break
        else:
            topic_parts.append(arg)
        idx += 1
    return " ".join(topic_parts).strip(), options


def _default_interview_enabled(*, jsonl: bool) -> bool:
    if jsonl:
        return False
    return bool(getattr(sys.stdin, "isatty", lambda: False)())


if __name__ == "__main__":
    raise SystemExit(main())
