#!/usr/bin/env python3
"""
MuchaNipo Session Check -- 세션 시작 시 대기 항목 알림
======================================================
세션 시작 시 실행하여 처리 대기 중인 항목을 요약 출력:
  - signoff-queue/ 스캔 → pending 항목 수 + 목록
  - rubric-feedback.jsonl 스캔 → 20건 이상이면 evolve 가능 알림
  - wiki/log.md 최근 5개 항목 출력

Usage:
    python3 session-check.py
    python3 session-check.py --no-color
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
SIGNOFF_QUEUE_DIR = SCRIPT_DIR / "signoff-queue"
RUBRIC_HISTORY_DIR = SCRIPT_DIR / "rubric-history"
FEEDBACK_FILE = RUBRIC_HISTORY_DIR / "rubric-feedback.jsonl"
WIKI_DIR = SCRIPT_DIR / "wiki"
WIKI_LOG = WIKI_DIR / "log.md"
CONFIG_PATH = SCRIPT_DIR / "config.json"

EVOLUTION_TRIGGER_DEFAULT = 20


# ---------------------------------------------------------------------------
# 색상 코드
# ---------------------------------------------------------------------------
class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    RED    = "\033[31m"
    GREEN  = "\033[32m"
    YELLOW = "\033[33m"
    CYAN   = "\033[36m"
    WHITE  = "\033[37m"
    DIM    = "\033[2m"


def colorize(text: str, *codes: str, use_color: bool = True) -> str:
    if not use_color:
        return text
    return "".join(codes) + text + C.RESET


# ---------------------------------------------------------------------------
# 박스 그리기
# ---------------------------------------------------------------------------
def box(title: str, lines: List[str], width: int = 60, use_color: bool = True) -> str:
    top    = "+" + "-" * (width - 2) + "+"
    header = "| " + colorize(title, C.BOLD, C.CYAN, use_color=use_color)
    # 색상 코드는 출력 너비에 포함되지 않으므로 시각적 너비 기준으로 패딩
    visible_title_len = len(title)
    header_pad = width - 2 - visible_title_len - 2
    header += " " * max(0, header_pad) + " |"
    sep    = "+" + "-" * (width - 2) + "+"
    rows   = []
    for line in lines:
        visible_len = len(line)
        pad = width - 2 - visible_len - 2
        rows.append("| " + line + " " * max(0, pad) + " |")
    bottom = "+" + "-" * (width - 2) + "+"
    return "\n".join([top, header, sep] + rows + [bottom])


# ---------------------------------------------------------------------------
# 데이터 수집
# ---------------------------------------------------------------------------
def get_pending_entries() -> List[Dict[str, Any]]:
    """signoff-queue/에서 pending 항목 로드."""
    entries = []
    if not SIGNOFF_QUEUE_DIR.exists():
        return entries
    for fpath in sorted(SIGNOFF_QUEUE_DIR.glob("sq-*.json")):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                entry = json.load(f)
            if entry.get("status") == "pending":
                entries.append(entry)
        except (json.JSONDecodeError, OSError):
            continue
    return entries


def get_feedback_count() -> int:
    """rubric-feedback.jsonl 줄 수 반환."""
    if not FEEDBACK_FILE.exists():
        return 0
    count = 0
    with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def get_evolution_trigger() -> int:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("eval_rubric", {}).get("evolution_trigger", EVOLUTION_TRIGGER_DEFAULT)
    return EVOLUTION_TRIGGER_DEFAULT


def get_recent_log_lines(n: int = 5) -> List[str]:
    """wiki/log.md에서 최근 n개 Operations 항목 반환."""
    if not WIKI_LOG.exists():
        return []
    lines = []
    with open(WIKI_LOG, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("- ") and " | " in stripped:
                lines.append(stripped[2:])  # '- ' 제거
    return lines[-n:]


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
def run(use_color: bool) -> None:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    print()
    print(colorize(f"  MuchaNipo Session Check  [{now_str}]", C.BOLD, C.WHITE, use_color=use_color))
    print()

    # --- Sign-off Queue ---
    pending = get_pending_entries()
    pending_count = len(pending)

    if pending_count == 0:
        sq_status = colorize("대기 없음", C.GREEN, use_color=use_color)
        sq_lines = [sq_status]
    else:
        sq_status = colorize(f"PENDING {pending_count}건", C.YELLOW, C.BOLD, use_color=use_color)
        sq_lines = [sq_status]
        for entry in pending[:5]:
            eid   = entry.get("id", "?")[:22]
            topic = entry.get("topic", "?")[:32]
            score = entry.get("eval_result", {}).get("total", "?")
            sq_lines.append(f"  {eid}  score={score}  {topic}")
        if pending_count > 5:
            sq_lines.append(f"  ... 외 {pending_count - 5}건 더")

    print(box("Sign-off Queue", sq_lines, width=68, use_color=use_color))
    print()

    # --- Rubric Evolution ---
    feedback_count = get_feedback_count()
    trigger = get_evolution_trigger()
    remaining = max(0, trigger - feedback_count)

    if feedback_count >= trigger:
        evo_label = colorize(
            f"EVOLVE 가능 ({feedback_count}건 >= {trigger})",
            C.GREEN, C.BOLD, use_color=use_color,
        )
        evo_lines = [
            evo_label,
            "  python3 rubric-learner.py  로 루브릭 진화 실행",
        ]
    else:
        evo_label = colorize(
            f"누적 {feedback_count}건 / 트리거 {trigger}건 (남은: {remaining}건)",
            C.DIM, use_color=use_color,
        )
        evo_lines = [evo_label]

    print(box("Rubric Evolution", evo_lines, width=68, use_color=use_color))
    print()

    # --- Recent Wiki Log ---
    recent_logs = get_recent_log_lines(5)
    if recent_logs:
        log_lines = [colorize(line[:62], C.DIM, use_color=use_color) for line in recent_logs]
    else:
        log_lines = [colorize("기록 없음", C.DIM, use_color=use_color)]

    print(box("Recent Activity (wiki/log.md)", log_lines, width=68, use_color=use_color))
    print()

    # --- 빠른 명령어 힌트 ---
    if pending_count > 0:
        hint = colorize(
            f"  python3 signoff-queue.py list   # {pending_count}건 확인",
            C.CYAN, use_color=use_color,
        )
        print(hint)
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="MuchaNipo Session Check -- 세션 시작 시 대기 항목 알림",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 session-check.py
  python3 session-check.py --no-color
        """,
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="ANSI 색상 코드 비활성화",
    )
    args = parser.parse_args()

    use_color = not args.no_color and sys.stdout.isatty()
    run(use_color=use_color)
    return 0


if __name__ == "__main__":
    sys.exit(main())
