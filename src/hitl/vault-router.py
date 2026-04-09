#!/usr/bin/env python3
"""
MuchaNipo Vault Router -- Eval 결과를 Obsidian Vault로 라우팅
=============================================================
eval-agent.py 결과(eval-result.json)를 읽고 자동 라우팅:
  PASS      → Obsidian vault에 마크다운 저장 (GBrain 패턴)
  UNCERTAIN → signoff-queue/에 JSON 저장
  FAIL      → logs/failed/에 이동
  모든 결과 → wiki/log.md 기록 + wiki/index.md 업데이트

Usage:
    python3 vault-router.py eval-result.json council-report.json
    python3 vault-router.py eval-result.json council-report.json --dry-run
    python3 vault-router.py eval-result.json council-report.json --verbose
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
SIGNOFF_QUEUE_DIR = SCRIPT_DIR / "signoff-queue"
LOGS_DIR = SCRIPT_DIR / "logs"
FAILED_DIR = LOGS_DIR / "failed"
WIKI_DIR = SCRIPT_DIR / "wiki"
WIKI_LOG = WIKI_DIR / "log.md"
WIKI_INDEX = WIKI_DIR / "index.md"
CONFIG_PATH = SCRIPT_DIR / "config.json"

DEFAULT_VAULT_BASE = Path.home() / "Documents" / "Hyunjun"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def load_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def resolve_vault_path(report: Dict[str, Any]) -> Path:
    """Interest axis 키워드 매칭으로 vault 저장 경로 결정."""
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

    # 기본: Feed 디렉토리
    feed_path = DEFAULT_VAULT_BASE / "Feed"
    feed_path.mkdir(parents=True, exist_ok=True)
    return feed_path


# ---------------------------------------------------------------------------
# GBrain 마크다운 생성
# ---------------------------------------------------------------------------
def build_compiled_truth(report: Dict[str, Any], eval_result: Dict[str, Any]) -> str:
    """Compiled Truth 섹션 (매번 덮어쓰기)."""
    topic = report.get("topic", "unknown")
    consensus = report.get("consensus", "")
    recommendations = report.get("recommendations", [])
    evidence = report.get("evidence", [])
    confidence = report.get("confidence", 0.0)
    scores = eval_result.get("scores", {})
    total = eval_result.get("total", 0)

    lines = [
        "## Compiled Truth",
        "",
        consensus,
        "",
    ]

    if recommendations:
        lines.append("### 권고사항")
        for i, rec in enumerate(recommendations, 1):
            lines.append(f"{i}. {rec}")
        lines.append("")

    if evidence:
        lines.append("### 근거")
        for i, ev in enumerate(evidence, 1):
            lines.append(f"- {ev}")
        lines.append("")

    dissent = report.get("dissent", "")
    if dissent:
        lines.append("### 반론")
        lines.append(dissent)
        lines.append("")

    lines.append("### 평가 점수")
    for axis, val in scores.items():
        lines.append(f"- {axis}: {val}/10")
    lines.append(f"- **총점**: {total}/40 (confidence: {confidence:.2f})")
    lines.append("")

    return "\n".join(lines)


def build_timeline_entry(eval_result: Dict[str, Any], council_id: str) -> str:
    """Timeline 섹션에 추가할 단일 항목 (append-only)."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    verdict = eval_result.get("verdict", "?")
    total = eval_result.get("total", 0)
    return f"- {now} | {verdict} | score={total}/40 | council_id={council_id}\n"


def build_frontmatter(report: Dict[str, Any], eval_result: Dict[str, Any]) -> str:
    """YAML frontmatter 생성."""
    topic = report.get("topic", "unknown")
    council_id = report.get("council_id", "unknown")
    confidence = report.get("confidence", 0.0)
    tags = report.get("tags", [])
    date_str = datetime.now().strftime("%Y-%m-%d")

    # interest axis 매칭으로 type 결정
    config = load_config()
    axes = config.get("interest_axes", [])
    topic_lower = topic.lower()
    axis_type = "general"
    for axis in axes:
        keywords = [kw.lower() for kw in axis.get("keywords", [])]
        if any(kw in topic_lower for kw in keywords):
            axis_type = axis.get("id", "general")
            break

    fm_lines = [
        "---",
        f"title: \"{topic}\"",
        f"type: {axis_type}",
        f"date: {date_str}",
        f"source: muchanipo-autoresearch",
        f"council_id: {council_id}",
        f"confidence: {confidence:.2f}",
    ]

    if tags:
        tag_str = ", ".join(f'"{t}"' for t in tags)
        fm_lines.append(f"tags: [{tag_str}]")

    fm_lines.append("---")
    fm_lines.append("")
    return "\n".join(fm_lines)


