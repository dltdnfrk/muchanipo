#!/usr/bin/env python3
"""
MuchaNipo Eval Agent -- Council 결과 자동 채점
==============================================
Council 토론 결과를 program.md 기반 루브릭으로 자동 채점하고
PASS/UNCERTAIN/FAIL로 라우팅한다.

Usage:
    python eval-agent.py <council-report.json>
    python eval-agent.py <council-report.json> --rubric rubric.json
    python eval-agent.py <council-report.json> --dry-run
    python eval-agent.py <council-report.json> --verbose

Routing:
    total >= 28  -> PASS       -> vault 저장 진행
    total 20-27  -> UNCERTAIN  -> signoff-queue 대기
    total < 20   -> FAIL       -> 폐기 + 로그
"""

import argparse
import json
import os
import sys
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
SIGNOFF_QUEUE_DIR = SCRIPT_DIR / "signoff-queue"
RUBRIC_HISTORY_DIR = SCRIPT_DIR / "rubric-history"
LOGS_DIR = SCRIPT_DIR / "logs"
CONFIG_PATH = SCRIPT_DIR / "config.json"

# Default vault base (expanduser handled at runtime)
DEFAULT_VAULT_BASE = Path.home() / "Documents" / "Hyunjun"

# ---------------------------------------------------------------------------
# Thresholds (from program.md / config.json)
# ---------------------------------------------------------------------------
THRESHOLD_PASS = 28
THRESHOLD_UNCERTAIN = 20


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------
def load_config() -> Dict[str, Any]:
    """Load config.json if available, return empty dict otherwise."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_rubric(rubric_path: Optional[str]) -> Dict[str, Any]:
    """Load a custom rubric file, or return default rubric."""
    if rubric_path and Path(rubric_path).exists():
        with open(rubric_path, "r", encoding="utf-8") as f:
            return json.load(f)
    # Default rubric from program.md
    return {
        "axes": ["usefulness", "reliability", "novelty", "actionability"],
        "thresholds": {
            "pass": THRESHOLD_PASS,
            "uncertain": THRESHOLD_UNCERTAIN,
        },
        "max_per_axis": 10,
    }


# ---------------------------------------------------------------------------
# Scoring engine (rule-based)
# ---------------------------------------------------------------------------
def score_usefulness(report: Dict[str, Any]) -> Tuple[int, str]:
    """Score usefulness: 의사결정/제품 구축에 도움이 되는가?"""
    score = 5  # baseline
    reasons = []

    recommendations = report.get("recommendations", [])
    if len(recommendations) >= 3:
        score += 2
        reasons.append(f"recommendations {len(recommendations)}개 (>= 3): +2")
    elif len(recommendations) >= 1:
        score += 1
        reasons.append(f"recommendations {len(recommendations)}개 (>= 1): +1")
    else:
        score -= 1
        reasons.append("recommendations 없음: -1")

    consensus = report.get("consensus", "")
    if len(consensus) > 200:
        score += 1
        reasons.append("consensus 상세 (200자 이상): +1")

    confidence = report.get("confidence", 0)
    if confidence >= 0.8:
        score += 1
        reasons.append(f"confidence {confidence:.2f} (>= 0.8): +1")

    # Check for concrete keywords indicating practical value
    all_text = consensus + " ".join(recommendations)
    action_keywords = ["구현", "적용", "도입", "전략", "implement", "deploy", "adopt", "strategy"]
    matches = [kw for kw in action_keywords if kw in all_text.lower()]
    if len(matches) >= 2:
        score += 1
        reasons.append(f"실용 키워드 {len(matches)}개: +1")

    return max(0, min(10, score)), "; ".join(reasons)


def score_reliability(report: Dict[str, Any]) -> Tuple[int, str]:
    """Score reliability: 출처가 명확한가? 검증 가능한가?"""
    score = 5  # baseline
    reasons = []

    evidence = report.get("evidence", [])
    if len(evidence) >= 5:
        score += 2
        reasons.append(f"evidence {len(evidence)}개 (>= 5): +2")
    elif len(evidence) >= 3:
        score += 1
        reasons.append(f"evidence {len(evidence)}개 (>= 3): +1")
    elif len(evidence) == 0:
        score -= 2
        reasons.append("evidence 없음: -2")

    confidence = report.get("confidence", 0)
    if confidence >= 0.7:
        score += 2
        reasons.append(f"confidence {confidence:.2f} (>= 0.7): +2")
    elif confidence >= 0.5:
        score += 1
        reasons.append(f"confidence {confidence:.2f} (>= 0.5): +1")
    elif confidence < 0.3:
        score -= 1
        reasons.append(f"confidence {confidence:.2f} (< 0.3): -1")

    # Persona consensus strength
    personas = report.get("personas", [])
    if personas:
        avg_persona_conf = sum(p.get("confidence", 0) for p in personas) / len(personas)
        if avg_persona_conf >= 0.7:
            score += 1
            reasons.append(f"평균 페르소나 confidence {avg_persona_conf:.2f} (>= 0.7): +1")
        elif avg_persona_conf < 0.3:
            score -= 1
            reasons.append(f"평균 페르소나 confidence {avg_persona_conf:.2f} (< 0.3): -1")

    return max(0, min(10, score)), "; ".join(reasons)


def score_novelty(report: Dict[str, Any]) -> Tuple[int, str]:
    """Score novelty: vault에 없는 새로운 정보인가?"""
    score = 5  # baseline
    reasons = []

    dissent = report.get("dissent", "")
    if not dissent or dissent.strip() == "":
        score -= 1
        reasons.append("dissent 없음 (토론 없이 동의 = 뻔한 내용): -1")
    elif len(dissent) > 100:
        score += 1
        reasons.append("dissent 상세 (활발한 토론 = 흥미로운 주제): +1")

    # More personas with diverse confidence = more nuanced topic
    personas = report.get("personas", [])
    if personas:
        confidences = [p.get("confidence", 0) for p in personas]
        if len(confidences) >= 2:
            spread = max(confidences) - min(confidences)
            if spread >= 0.3:
                score += 1
                reasons.append(f"페르소나 의견 다양성 높음 (spread {spread:.2f}): +1")
            elif spread < 0.1:
                score -= 1
                reasons.append(f"페르소나 의견 획일적 (spread {spread:.2f}): -1")

    if len(personas) >= 5:
        score += 1
        reasons.append(f"페르소나 {len(personas)}명 (>= 5, 다각적 분석): +1")

    # Topic complexity proxy: longer consensus = more complex topic
    consensus = report.get("consensus", "")
    if len(consensus) > 500:
        score += 1
        reasons.append("consensus 500자 초과 (복잡한 주제): +1")

    evidence = report.get("evidence", [])
    if len(evidence) >= 8:
        score += 1
        reasons.append(f"evidence {len(evidence)}개 (>= 8, 광범위 조사): +1")

    return max(0, min(10, score)), "; ".join(reasons)


def score_actionability(report: Dict[str, Any]) -> Tuple[int, str]:
    """Score actionability: 구체적 다음 단계가 있는가?"""
    score = 5  # baseline
    reasons = []

    recommendations = report.get("recommendations", [])
    if len(recommendations) >= 3:
        score += 2
        reasons.append(f"recommendations {len(recommendations)}개 (>= 3): +2")
    elif len(recommendations) >= 1:
        score += 1
        reasons.append(f"recommendations {len(recommendations)}개 (>= 1): +1")
    else:
        score -= 2
        reasons.append("recommendations 없음: -2")

    # Check if recommendations are concrete (have sufficient detail)
    if recommendations:
        avg_len = sum(len(r) for r in recommendations) / len(recommendations)
        if avg_len > 50:
            score += 1
            reasons.append(f"recommendations 평균 {avg_len:.0f}자 (상세): +1")
        elif avg_len < 15:
            score -= 1
            reasons.append(f"recommendations 평균 {avg_len:.0f}자 (너무 짧음): -1")

    confidence = report.get("confidence", 0)
    if confidence >= 0.8:
        score += 1
        reasons.append(f"높은 confidence {confidence:.2f} → 실행 가능성 높음: +1")

    # Specific action verbs in recommendations
    action_verbs = ["테스트", "구현", "검증", "배포", "분석", "조사", "작성", "연락",
                     "test", "build", "verify", "deploy", "analyze", "contact", "write"]
    if recommendations:
        all_recs = " ".join(recommendations).lower()
        verb_matches = [v for v in action_verbs if v in all_recs]
        if len(verb_matches) >= 2:
            score += 1
            reasons.append(f"구체적 행동 동사 {len(verb_matches)}개: +1")

    return max(0, min(10, score)), "; ".join(reasons)


def evaluate(report: Dict[str, Any], rubric: Dict[str, Any]) -> Dict[str, Any]:
    """Run the full evaluation on a council report."""
    scorers = {
        "usefulness": score_usefulness,
        "reliability": score_reliability,
        "novelty": score_novelty,
        "actionability": score_actionability,
    }

    scores = {}
    reasoning_parts = []

    for axis in rubric.get("axes", scorers.keys()):
        if axis in scorers:
            val, reason = scorers[axis](report)
            scores[axis] = val
            reasoning_parts.append(f"[{axis}={val}] {reason}")

    total = sum(scores.values())

    thresholds = rubric.get("thresholds", {})
    pass_threshold = thresholds.get("pass", THRESHOLD_PASS)
    uncertain_threshold = thresholds.get("uncertain", THRESHOLD_UNCERTAIN)

    if total >= pass_threshold:
        verdict = "PASS"
    elif total >= uncertain_threshold:
        verdict = "UNCERTAIN"
    else:
        verdict = "FAIL"

    return {
        "council_id": report.get("council_id", "unknown"),
        "topic": report.get("topic", "unknown"),
        "scores": scores,
        "total": total,
        "verdict": verdict,
        "reasoning": "\n".join(reasoning_parts),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rubric_version": rubric.get("version", "v1"),
    }


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
def resolve_vault_path(report: Dict[str, Any]) -> Path:
    """Determine the vault destination based on topic/interest axis."""
    config = load_config()
    axes = config.get("interest_axes", [])

    topic = report.get("topic", "").lower()

    for axis in axes:
        keywords = [kw.lower() for kw in axis.get("keywords", [])]
        if any(kw in topic for kw in keywords):
            vault_path = axis.get("vault_path", "")
            expanded = Path(os.path.expanduser(vault_path))
            if expanded.exists():
                return expanded

    # Default: Feed directory for uncategorized research
    feed_path = DEFAULT_VAULT_BASE / "Feed"
    feed_path.mkdir(parents=True, exist_ok=True)
    return feed_path


def route_pass(report: Dict[str, Any], eval_result: Dict[str, Any], dry_run: bool = False) -> str:
    """PASS -> prepare for vault storage."""
    vault_dir = resolve_vault_path(report)
    topic_slug = report.get("topic", "untitled").replace(" ", "-").lower()[:50]
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{date_str}-{topic_slug}.json"
    dest = vault_dir / filename

    if dry_run:
        return f"[DRY-RUN] PASS: would save to {dest}"

    # Save council report + eval result together
    output = {
        "council_report": report,
        "eval_result": eval_result,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return f"PASS: saved to {dest}"


def route_uncertain(report: Dict[str, Any], eval_result: Dict[str, Any], dry_run: bool = False) -> str:
    """UNCERTAIN -> signoff-queue."""
    SIGNOFF_QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    sq_id = f"sq-{ts}"

    entry = {
        "id": sq_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "topic": report.get("topic", "unknown"),
        "council_id": report.get("council_id", "unknown"),
        "eval_result": eval_result,
        "council_report": report,
        "status": "pending",
    }

    if dry_run:
        return f"[DRY-RUN] UNCERTAIN: would queue as {sq_id}"

    dest = SIGNOFF_QUEUE_DIR / f"{sq_id}.json"
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)

    return f"UNCERTAIN: queued as {sq_id} -> {dest}"


def route_fail(report: Dict[str, Any], eval_result: Dict[str, Any], dry_run: bool = False) -> str:
    """FAIL -> discard + log."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = LOGS_DIR / f"eval-fail-{ts}.json"

    entry = {
        "council_id": report.get("council_id", "unknown"),
        "topic": report.get("topic", "unknown"),
        "eval_result": eval_result,
        "discarded_at": datetime.now(timezone.utc).isoformat(),
    }

    if dry_run:
        return f"[DRY-RUN] FAIL: would discard and log to {log_file}"

    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)

    return f"FAIL: discarded, logged to {log_file}"


