"""Muchanipo command line entrypoint.

Modes:
    demo
        Deterministic offline sample run. Writes the same report, event log,
        and summary artifacts as a normal run without asking interview
        questions or requiring provider credentials.
    run
        Terminal-first full pipeline runner. Writes a report, event log, and
        summary under the local runs directory.
    tui
        Terminal dashboard wrapper around the same full pipeline core.
    --pipeline=stub  (legacy)
        Emits the canonical phase order (STARTUP → INTERVIEW → COUNCIL → REPORT
        → done) with placeholder council/report content.
    --pipeline=full  (default)
        PRD-v2 §2.1 8-stage pipeline:
        intake → interview → targeting → research → evidence → council →
        report → finalize. Council generates 10 RoundDigest entries; report
        composes a real MBB 6-chapter document via ChapterMapper +
        PyramidFormatter and writes it to REPORT.md.

Offline mode and demo use mock providers so the CLI/TUI and Tauri shell can be
exercised end-to-end without API keys. Online mode requires provider CLIs or
API credentials and fails closed when live providers are requested but absent.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, IO, List, Sequence

from .events import Action, emit, parse_action
from src.research.depth import VALID_DEPTHS


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
    run.add_argument("--depth", choices=VALID_DEPTHS, default="deep", help="Autoresearch depth budget")
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
    tui.add_argument("--depth", choices=VALID_DEPTHS, default="deep", help="Autoresearch depth budget")
    tui.add_argument("--interview", action="store_true", help="Ask the PRD intake interview before running")
    tui.add_argument("--no-interview", action="store_true", help="Skip the PRD intake interview")

    runs = sub.add_parser("runs", help="List recent terminal runs")
    runs.add_argument("--limit", type=int, default=10, help="Maximum runs to show")
    runs.add_argument("--json", action="store_true", help="Print run summaries as JSON")

    status = sub.add_parser("status", help="Show local provider CLI status")
    status.add_argument("--json", action="store_true", help="Print provider CLI status as JSON")
    status.add_argument(
        "--probe",
        action="store_true",
        help="Run opt-in real prompt probes against installed provider CLIs",
    )

    doctor = sub.add_parser("doctor", help="Check local runtime readiness")
    doctor.add_argument("--json", action="store_true", help="Print readiness checks as JSON")

    contracts = sub.add_parser("contracts", help="Show stable CLI JSON output contracts")
    contracts.add_argument("--json", action="store_true", help="Print JSON contracts as JSON")

    references = sub.add_parser("references", help="Show reference-project runtime readiness")
    references.add_argument("--json", action="store_true", help="Print reference readiness as JSON")

    orchestrate = sub.add_parser("orchestrate", help="Show/manage tmux operator and worker orchestration")
    orchestrate.add_argument("--session", default="muni", help="tmux session name (default: muni)")
    orchestrate.add_argument("--json", action="store_true", help="Print orchestration status as JSON")
    orchestrate.add_argument("--include-capture", action="store_true", help="Include recent capture-pane output")
    orchestrate.add_argument("--cleanup-workers", action="store_true", help="Kill worker windows 1-4 after completion")
    orchestrate.add_argument("--dry-run", action="store_true", help="Show cleanup actions without killing windows")
    orchestrate.add_argument("--force", action="store_true", help="Required for destructive worker-window cleanup")

    demo = sub.add_parser("demo", help="Run a deterministic offline demo topic")
    demo.add_argument(
        "--report-path",
        default=None,
        help="Where to write the final REPORT.md (defaults to the run directory)",
    )
    demo.add_argument(
        "--run-dir",
        default=None,
        help="Run artifact directory (defaults to ~/.local/share/muchanipo/runs/<run-id>)",
    )
    demo.add_argument("--jsonl", action="store_true", help="Print machine-readable JSONL progress")
    demo.add_argument("--plain", action="store_true", help="Disable dashboard redraw; print line-by-line")
    demo.add_argument("--offline", action="store_true", help="Accepted for symmetry; demo always runs offline")
    demo.add_argument("--depth", choices=VALID_DEPTHS, default="shallow", help="Demo depth budget")

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
        default="full",
        help="full = PRD-v2 §2.1 8-stage MBB pipeline (default), stub = legacy 4-phase placeholder",
    )
    serve.add_argument("--depth", choices=VALID_DEPTHS, default="deep", help="Autoresearch depth budget")
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
        for flag in (
            "ANTHROPIC_USE_CLI",
            "GEMINI_USE_CLI",
            "KIMI_USE_CLI",
            "CODEX_USE_CLI",
            "OPENCODE_USE_CLI",
        )
    )
    if running_pytest and explicit_cli_preference is None and not cli_global and not provider_cli_requested:
        return True
    cli_pairs = [
        ("ANTHROPIC_USE_CLI", "CLAUDE_BIN", "claude"),
        ("GEMINI_USE_CLI", "GEMINI_BIN", "gemini"),
        ("KIMI_USE_CLI", "KIMI_BIN", "kimi"),
        ("CODEX_USE_CLI", "CODEX_BIN", "codex"),
        ("OPENCODE_USE_CLI", "OPENCODE_BIN", "opencode"),
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
        "OPENCODE_API_KEY",
        "OPENCODE_GO_API_KEY",
    ):
        if os.environ.get(key):
            return False
    return True


@dataclass(frozen=True)
class ServeInterviewResult:
    status: str
    topic: str | None = None
    message: str = ""


class JSONLineHITLAdapter:
    """Interactive HITL adapter for the Tauri/serve JSON-line protocol."""

    mode = "jsonline"

    def __init__(self, *, stdout: IO[str], stdin: IO[str]) -> None:
        self.stdout = stdout
        self.stdin = stdin

    def gate(self, gate_name: str, payload: dict) -> Any:
        from src.hitl.plannotator_adapter import HITLResult

        emit(
            "hitl_gate",
            stream=self.stdout,
            gate=gate_name,
            title=_hitl_gate_title(gate_name),
            prompt=_hitl_gate_prompt(gate_name),
            preview=_hitl_gate_preview(gate_name, payload),
            options=[
                {
                    "key": "approve",
                    "label": "승인하고 계속",
                    "value": "approved",
                    "description": "현재 계획/근거를 승인하고 다음 단계로 진행합니다.",
                },
                {
                    "key": "changes",
                    "label": "수정 필요",
                    "value": "changes_requested",
                    "description": "이 실행은 중단하고 보완이 필요하다고 표시합니다.",
                },
            ],
            data={
                "gate": gate_name,
                "payload": _jsonable_payload(payload),
            },
        )
        while True:
            action = _read_action(self.stdin)
            if action is None:
                return HITLResult(
                    status="pending",
                    comments=[f"no HITL decision received for {gate_name}"],
                    gate_id=f"{gate_name}-jsonline",
                )
            if action.action == "abort":
                return HITLResult(
                    status="changes_requested",
                    comments=[f"aborted during HITL gate: {gate_name}"],
                    gate_id=f"{gate_name}-jsonline",
                )
            if action.action != "hitl_decision":
                emit(
                    "warning",
                    stream=self.stdout,
                    message=f"ignoring unexpected action while waiting for HITL gate {gate_name}: {action.action}",
                )
                continue

            requested_gate = str(action.fields.get("gate") or action.fields.get("gate_name") or gate_name)
            if requested_gate != gate_name:
                emit(
                    "warning",
                    stream=self.stdout,
                    message=f"ignoring HITL decision for {requested_gate}; waiting for {gate_name}",
                )
                continue
            status = str(action.fields.get("status") or "pending").strip()
            if status not in {"approved", "changes_requested"}:
                status = "pending"
            return HITLResult(
                status=status,
                comments=[str(action.fields.get("comment") or f"jsonline decision: {status}")],
                gate_id=f"{gate_name}-jsonline",
                synthetic=False,
            )

    def gate_brief(self, brief: Any) -> Any:
        return self.gate("brief", {"brief": _jsonable_payload(brief)})

    def gate_evidence(self, evidence_refs: Any) -> Any:
        return self.gate("evidence", {"evidence_refs": _jsonable_payload(evidence_refs)})

    def gate_report(self, report_md: str) -> Any:
        return self.gate("report", {"report_md": str(report_md)})


def _jsonable_payload(payload: Any) -> Any:
    try:
        return json.loads(json.dumps(payload, ensure_ascii=False, default=_json_default))
    except TypeError:
        return str(payload)


def _json_default(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "to_ontology"):
        return value.to_ontology()
    if hasattr(value, "to_brief"):
        return value.to_brief()
    if hasattr(value, "__dict__"):
        return vars(value)
    return str(value)


def _hitl_gate_title(gate_name: str) -> str:
    return {
        "plan": "리서치 계획 승인",
        "brief": "타겟팅/브리프 승인",
        "evidence": "수집 근거 승인",
        "report": "최종 보고서 승인",
    }.get(gate_name, f"{gate_name} 승인")


def _hitl_gate_prompt(gate_name: str) -> str:
    return {
        "plan": "타겟팅과 리서치를 시작하기 전에 계획을 승인해야 합니다.",
        "brief": "생성된 브리프와 타겟팅 범위를 승인해야 리서치로 넘어갑니다.",
        "evidence": "수집된 근거를 승인해야 심의와 보고서 작성으로 넘어갑니다.",
        "report": "최종 보고서를 저장하기 전에 승인해야 합니다.",
    }.get(gate_name, "계속 진행하려면 승인하세요.")


def _hitl_gate_preview(gate_name: str, payload: dict) -> str:
    payload = _jsonable_payload(payload)
    if gate_name == "plan" and isinstance(payload, dict):
        plan = payload.get("consensus_plan") or {}
        design_doc = payload.get("design_doc") or {}
        return "\n".join(
            line
            for line in [
                f"Gate reason: {payload.get('gate_reason', '')}",
                f"Consensus score: {plan.get('consensus_score', '') if isinstance(plan, dict) else ''}",
                f"Gate passed: {plan.get('gate_passed', '') if isinstance(plan, dict) else ''}",
                "",
                "Design brief:",
                _compact_preview(design_doc, limit=1400),
            ]
            if line is not None
        ).strip()
    if gate_name == "brief" and isinstance(payload, dict):
        return _compact_preview(payload.get("brief", payload), limit=1800)
    if gate_name == "evidence" and isinstance(payload, dict):
        refs = payload.get("evidence_refs") or []
        if isinstance(refs, list):
            lines = [f"Evidence count: {len(refs)}"]
            for ref in refs[:8]:
                if isinstance(ref, dict):
                    lines.append(f"- {ref.get('id', '?')} | {ref.get('source_grade', '?')} | {ref.get('source_title', '')}")
            return "\n".join(lines)
    if gate_name == "report" and isinstance(payload, dict):
        return _compact_preview(str(payload.get("report_md", "")), limit=2400)
    return _compact_preview(payload, limit=1800)


def _compact_preview(value: Any, *, limit: int) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _collect_serve_interview_answers(
    topic: str,
    *,
    stdout: IO[str],
    stdin: IO[str],
) -> ServeInterviewResult:
    """Run a show-me-the-prd style intake over the JSON-line serve protocol."""
    from src.intake.idea_dump import IdeaDump
    from src.intent.interview_prompts import merge_answers_to_text
    from src.intent.office_hours import reframe_with_context
    from src.interview.session import InterviewSession

    session = InterviewSession.from_idea(IdeaDump(raw_text=topic))
    total_questions = 6
    emit(
        "phase_change",
        phase="INTERVIEW",
        stream=stdout,
        data={
            "workflow": "show-me-the-prd",
            "question_count": total_questions,
            "mode": getattr(session.plan, "mode", "deep"),
        },
    )

    qa_pairs: list[dict[str, str]] = []
    for idx in range(1, total_questions + 1):
        item = session.next_question()
        if item is None:
            break
        framed = reframe_with_context(item.dimension_id, topic, session.answers)
        qid = item.dimension_id
        question = str(framed.get("question") or item.research_question or qid).strip()
        options = _normalize_show_prd_options(framed.get("options"))
        header = _show_prd_header(qid)
        preview = _show_prd_preview(qid, topic, session.answers)
        emit(
            "interview_question",
            stream=stdout,
            q_id=qid,
            question_id=qid,
            text=question,
            prompt=question,
            header=header,
            options=options,
            allow_other=True,
            multiSelect=False,
            preview=preview,
            index=idx,
            total=total_questions,
            data={
                "q_id": qid,
                "text": question,
                "header": header,
                "options": options,
                "allow_other": True,
                "multiSelect": False,
                "preview": preview,
                "index": idx,
                "total": total_questions,
            },
        )

        action = _read_action(stdin)
        if action is None:
            return ServeInterviewResult(
                status="error",
                message=f"no interview answer received for {qid}",
            )
        if action.action == "abort":
            return ServeInterviewResult(status="aborted")
        if action.action != "interview_answer":
            return ServeInterviewResult(
                status="error",
                message=f"unexpected action while waiting for {qid}: {action.action}",
            )

        answer = _interview_answer_from_action(action).strip()
        if answer and answer.lower() not in {"skip", "pass", "건너뛰기"}:
            session.answer(_serve_interview_answer_key(item.label), answer)
            qa_pairs.append({"id": qid, "answer": answer})

    if not qa_pairs:
        return ServeInterviewResult(status="ok", topic=topic)
    return ServeInterviewResult(status="ok", topic=merge_answers_to_text(topic, qa_pairs))


def _normalize_show_prd_options(raw_options: Any) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    if not isinstance(raw_options, list):
        return options
    for idx, raw in enumerate(raw_options):
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()
        if not label:
            continue
        description = str(raw.get("description") or "").strip()
        recommended = idx == 0 and "추천" not in label and label != "Other"
        display_label = f"{label} (추천)" if recommended else label
        options.append(
            {
                "key": chr(ord("A") + len(options)),
                "label": display_label,
                "value": label,
                "description": description,
            }
        )
    return options


def _show_prd_header(qid: str) -> str:
    return {
        "Q1_research_question": "아이디어 구체화",
        "Q2_purpose": "목적",
        "Q3_context": "맥락",
        "Q4_known": "기존 정보",
        "Q5_deliverable": "산출물",
        "Q6_quality": "근거 품질",
    }.get(qid, "인터뷰")


def _show_prd_preview(qid: str, topic: str, answers: dict[str, str]) -> str:
    if qid == "Q3_context":
        return (
            "선택한 맥락은 이후 검색 범위, 페르소나 구성, 비교 국가/산업 범위를 제한합니다.\n"
            f"원 요청: {topic}"
        )
    if qid == "Q5_deliverable":
        purpose = answers.get("purpose", "아직 목적 미정")
        return (
            "| 산출물 | 적합한 상황 |\n"
            "| --- | --- |\n"
            "| 결정서 | 빠른 Go/No-Go 판단 |\n"
            "| 리서치 리포트 | 근거와 반론까지 필요한 검토 |\n"
            "| Slide deck | 외부 공유/발표 |\n\n"
            f"현재 목적: {purpose}"
        )
    if qid == "Q6_quality":
        return (
            "A/B급 기준을 고르면 속도는 느려지지만 mock·추정 결과가 최종 보고서에 섞이는 것을 더 강하게 막습니다."
        )
    return ""


def _serve_interview_answer_key(label: str) -> str:
    return {
        "deliverable": "deliverable_type",
        "quality": "quality_bar",
    }.get(label, label)


def _interview_answer_from_action(action: Action) -> str:
    for key in ("answer", "other_text", "selected", "choice", "value"):
        value = action.fields.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def serve_full(
    topic: str,
    *,
    report_path: Path,
    stdout: IO[str],
    stdin: IO[str] | None = None,
    wait_for_input: bool = False,
    depth: str = "deep",
) -> int:
    """PRD-v2 §2.1 full pipeline — uses real LLM providers when configured."""
    from src.pipeline.runner import run_pipeline
    from src.report.chapter_mapper import ChapterMapper
    from src.report.pyramid_formatter import PyramidFormatter
    from src.research.depth import depth_profile

    offline = _detect_offline_mode()
    profile = depth_profile(depth)
    emit(
        "phase_change",
        phase="STARTUP",
        stream=stdout,
        data={
            "topic": topic,
            "pipeline": "full",
            "offline": offline,
            "depth": depth,
            "council_persona_pool_size": profile.persona_pool_size,
            "active_council_persona_count": profile.active_persona_count,
        },
    )

    if wait_for_input:
        interview_result = _collect_serve_interview_answers(
            topic,
            stdout=stdout,
            stdin=stdin or sys.stdin,
        )
        if interview_result.status == "aborted":
            emit("done", stream=stdout, pipeline="full", aborted=True)
            return 0
        if interview_result.status == "error":
            emit("error", stream=stdout, message=interview_result.message or "interview failed")
            return 1
        topic = interview_result.topic or topic

    streamed_council_events = 0

    def emit_progress(event: dict[str, Any]) -> None:
        nonlocal streamed_council_events
        name = str(event.get("event") or "")
        fields = {key: value for key, value in event.items() if key != "event"}
        if name == "stage_started":
            emit("phase_change", phase=str(fields.get("stage", "")).upper(), stream=stdout, data={"stage": fields.get("stage")})
        if name.startswith("council_"):
            streamed_council_events += 1
        emit(name, stream=stdout, **fields)

    try:
        hitl_adapter = (
            JSONLineHITLAdapter(stdout=stdout, stdin=stdin or sys.stdin)
            if wait_for_input
            else None
        )
        pipeline_result = run_pipeline(
            topic,
            progress_callback=emit_progress,
            offline=offline,
            require_live=not offline,
            depth=depth,
            hitl_adapter=hitl_adapter,
        )
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
    executed_round_count = int(pipeline_result.get("executed_council_round_count") or len(rounds))
    turn_transcript = list(pipeline_result.get("council_turn_transcript") or [])

    if streamed_council_events == 0:
        for round_no, digest in enumerate(rounds[:executed_round_count], start=1):
            emit(
                "council_round_start",
                stream=stdout,
                stage="council_progress",
                pipeline_stage="council",
                round=round_no,
                layer=digest.layer_id,
            )
            for turn in turn_transcript:
                if int(turn.get("round") or 0) != round_no:
                    continue
                emit(
                    "council_turn",
                    stream=stdout,
                    round=round_no,
                    layer=str(turn.get("layer_id") or digest.layer_id),
                    stage="council_progress",
                    pipeline_stage="council",
                    council_stage=str(turn.get("stage") or ""),
                    persona=str(turn.get("persona_id") or ""),
                    provider=str(turn.get("provider") or ""),
                )
            emit(
                "council_persona_token",
                stream=stdout,
                stage="council_progress",
                pipeline_stage="council",
                council_stage="digest",
                persona="agent",
                delta=digest.key_claim,
            )
            emit(
                "council_round_done",
                stream=stdout,
                stage="council_progress",
                pipeline_stage="council",
                round=round_no,
                score=round(digest.confidence * 100),
            )

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
    emit(
        "done",
        stream=stdout,
        report_path=str(report_path),
        pipeline="full",
        depth=depth,
        council_persona_pool_size=int(pipeline_result.get("council_persona_pool_size") or 0),
        active_council_persona_count=int(pipeline_result.get("active_council_persona_count") or 0),
        council_turn_count=len(turn_transcript),
    )
    return 0


# ---- entrypoint ---------------------------------------------------------


def serve(
    topic: str,
    *,
    report_path: Path,
    wait_for_input: bool,
    stdout: IO[str],
    stdin: IO[str],
    pipeline: str = "full",
    depth: str = "deep",
) -> int:
    if pipeline == "full":
        return serve_full(
            topic,
            report_path=report_path,
            stdout=stdout,
            stdin=stdin,
            wait_for_input=wait_for_input,
            depth=depth,
        )
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

    known_commands = {
        "run",
        "tui",
        "serve",
        "runs",
        "status",
        "doctor",
        "contracts",
        "references",
        "orchestrate",
        "demo",
    }
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
            require_live=shortcut_options["require_live"],
            depth=shortcut_options["depth"],
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
        require_live = bool(args.online)
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
            require_live=require_live,
            depth=args.depth,
        )

    if args.command == "runs":
        from src.muchanipo.terminal import render_runs, runs_report

        limit = max(1, args.limit)
        if args.json:
            _write_json(runs_report(limit=limit))
        else:
            render_runs(stdout=sys.stdout, limit=limit)
        return 0

    if args.command == "status":
        from src.muchanipo.terminal import render_cli_status, status_report

        if args.json:
            _write_json(status_report(probe=bool(args.probe)))
        else:
            render_cli_status(stdout=sys.stdout, probe=bool(args.probe))
        return 0

    if args.command == "doctor":
        from src.muchanipo.terminal import doctor_report, render_doctor

        if args.json:
            report = doctor_report()
            _write_json(report)
        else:
            report = render_doctor(stdout=sys.stdout)
        return 0 if report["ok"] else 1

    if args.command == "contracts":
        from src.muchanipo.terminal import json_contracts_report, render_json_contracts

        if args.json:
            _write_json(json_contracts_report())
        else:
            render_json_contracts(stdout=sys.stdout)
        return 0

    if args.command == "references":
        from src.muchanipo.terminal import references_report, render_references

        if args.json:
            _write_json(references_report())
        else:
            render_references(stdout=sys.stdout)
        return 0

    if args.command == "orchestrate":
        from src.muchanipo.terminal import orchestration_report, render_orchestration

        if args.cleanup_workers and not args.dry_run and not args.force:
            sys.stderr.write("muchanipo: orchestrate cleanup requires --dry-run or --force\n")
            return 2
        if args.json:
            report = orchestration_report(
                session=args.session,
                include_capture=bool(args.include_capture),
                cleanup_workers=bool(args.cleanup_workers),
                dry_run=bool(args.dry_run),
                force=bool(args.force),
            )
            _write_json(report)
        else:
            report = render_orchestration(
                stdout=sys.stdout,
                session=args.session,
                include_capture=bool(args.include_capture),
                cleanup_workers=bool(args.cleanup_workers),
                dry_run=bool(args.dry_run),
                force=bool(args.force),
            )
        return 0 if report.get("ok") else 1

    if args.command == "demo":
        from src.muchanipo.terminal import DEMO_TOPIC

        return _run_terminal_safely(
            DEMO_TOPIC,
            report_path=Path(args.report_path) if args.report_path else None,
            run_dir=Path(args.run_dir) if args.run_dir else None,
            offline=True,
            jsonl=bool(args.jsonl),
            dashboard=(not bool(args.plain) and not bool(args.jsonl) and bool(getattr(sys.stdout, "isatty", lambda: False)())),
            interview=False,
            require_live=False,
            depth=args.depth,
        )

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
        depth=args.depth,
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
    require_live: bool,
    depth: str,
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
            require_live=require_live,
            depth=depth,
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
        "require_live": False,
        "depth": "deep",
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
            options["require_live"] = True
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
        elif arg == "--depth":
            if idx + 1 >= len(argv):
                options["error"] = "--depth requires a value"
                break
            value = argv[idx + 1].strip().lower()
            if value not in VALID_DEPTHS:
                options["error"] = f"--depth must be one of: {'|'.join(VALID_DEPTHS)}"
                break
            options["depth"] = value
            idx += 1
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


def _write_json(value: Any) -> None:
    import json

    sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
