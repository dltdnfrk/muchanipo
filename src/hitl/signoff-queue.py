#!/usr/bin/env python3
"""
MuchaNipo Sign-off Queue -- UNCERTAIN 결과 관리
================================================
Eval Agent가 UNCERTAIN으로 판정한 Council 결과를 사람이 검토하고
승인/거절/수정할 수 있는 CLI 도구.

Usage:
    python signoff-queue.py list                          # 대기 목록
    python signoff-queue.py show <id>                     # 상세 보기
    python signoff-queue.py approve <id>                  # 승인 -> vault 저장
    python signoff-queue.py reject <id> --reason "..."    # 거절 + 사유
    python signoff-queue.py modify <id> --note "수정내용"  # 수정 후 승인
    python signoff-queue.py stats                         # 통계

Sign-off decisions are recorded in rubric-feedback.jsonl for future
rubric evolution (per program.md: after 20+ sign-offs, analyze patterns).
"""

import argparse
import json
import os
import subprocess
import sys
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
SIGNOFF_QUEUE_DIR = SCRIPT_DIR / "signoff-queue"
RUBRIC_HISTORY_DIR = SCRIPT_DIR / "rubric-history"
FEEDBACK_FILE = RUBRIC_HISTORY_DIR / "rubric-feedback.jsonl"
LOGS_DIR = SCRIPT_DIR / "logs"
CONFIG_PATH = SCRIPT_DIR / "config.json"

DEFAULT_VAULT_BASE = Path.home() / "Documents" / "Hyunjun"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_config() -> Dict[str, Any]:
    """Load config.json if available."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_queue_entries(status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load all entries from the signoff-queue directory."""
    entries = []
    if not SIGNOFF_QUEUE_DIR.exists():
        return entries

    for fpath in sorted(SIGNOFF_QUEUE_DIR.glob("sq-*.json")):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                entry = json.load(f)
            entry["_file_path"] = str(fpath)
            if status_filter is None or entry.get("status") == status_filter:
                entries.append(entry)
        except (json.JSONDecodeError, OSError) as e:
            print(f"WARNING: Could not read {fpath}: {e}", file=sys.stderr)

    return entries


def find_entry(entry_id: str) -> Optional[Dict[str, Any]]:
    """Find a specific entry by ID."""
    # Try direct file path first
    candidate = SIGNOFF_QUEUE_DIR / f"{entry_id}.json"
    if candidate.exists():
        with open(candidate, "r", encoding="utf-8") as f:
            entry = json.load(f)
        entry["_file_path"] = str(candidate)
        return entry

    # Fallback: scan all files
    for entry in load_queue_entries():
        if entry.get("id") == entry_id:
            return entry

    return None


def append_feedback(record: Dict[str, Any]) -> None:
    """Append a feedback record to rubric-feedback.jsonl."""
    RUBRIC_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def resolve_vault_path(report: Dict[str, Any]) -> Path:
    """Determine vault destination based on topic/interest axis."""
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

    feed_path = DEFAULT_VAULT_BASE / "Feed"
    feed_path.mkdir(parents=True, exist_ok=True)
    return feed_path


def save_to_vault(entry: Dict[str, Any], modification_note: Optional[str] = None) -> Path:
    """Save an approved entry to the vault."""
    report = entry.get("council_report", {})
    vault_dir = resolve_vault_path(report)

    topic_slug = report.get("topic", "untitled").replace(" ", "-").lower()[:50]
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{date_str}-{topic_slug}.json"
    dest = vault_dir / filename

    output = {
        "council_report": report,
        "eval_result": entry.get("eval_result", {}),
        "signoff": {
            "action": "modify" if modification_note else "approve",
            "note": modification_note,
            "approved_at": datetime.now(timezone.utc).isoformat(),
        },
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }

    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return dest


def remove_from_queue(entry: Dict[str, Any]) -> None:
    """Remove entry file from the signoff-queue directory."""
    fpath = entry.get("_file_path")
    if fpath and Path(fpath).exists():
        Path(fpath).unlink()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_list(args: argparse.Namespace) -> int:
    """List pending entries in the sign-off queue."""
    entries = load_queue_entries(status_filter="pending")

    if not entries:
        print("Sign-off queue is empty. No pending items.")
        return 0

    print(f"{'ID':<25s} {'Score':>5s} {'Topic':<40s} {'Date':<20s}")
    print("-" * 95)

    for entry in entries:
        entry_id = entry.get("id", "?")
        topic = entry.get("topic", "?")[:40]
        total = entry.get("eval_result", {}).get("total", "?")
        ts = entry.get("timestamp", "?")[:19]
        print(f"{entry_id:<25s} {str(total):>5s} {topic:<40s} {ts:<20s}")

    print(f"\nTotal: {len(entries)} pending item(s)")
    return 0