def route(report: Dict[str, Any], eval_result: Dict[str, Any], dry_run: bool = False) -> str:
    """Route eval result to the appropriate destination."""
    verdict = eval_result.get("verdict", "FAIL")
    routers = {
        "PASS": route_pass,
        "UNCERTAIN": route_uncertain,
        "FAIL": route_fail,
    }
    router = routers.get(verdict, route_fail)
    return router(report, eval_result, dry_run)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MuchaNipo Eval Agent -- Council 결과 자동 채점",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python eval-agent.py council-report.json
  python eval-agent.py council-report.json --rubric custom-rubric.json
  python eval-agent.py council-report.json --dry-run --verbose
  python eval-agent.py council-report.json --output-only
        """,
    )
    parser.add_argument(
        "report",
        help="Council report JSON file path",
    )
    parser.add_argument(
        "--rubric",
        default=None,
        help="Custom rubric JSON file (default: built-in from program.md)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate without routing (no file writes except eval result)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed scoring breakdown",
    )
    parser.add_argument(
        "--output-only",
        action="store_true",
        help="Print eval result JSON to stdout (no routing, no side effects)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Write eval result to this file path",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Load council report
    report_path = Path(args.report)
    if not report_path.exists():
        print(f"ERROR: Council report not found: {report_path}", file=sys.stderr)
        return 1

    try:
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {report_path}: {e}", file=sys.stderr)
        return 1

    # Validate required fields
    required_fields = ["topic", "council_id", "consensus"]
    missing = [f for f in required_fields if f not in report]
    if missing:
        print(f"ERROR: Missing required fields in report: {missing}", file=sys.stderr)
        return 1

    # Load rubric
    rubric = load_rubric(args.rubric)

    # Evaluate
    eval_result = evaluate(report, rubric)

    # Output
    if args.verbose:
        print("=" * 60)
        print(f"  MuchaNipo Eval Agent -- {report.get('topic', 'unknown')}")
        print("=" * 60)
        print(f"  Council ID: {eval_result['council_id']}")
        print(f"  Timestamp:  {eval_result['timestamp']}")
        print("-" * 60)
        for axis, val in eval_result["scores"].items():
            print(f"  {axis:15s}: {val:2d}/10")
        print("-" * 60)
        print(f"  {'TOTAL':15s}: {eval_result['total']:2d}/40")
        print(f"  {'VERDICT':15s}: {eval_result['verdict']}")
        print("-" * 60)
        print("  Reasoning:")
        for line in eval_result["reasoning"].split("\n"):
            print(f"    {line}")
        print("=" * 60)
    else:
        print(json.dumps(eval_result, ensure_ascii=False, indent=2))

    # Write eval result to file if requested
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(eval_result, f, ensure_ascii=False, indent=2)
        print(f"\nEval result saved to: {output_path}", file=sys.stderr)

    # Route (unless output-only or dry-run suppresses it)
    if args.output_only:
        return 0

    route_msg = route(report, eval_result, dry_run=args.dry_run)
    print(f"\n{route_msg}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
