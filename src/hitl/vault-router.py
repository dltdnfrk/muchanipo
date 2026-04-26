#!/usr/bin/env python3
"""
MuchaNipo Vault Router -- Eval 결과를 Obsidian Vault로 라우팅
=============================================================
eval-agent.py 결과(eval-result.json)를 읽고 자동 라우팅:
  PASS      → Obsidian vault에 마크다운 저장 (GBrain 패턴)
  UNCERTAIN → signoff-queue/에 JSON 저장
  FAIL      → logs/failed/에 이동
  모든 결과 → wiki/log.md 기록 + wiki/index.md 업데이트

GBrain 패턴 채용 (garrytan/gbrain):
  - Compiled Truth + Timeline 2-layer 페이지 구조
  - content_hash(SHA-256)로 idempotent import
  - Stale detection: compiled_truth가 최신 timeline보다 오래되면 [STALE] 표시
  - Frontmatter에 구조화 메타데이터 (type, tags, aliases, confidence)
  - Page versioning: 기존 compiled_truth를 versions/에 스냅샷 보관
  - 단일 entity = 단일 파일 원칙 (slug 기반 dedup)

Usage:
    python3 vault-router.py eval-result.json council-report.json
    python3 vault-router.py eval-result.json council-report.json --dry-run
    python3 vault-router.py eval-result.json council-report.json --verbose
"""

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def _load_runtime_paths():
    spec = importlib.util.spec_from_file_location(
        "muchanipo_runtime_paths",
        SCRIPT_DIR.parent / "runtime" / "paths.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_runtime_paths = _load_runtime_paths()
CONFIG_PATH = _runtime_paths.get_config_path()

# GBrain 패턴: Page type 정의 (garrytan/gbrain types.ts 참조)
GBRAIN_PAGE_TYPES = [
    "person", "company", "deal", "project", "concept",
    "source", "media", "meeting", "idea",
]

# GBrain 패턴: versions 디렉토리 (page_versions 테이블의 파일시스템 대응)
VERSIONS_DIR = SCRIPT_DIR / "versions"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def load_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def score_max(eval_result: Dict[str, Any]) -> int:
    explicit = eval_result.get("rubric_max")
    if isinstance(explicit, int) and explicit > 0:
        return explicit
    rubric_path = _runtime_paths.get_rubric_path()
    if rubric_path.exists():
        with open(rubric_path, "r", encoding="utf-8") as f:
            return _runtime_paths.rubric_score_max(json.load(f))
    return 100


# ---------------------------------------------------------------------------
# GBrain 패턴: Content Hash (import idempotency, gbrain import-file.ts 참조)
# ---------------------------------------------------------------------------
def compute_content_hash(content: str) -> str:
    """SHA-256 content hash — GBrain이 import 시 중복 판별에 사용하는 동일 방식."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# GBrain 패턴: Slug 생성 (gbrain markdown.ts inferSlug 참조)
# ---------------------------------------------------------------------------
def topic_to_slug(topic: str) -> str:
    """토픽 문자열을 GBrain 호환 slug로 변환.

    GBrain: 파일명에서 .md 제거, 소문자, / 구분. 여기선 한글+영문 지원.
    """
    slug = topic.strip().lower()
    slug = re.sub(r"[^\w\s가-힣-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return slug[:60]


# ---------------------------------------------------------------------------
# GBrain 패턴: Stale Detection (search/hybrid.ts stale alert 참조)
# ---------------------------------------------------------------------------
def detect_stale(compiled_truth_updated: datetime, latest_timeline_date: Optional[datetime]) -> bool:
    """Compiled Truth가 최신 Timeline 항목보다 오래되면 stale.

    GBrain 원본: search 결과에 stale 플래그 부착. 여기선 페이지 저장 시 감지.
    """
    if latest_timeline_date is None:
        return False
    return compiled_truth_updated < latest_timeline_date


# ---------------------------------------------------------------------------
# GBrain 패턴: Page Versioning (page_versions 테이블의 파일시스템 대응)
# ---------------------------------------------------------------------------
def snapshot_version(
    dest: Path,
    dry_run: bool = False,
) -> Optional[Path]:
    """기존 파일의 compiled_truth를 versions/에 스냅샷 보관.

    GBrain page_versions: compiled_truth + frontmatter + snapshot_at 저장.
    파일시스템 대응으로 전체 파일을 타임스탬프 파일명으로 복사.
    """
    if not dest.exists() or dry_run:
        return None
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    version_path = VERSIONS_DIR / f"{dest.stem}--{ts}{dest.suffix}"
    version_path.write_text(dest.read_text(encoding="utf-8"), encoding="utf-8")
    return version_path


# ---------------------------------------------------------------------------
# GBrain 패턴: Existing Page Detection (slug 기반 단일 entity = 단일 파일)
# ---------------------------------------------------------------------------
def find_existing_page(vault_dir: Path, topic_slug: str) -> Optional[Path]:
    """같은 slug를 가진 기존 페이지를 찾는다. GBrain의 putPage는 slug UNIQUE.

    날짜 프리픽스가 다를 수 있으므로 slug 부분으로 매칭.
    """
    for md_file in vault_dir.glob("*.md"):
        # 파일명에서 날짜 프리픽스(YYYY-MM-DD-) 제거 후 slug 비교
        name_without_ext = md_file.stem
        # 패턴: 2026-04-09-topic-slug
        parts = name_without_ext.split("-", 3)
        if len(parts) >= 4:
            file_slug = parts[3]
        else:
            file_slug = name_without_ext
        if file_slug == topic_slug:
            return md_file
    return None


# ---------------------------------------------------------------------------
# GBrain 패턴: Timeline 파싱 (가장 최근 날짜 추출)
# ---------------------------------------------------------------------------
def extract_latest_timeline_date(timeline_text: str) -> Optional[datetime]:
    """Timeline 섹션에서 가장 최근 날짜를 파싱."""
    dates = re.findall(r"(\d{4}-\d{2}-\d{2})", timeline_text)
    if not dates:
        return None
    latest = max(dates)
    try:
        return datetime.strptime(latest, "%Y-%m-%d")
    except ValueError:
        return None


def resolve_vault_path(report: Dict[str, Any]) -> Path:
    """Interest axis 키워드 매칭으로 vault 저장 경로 결정."""
    config = load_config()
    axes = config.get("interest_axes", [])
    topic = report.get("topic", "").lower()

    for axis in axes:
        keywords = [kw.lower() for kw in axis.get("keywords", [])]
        if any(kw in topic for kw in keywords):
            vault_path = axis.get("vault_path", "")
            return _runtime_paths.resolve_vault_path_setting(vault_path, create=True)

    # 기본: Feed 디렉토리
    return _runtime_paths.get_vault_path("Feed", create=True)


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
    lines.append(f"- **총점**: {total}/{score_max(eval_result)} (confidence: {confidence:.2f})")
    lines.append("")

    return "\n".join(lines)


def build_timeline_entry(eval_result: Dict[str, Any], council_id: str) -> str:
    """Timeline 섹션에 추가할 단일 항목 (append-only)."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    verdict = eval_result.get("verdict", "?")
    total = eval_result.get("total", 0)
    return f"- {now} | {verdict} | score={total}/{score_max(eval_result)} | council_id={council_id}\n"


def build_frontmatter(
    report: Dict[str, Any],
    eval_result: Dict[str, Any],
    content_hash: Optional[str] = None,
) -> str:
    """YAML frontmatter 생성.

    GBrain 패턴 반영:
    - slug: 페이지 고유 식별자 (gbrain pages.slug UNIQUE)
    - type: 9가지 page type 중 하나 (gbrain types.ts PageType)
    - content_hash: SHA-256 (gbrain import idempotency)
    - aliases: 동일 주제의 대체 이름 (gbrain RECOMMENDED_SCHEMA)
    """
    topic = report.get("topic", "unknown")
    council_id = report.get("council_id", "unknown")
    confidence = report.get("confidence", 0.0)
    tags = report.get("tags", [])
    date_str = datetime.now().strftime("%Y-%m-%d")
    slug = topic_to_slug(topic)

    # interest axis 매칭으로 type 결정
    config = load_config()
    axes = config.get("interest_axes", [])
    topic_lower = topic.lower()
    axis_type = "concept"  # GBrain 기본: concept
    for axis in axes:
        keywords = [kw.lower() for kw in axis.get("keywords", [])]
        if any(kw in topic_lower for kw in keywords):
            axis_type = axis.get("id", "concept")
            break
    # GBrain page type으로 정규화
    if axis_type not in GBRAIN_PAGE_TYPES:
        axis_type = "concept"

    fm_lines = [
        "---",
        f"title: \"{topic}\"",
        f"slug: {slug}",
        f"type: {axis_type}",
        f"date: {date_str}",
        f"source: muchanipo-autoresearch",
        f"council_id: {council_id}",
        f"confidence: {confidence:.2f}",
    ]

    if content_hash:
        fm_lines.append(f"content_hash: {content_hash}")

    if tags:
        tag_str = ", ".join(f'"{t}"' for t in tags)
        fm_lines.append(f"tags: [{tag_str}]")

    # GBrain 패턴: aliases (RECOMMENDED_SCHEMA 참조)
    aliases = report.get("aliases", [])
    if aliases:
        alias_str = ", ".join(f'"{a}"' for a in aliases)
        fm_lines.append(f"aliases: [{alias_str}]")

    fm_lines.append("---")
    fm_lines.append("")
    return "\n".join(fm_lines)


def save_markdown_to_vault(
    report: Dict[str, Any],
    eval_result: Dict[str, Any],
    vault_dir: Path,
    dry_run: bool = False,
) -> Path:
    """Vault에 마크다운 저장.

    GBrain 패턴 (garrytan/gbrain markdown.ts + import-file.ts):
    1. slug 기반 기존 페이지 탐색 (단일 entity = 단일 파일)
    2. content_hash로 idempotent 저장 (변경 없으면 skip)
    3. 기존 파일이 있으면 page version 스냅샷 생성
    4. Compiled Truth는 REWRITE (append 아님, ingest SKILL.md 규칙)
    5. Timeline은 append-only (절대 수정 안 함)
    6. Compiled Truth와 Timeline은 --- 구분자로 분리 (gbrain splitBody)
    7. Stale detection: compiled_truth < latest_timeline이면 경고
    """
    topic = report.get("topic", "untitled")
    topic_slug = topic_to_slug(topic)
    date_str = datetime.now().strftime("%Y-%m-%d")

    # GBrain 패턴: slug 기반 기존 페이지 검색 (putPage slug UNIQUE)
    existing_page = find_existing_page(vault_dir, topic_slug)
    if existing_page:
        dest = existing_page  # 기존 파일 위치 유지
    else:
        filename = f"{date_str}-{topic_slug}.md"
        dest = vault_dir / filename

    if dry_run:
        print(f"  [DRY-RUN] would write: {dest}")
        return dest

    # GBrain 패턴: 기존 Timeline 보존 + 기존 compiled_truth에서 stale 감지
    existing_timeline = ""
    existing_content_hash = ""
    if dest.exists():
        existing_content = dest.read_text(encoding="utf-8")

        # content_hash 추출 (frontmatter에서)
        hash_match = re.search(r"content_hash:\s*(\S+)", existing_content)
        if hash_match:
            existing_content_hash = hash_match.group(1)

        # GBrain 패턴: Timeline 추출 (--- 구분자 이후)
        # gbrain markdown.ts splitBody: 첫 standalone --- 이후가 timeline
        if "\n---\n" in existing_content:
            # frontmatter 이후의 첫 --- 를 찾아야 함
            # frontmatter 끝(두 번째 ---) 이후 본문에서 --- 검색
            body_start = existing_content.find("---", existing_content.find("---") + 3)
            if body_start != -1:
                body = existing_content[body_start + 3:]
                separator_pos = body.find("\n---\n")
                if separator_pos != -1:
                    existing_timeline = body[separator_pos + 5:].strip()

        # 레거시 호환: ## Timeline 헤더로도 검색
        if not existing_timeline and "## Timeline" in existing_content:
            timeline_start = existing_content.index("## Timeline")
            raw_timeline = existing_content[timeline_start:]
            # ## Timeline 헤더 제거, 내용만 추출
            existing_timeline = raw_timeline.replace("## Timeline", "").strip()

    # 새 컨텐츠 조합
    council_id = report.get("council_id", "unknown")
    compiled_truth = build_compiled_truth(report, eval_result)
    new_timeline_entry = build_timeline_entry(eval_result, council_id)

    # GBrain 패턴: content_hash 계산 (import idempotency)
    new_content_hash = compute_content_hash(compiled_truth)

    # Idempotency: 내용이 동일하면 timeline만 추가
    content_changed = new_content_hash != existing_content_hash

    # GBrain 패턴: 기존 파일이 있고 내용이 변경되면 version 스냅샷
    if dest.exists() and content_changed:
        snapshot_version(dest, dry_run)

    # Frontmatter 생성 (content_hash 포함)
    frontmatter = build_frontmatter(report, eval_result, content_hash=new_content_hash)

    # GBrain 패턴: Timeline은 append-only (newest first = reverse-chrono)
    if existing_timeline:
        timeline_content = new_timeline_entry + existing_timeline
    else:
        timeline_content = new_timeline_entry

    # GBrain 패턴: Stale detection
    stale_warning = ""
    latest_tl_date = extract_latest_timeline_date(timeline_content)
    if latest_tl_date and detect_stale(datetime.now().replace(hour=0, minute=0, second=0), latest_tl_date):
        stale_warning = "\n> [!warning] STALE\n> Compiled Truth가 최신 Timeline보다 오래되었습니다. 리뷰 필요.\n\n"

    # GBrain 페이지 구조: frontmatter + compiled_truth + --- + timeline
    # (gbrain markdown.ts serializeMarkdown 참조)
    content = (
        frontmatter
        + f"# {topic}\n\n"
        + stale_warning
        + compiled_truth
        + "\n---\n\n"  # GBrain separator: compiled_truth와 timeline 분리
        + "## Timeline\n"
        + "<!-- Append-only. 절대 수정하지 않고 추가만. 증거 추적용. (GBrain 패턴) -->\n\n"
        + timeline_content
    )

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
        print(f"Routing: topic='{topic}' verdict={verdict} score={total}/{score_max(eval_result)}")

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