REVIEW_DIR = SCRIPT_DIR / "review"


def _write_plannotator_review(entry: Dict[str, Any]) -> Path:
    """Council 결과를 리뷰용 마크다운으로 변환하여 review/ 디렉토리에 저장."""
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    entry_id = entry.get("id", "unknown")
    topic = entry.get("topic", "unknown")
    report = entry.get("council_report", {})
    eval_result = entry.get("eval_result", {})

    scores = eval_result.get("scores", {})
    total = eval_result.get("total", "?")
    verdict = eval_result.get("verdict", "?")
    reasoning = eval_result.get("reasoning", "")
    consensus = report.get("consensus", "")
    dissent = report.get("dissent", "")
    recommendations = report.get("recommendations", [])
    evidence = report.get("evidence", [])
    timestamp = entry.get("timestamp", "")[:19]

    lines = [
        f"# 리뷰: {topic}",
        "",
        f"**ID**: {entry_id}  ",
        f"**Timestamp**: {timestamp}  ",
        f"**Verdict**: {verdict} ({total}/40)  ",
        "",
        "## 평가 점수",
        "",
    ]
    for axis, val in scores.items():
        lines.append(f"- {axis}: {val}/10")
    lines.append("")

    if reasoning:
        lines.append("## 평가 근거")
        lines.append("")
        for line in reasoning.split("\n"):
            lines.append(line)
        lines.append("")

    if consensus:
        lines.append("## Council 합의")
        lines.append("")
        lines.append(consensus)
        lines.append("")

    if dissent:
        lines.append("## 반론")
        lines.append("")
        lines.append(dissent)
        lines.append("")

    if evidence:
        lines.append(f"## 근거 ({len(evidence)}개)")
        lines.append("")
        for i, src in enumerate(evidence, 1):
            lines.append(f"{i}. {src}")
        lines.append("")

    if recommendations:
        lines.append(f"## 권고사항 ({len(recommendations)}개)")
        lines.append("")
        for i, rec in enumerate(recommendations, 1):
            lines.append(f"{i}. {rec}")
        lines.append("")

    lines += [
        "## 결정",
        "",
        "- [ ] 승인 (Approve)",
        "- [ ] 거절 (Reject) — 사유:",
        "- [ ] 수정 (Modify) — 내용:",
        "",
    ]

    dest = REVIEW_DIR / f"{entry_id}.md"
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def cmd_show(args: argparse.Namespace) -> int:
    """Show detailed information about a specific entry."""
    entry = find_entry(args.id)
    if not entry:
        print(f"ERROR: Entry not found: {args.id}", file=sys.stderr)
        return 1

    # --plannotator: 리뷰 마크다운 생성
    if getattr(args, "plannotator", False):
        dest = _write_plannotator_review(entry)
        print(f"Review file created: {dest}")
        print(f"\nRun: plannotator annotate review/{dest.name}")
        return 0

    # --open implies --html
    if getattr(args, "open", False) or getattr(args, "html", False):
        try:
            from signoff_report import write_report  # noqa: F811
        except ImportError:
            # Fallback: invoke as subprocess
            cmd = [sys.executable, str(SCRIPT_DIR / "signoff-report.py"), args.id]
            if getattr(args, "open", False):
                cmd.append("--open")
            return subprocess.run(cmd).returncode
        return 0 if write_report(entry, open_browser=getattr(args, "open", False)) else 1

    report = entry.get("council_report", {})
    eval_result = entry.get("eval_result", {})

    print("=" * 70)
    print(f"  Sign-off Queue Entry: {entry.get('id', '?')}")
    print("=" * 70)
    print(f"  Status:     {entry.get('status', '?')}")
    print(f"  Topic:      {entry.get('topic', '?')}")
    print(f"  Council ID: {entry.get('council_id', '?')}")
    print(f"  Timestamp:  {entry.get('timestamp', '?')}")

    print("\n--- Eval Scores ---")
    scores = eval_result.get("scores", {})
    for axis, val in scores.items():
        print(f"  {axis:15s}: {val:2d}/10")
    print(f"  {'TOTAL':15s}: {eval_result.get('total', '?')}/40")
    print(f"  {'VERDICT':15s}: {eval_result.get('verdict', '?')}")

    print("\n--- Eval Reasoning ---")
    reasoning = eval_result.get("reasoning", "")
    for line in reasoning.split("\n"):
        print(f"  {line}")

    print("\n--- Council Consensus ---")
    consensus = report.get("consensus", "(none)")
    print(f"  {consensus}")

    dissent = report.get("dissent", "")
    if dissent:
        print("\n--- Dissent ---")
        print(f"  {dissent}")

    evidence = report.get("evidence", [])
    if evidence:
        print(f"\n--- Evidence ({len(evidence)} sources) ---")
        for i, src in enumerate(evidence, 1):
            print(f"  {i}. {src}")

    recommendations = report.get("recommendations", [])
    if recommendations:
        print(f"\n--- Recommendations ({len(recommendations)}) ---")
        for i, rec in enumerate(recommendations, 1):
            print(f"  {i}. {rec}")

    personas = report.get("personas", [])
    if personas:
        print(f"\n--- Personas ({len(personas)}) ---")
        for p in personas:
            name = p.get("name", "?")
            conf = p.get("confidence", 0)
            print(f"  {name}: confidence {conf:.2f}")

    print("=" * 70)
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    """Approve an entry and save to vault."""
    entry = find_entry(args.id)
    if not entry:
        print(f"ERROR: Entry not found: {args.id}", file=sys.stderr)
        return 1

    if entry.get("status") != "pending":
        print(f"WARNING: Entry status is '{entry.get('status')}', not 'pending'.", file=sys.stderr)

    # Save to vault
    dest = save_to_vault(entry)
    print(f"Approved: {entry.get('id')}")
    print(f"Saved to: {dest}")

    # Record feedback
    append_feedback({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "id": entry.get("id", "?"),
        "action": "approve",
        "reason": "",
        "eval_total": entry.get("eval_result", {}).get("total", 0),
        "topic": entry.get("topic", "?"),
    })

    # Remove from queue
    remove_from_queue(entry)
    print("Removed from sign-off queue.")

    _check_evolution_trigger()
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    """Reject an entry with a reason."""
    entry = find_entry(args.id)
    if not entry:
        print(f"ERROR: Entry not found: {args.id}", file=sys.stderr)
        return 1

    if not args.reason:
        print("ERROR: --reason is required for reject.", file=sys.stderr)
        return 1

    if entry.get("status") != "pending":
        print(f"WARNING: Entry status is '{entry.get('status')}', not 'pending'.", file=sys.stderr)

    # Move to logs as failed
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    fail_entry = {
        "id": entry.get("id"),
        "topic": entry.get("topic"),
        "council_id": entry.get("council_id"),
        "eval_result": entry.get("eval_result"),
        "rejected_at": datetime.now(timezone.utc).isoformat(),
        "reason": args.reason,
    }
    fail_path = LOGS_DIR / f"rejected-{entry.get('id', 'unknown')}.json"
    with open(fail_path, "w", encoding="utf-8") as f:
        json.dump(fail_entry, f, ensure_ascii=False, indent=2)

    print(f"Rejected: {entry.get('id')}")
    print(f"Reason: {args.reason}")
    print(f"Logged to: {fail_path}")

    # Record feedback
    append_feedback({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "id": entry.get("id", "?"),
        "action": "reject",
        "reason": args.reason,
        "eval_total": entry.get("eval_result", {}).get("total", 0),
        "topic": entry.get("topic", "?"),
    })

    # Remove from queue
    remove_from_queue(entry)
    print("Removed from sign-off queue.")

    _check_evolution_trigger()
    return 0