def save_markdown_to_vault(
    report: Dict[str, Any],
    eval_result: Dict[str, Any],
    vault_dir: Path,
    dry_run: bool = False,
) -> Path:
    """Vault에 마크다운 저장. Compiled Truth 덮어쓰기, Timeline append."""
    topic = report.get("topic", "untitled")
    topic_slug = topic.replace(" ", "-").lower()[:50]
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{date_str}-{topic_slug}.md"
    dest = vault_dir / filename

    if dry_run:
        print(f"  [DRY-RUN] would write: {dest}")
        return dest

    # 기존 파일이 있으면 Timeline 섹션 보존
    existing_timeline = ""
    if dest.exists():
        existing_content = dest.read_text(encoding="utf-8")
        # Timeline 섹션 추출
        if "## Timeline" in existing_content:
            timeline_start = existing_content.index("## Timeline")
            existing_timeline = existing_content[timeline_start:]

    # 새 컨텐츠 조합
    council_id = report.get("council_id", "unknown")
    frontmatter = build_frontmatter(report, eval_result)
    compiled_truth = build_compiled_truth(report, eval_result)
    new_timeline_entry = build_timeline_entry(eval_result, council_id)

    if existing_timeline:
        # Timeline 섹션에 항목 추가
        timeline_section = existing_timeline.rstrip() + "\n" + new_timeline_entry
    else:
        timeline_section = "## Timeline\n\n" + new_timeline_entry

    content = frontmatter + f"# {topic}\n\n" + compiled_truth + timeline_section

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# 라우팅 핸들러
# ---------------------------------------------------------------------------
def handle_pass(
    eval_result: Dict[str, Any],
    report: Dict[str, Any],
    dry_run: bool,
    verbose: bool,
) -> str:
    vault_dir = resolve_vault_path(report)
    dest = save_markdown_to_vault(report, eval_result, vault_dir, dry_run)
    msg = f"PASS -> vault: {dest}"
    if verbose:
        print(f"  저장 경로: {dest}")
    return msg


def handle_uncertain(
    eval_result: Dict[str, Any],
    report: Dict[str, Any],
    dry_run: bool,
    verbose: bool,
) -> str:
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
    dest = SIGNOFF_QUEUE_DIR / f"{sq_id}.json"
    if not dry_run:
        dest.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    msg = f"UNCERTAIN -> signoff-queue: {sq_id}"
    if verbose:
        print(f"  큐 항목: {dest}")
    return msg


def handle_fail(
    eval_result: Dict[str, Any],
    report: Dict[str, Any],
    dry_run: bool,
    verbose: bool,
) -> str:
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    council_id = report.get("council_id", "unknown")
    dest = FAILED_DIR / f"fail-{ts}-{council_id[:8]}.json"
    entry = {
        "council_id": council_id,
        "topic": report.get("topic", "unknown"),
        "eval_result": eval_result,
        "council_report": report,
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }
    if not dry_run:
        dest.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    msg = f"FAIL -> logs/failed: {dest.name}"
    if verbose:
        print(f"  실패 로그: {dest}")
    return msg


# ---------------------------------------------------------------------------
# Wiki 업데이트
# ---------------------------------------------------------------------------
def append_wiki_log(action: str, details: str, dry_run: bool) -> None:
    """wiki/log.md에 결과 기록 (append-only)."""
    if dry_run:
        return
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"- {now} | VAULT_ROUTER | {action} | {details}\n"
    if not WIKI_LOG.exists():
        WIKI_LOG.write_text(
            "# MuchaNipo Wiki Log\n<!-- Append-only. 절대 수정하지 않고 추가만. -->\n\n## Operations\n",
            encoding="utf-8",
        )
    with open(WIKI_LOG, "a", encoding="utf-8") as f:
        f.write(entry)


