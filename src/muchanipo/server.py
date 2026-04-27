"""`muchanipo serve` — minimal Phase-1 event stream for the native shell.

This is intentionally a stub pipeline: it emits the canonical phase order
(STARTUP → INTERVIEW → COUNCIL → REPORT → done), pauses for one interview
answer over stdin, and writes a placeholder REPORT.md. Real wiring to
council/report runners arrives in Phase 2; for now Worker 2/3/4 only need
the protocol to exercise their UI plumbing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import IO, Sequence

from .events import Action, emit, parse_action


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="muchanipo")
    sub = parser.add_subparsers(dest="command", required=True)

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
    return parser


def _read_action(stdin: IO[str]) -> Action | None:
    line = stdin.readline()
    if not line:
        return None
    return parse_action(line)


def serve(
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
            emit(
                "error",
                stream=stdout,
                message=f"unexpected action: {action.action}",
            )
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
    emit(
        "report_chunk",
        stream=stdout,
        section="executive_summary",
        markdown=body,
    )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(body, encoding="utf-8")

    emit("done", stream=stdout, report_path=str(report_path))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command != "serve":
        parser.error(f"unknown command: {args.command}")

    report_path = Path(args.report_path) if args.report_path else Path.cwd() / "REPORT.md"
    return serve(
        args.topic,
        report_path=report_path,
        wait_for_input=not args.no_wait,
        stdout=sys.stdout,
        stdin=sys.stdin,
    )


if __name__ == "__main__":
    raise SystemExit(main())