def cmd_modify(args: argparse.Namespace) -> int:
    """Add modification note and approve."""
    entry = find_entry(args.id)
    if not entry:
        print(f"ERROR: Entry not found: {args.id}", file=sys.stderr)
        return 1

    if not args.note:
        print("ERROR: --note is required for modify.", file=sys.stderr)
        return 1

    if entry.get("status") != "pending":
        print(f"WARNING: Entry status is '{entry.get('status')}', not 'pending'.", file=sys.stderr)

    # Save to vault with modification note
    dest = save_to_vault(entry, modification_note=args.note)
    print(f"Modified & approved: {entry.get('id')}")
    print(f"Note: {args.note}")
    print(f"Saved to: {dest}")

    # Record feedback
    append_feedback({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "id": entry.get("id", "?"),
        "action": "modify",
        "reason": args.note,
        "eval_total": entry.get("eval_result", {}).get("total", 0),
        "topic": entry.get("topic", "?"),
    })

    # Remove from queue
    remove_from_queue(entry)
    print("Removed from sign-off queue.")

    _check_evolution_trigger()
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Show sign-off statistics and feedback analysis."""
    # Queue stats
    pending = load_queue_entries(status_filter="pending")
    print(f"Pending items: {len(pending)}")

    # Feedback stats
    if not FEEDBACK_FILE.exists():
        print("No feedback recorded yet.")
        return 0

    feedback_records = []
    with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    feedback_records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    total = len(feedback_records)
    approvals = sum(1 for r in feedback_records if r.get("action") == "approve")
    rejections = sum(1 for r in feedback_records if r.get("action") == "reject")
    modifications = sum(1 for r in feedback_records if r.get("action") == "modify")

    print(f"\n--- Feedback Summary ({total} decisions) ---")
    print(f"  Approved:  {approvals}")
    print(f"  Rejected:  {rejections}")
    print(f"  Modified:  {modifications}")

    if total > 0:
        approval_rate = (approvals + modifications) / total * 100
        print(f"  Approval rate: {approval_rate:.1f}%")

    # Score distribution for approved vs rejected
    if approvals + modifications > 0:
        approved_scores = [
            r.get("eval_total", 0)
            for r in feedback_records
            if r.get("action") in ("approve", "modify")
        ]
        avg_approved = sum(approved_scores) / len(approved_scores)
        print(f"  Avg score (approved): {avg_approved:.1f}")

    if rejections > 0:
        rejected_scores = [
            r.get("eval_total", 0)
            for r in feedback_records
            if r.get("action") == "reject"
        ]
        avg_rejected = sum(rejected_scores) / len(rejected_scores)
        print(f"  Avg score (rejected): {avg_rejected:.1f}")

    # Evolution trigger check
    config = load_config()
    evolution_trigger = config.get("eval_rubric", {}).get("evolution_trigger", 20)
    if total >= evolution_trigger:
        print(f"\n  ** Rubric evolution trigger reached ({total} >= {evolution_trigger}) **")
        print("  Consider analyzing feedback patterns to refine scoring thresholds.")
    else:
        remaining = evolution_trigger - total
        print(f"\n  Rubric evolution: {remaining} more decisions until analysis trigger")

    return 0


def _check_evolution_trigger() -> None:
    """Check if enough feedback has been collected for rubric evolution."""
    if not FEEDBACK_FILE.exists():
        return

    count = 0
    with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1

    config = load_config()
    trigger = config.get("eval_rubric", {}).get("evolution_trigger", 20)

    if count >= trigger and count % 5 == 0:  # Remind every 5 decisions after trigger
        print(
            f"\nNOTICE: {count} sign-off decisions recorded (trigger: {trigger}). "
            "Run 'python signoff-queue.py stats' to review patterns.",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MuchaNipo Sign-off Queue -- UNCERTAIN 결과 관리",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python signoff-queue.py list
  python signoff-queue.py show sq-20260409-123456
  python signoff-queue.py approve sq-20260409-123456
  python signoff-queue.py reject sq-20260409-123456 --reason "출처 불명확"
  python signoff-queue.py modify sq-20260409-123456 --note "시장 규모 수치 업데이트"
  python signoff-queue.py stats
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # list
    subparsers.add_parser("list", help="Show pending items in the sign-off queue")

    # show
    show_parser = subparsers.add_parser("show", help="Show detailed entry information")
    show_parser.add_argument("id", help="Sign-off queue entry ID (e.g., sq-20260409-123456)")
    show_parser.add_argument("--html", action="store_true", help="Generate HTML report instead of terminal output")
    show_parser.add_argument("--open", action="store_true", help="Open HTML report in browser (implies --html)")
    show_parser.add_argument("--plannotator", action="store_true", help="리뷰용 마크다운 생성 후 plannotator 명령 출력")

    # approve
    approve_parser = subparsers.add_parser("approve", help="Approve entry and save to vault")
    approve_parser.add_argument("id", help="Sign-off queue entry ID")

    # reject
    reject_parser = subparsers.add_parser("reject", help="Reject entry with reason")
    reject_parser.add_argument("id", help="Sign-off queue entry ID")
    reject_parser.add_argument("--reason", required=True, help="Rejection reason")

    # modify
    modify_parser = subparsers.add_parser("modify", help="Add modification note and approve")
    modify_parser.add_argument("id", help="Sign-off queue entry ID")
    modify_parser.add_argument("--note", required=True, help="Modification note")

    # stats
    subparsers.add_parser("stats", help="Show sign-off statistics")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Ensure directories exist
    SIGNOFF_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    RUBRIC_HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    commands = {
        "list": cmd_list,
        "show": cmd_show,
        "approve": cmd_approve,
        "reject": cmd_reject,
        "modify": cmd_modify,
        "stats": cmd_stats,
    }

    handler = commands.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