def update_wiki_index(
    report: Dict[str, Any],
    eval_result: Dict[str, Any],
    dest_path: Optional[Path],
    dry_run: bool,
) -> None:
    """wiki/index.md에 PASS 항목 추가/갱신."""
    if dry_run or dest_path is None:
        return

    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    topic = report.get("topic", "unknown")
    date_str = datetime.now().strftime("%Y-%m-%d")
    confidence_val = report.get("confidence", 0.0)
    confidence_label = "high" if confidence_val >= 0.8 else ("medium" if confidence_val >= 0.5 else "low")
    page_name = dest_path.name
    council_id = report.get("council_id", "unknown")

    new_row = f"| [{page_name}]({page_name}) | {topic} | {date_str} | {confidence_label} | {council_id} |"

    if not WIKI_INDEX.exists():
        WIKI_INDEX.write_text(
            "# MuchaNipo Wiki Index\n<!-- LLM이 자동 유지관리. 새 페이지 생성 시 여기에 추가. -->\n\n"
            "## Pages\n| Page | Topic | Updated | Confidence | Source |\n"
            "|------|-------|---------|------------|--------|\n",
            encoding="utf-8",
        )

    content = WIKI_INDEX.read_text(encoding="utf-8")

    # 기존 행 교체 또는 신규 추가
    if page_name in content:
        lines = content.splitlines()
        updated_lines = []
        for line in lines:
            if f"[{page_name}]" in line:
                updated_lines.append(new_row)
            else:
                updated_lines.append(line)
        WIKI_INDEX.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    else:
        with open(WIKI_INDEX, "a", encoding="utf-8") as f:
            f.write(new_row + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="MuchaNipo Vault Router -- Eval 결과를 Obsidian Vault로 라우팅",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 vault-router.py eval-result.json council-report.json
  python3 vault-router.py eval-result.json council-report.json --dry-run
  python3 vault-router.py eval-result.json council-report.json --verbose
        """,
    )
    parser.add_argument("eval_result", help="eval-agent.py 출력 JSON 파일")
    parser.add_argument("council_report", help="Council 보고서 JSON 파일")
    parser.add_argument("--dry-run", action="store_true", help="실제 파일 쓰기 없이 시뮬레이션")
    parser.add_argument("--verbose", "-v", action="store_true", help="상세 출력")
    args = parser.parse_args()

    # 입력 파일 로드
    eval_path = Path(args.eval_result)
    report_path = Path(args.council_report)

    if not eval_path.exists():
        print(f"ERROR: eval-result 파일 없음: {eval_path}", file=sys.stderr)
        return 1
    if not report_path.exists():
        print(f"ERROR: council-report 파일 없음: {report_path}", file=sys.stderr)
        return 1

    with open(eval_path, "r", encoding="utf-8") as f:
        eval_result = json.load(f)
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    verdict = eval_result.get("verdict", "FAIL")
    topic = report.get("topic", "unknown")
    total = eval_result.get("total", 0)

    if args.verbose:
        print(f"Routing: topic='{topic}' verdict={verdict} score={total}/40")

    handlers = {
        "PASS": handle_pass,
        "UNCERTAIN": handle_uncertain,
        "FAIL": handle_fail,
    }
    handler = handlers.get(verdict, handle_fail)

    result_msg = handler(eval_result, report, args.dry_run, args.verbose)
    print(result_msg)

    # vault 경로 추출 (PASS인 경우 index 업데이트용)
    vault_dest: Optional[Path] = None
    if verdict == "PASS" and not args.dry_run:
        vault_dir = resolve_vault_path(report)
        topic_slug = topic.replace(" ", "-").lower()[:50]
        date_str = datetime.now().strftime("%Y-%m-%d")
        vault_dest = vault_dir / f"{date_str}-{topic_slug}.md"

    # Wiki 업데이트
    append_wiki_log(verdict, result_msg, args.dry_run)
    if verdict == "PASS":
        update_wiki_index(report, eval_result, vault_dest, args.dry_run)

    return 0


if __name__ == "__main__":
    sys.exit(main())
