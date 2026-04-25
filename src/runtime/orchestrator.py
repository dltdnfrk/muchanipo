#!/usr/bin/env python3
"""
MuchaNipo Orchestrator — 전체 파이프라인 자동 루프
====================================================
program.md의 Interest Axis를 읽어 주제를 자동 선택하고,
전체 AutoResearch 파이프라인을 NEVER STOP 루프로 실행한다.

Usage:
    python3 orchestrator.py                    # 자율 루프 시작
    python3 orchestrator.py --topic "주제"     # 특정 주제 1회 실행
    python3 orchestrator.py --dry-run          # 주제 선택만 미리보기
    python3 orchestrator.py --max-rounds 5     # 최대 5라운드 후 종료
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
PROGRAM_MD = PROJECT_ROOT / "config" / "program.md"
WIKI_LOG = PROJECT_ROOT / "wiki" / "log.md"
LOCK_FILE = PROJECT_ROOT / ".orchestrator.lock"
RAW_DIR = PROJECT_ROOT / "raw"
LOGS_DIR = PROJECT_ROOT / "logs"

INGEST_SCRIPT = PROJECT_ROOT / "src" / "ingest" / "muchanipo-ingest.py"
INSIGHT_SCRIPT = PROJECT_ROOT / "src" / "search" / "insight-forge.py"
COUNCIL_SCRIPT = PROJECT_ROOT / "src" / "council" / "council-runner.py"
EVAL_SCRIPT = PROJECT_ROOT / "src" / "eval" / "eval-agent.py"
VAULT_SCRIPT = PROJECT_ROOT / "src" / "hitl" / "vault-router.py"

COOLDOWN_SECONDS = 30

# ---------------------------------------------------------------------------
# Interest Axis 정의 (program.md에서 파싱)
# ---------------------------------------------------------------------------

def parse_interest_axes(program_path: Path) -> list[dict[str, Any]]:
    """program.md에서 Interest Axis 목록을 파싱한다."""
    if not program_path.exists():
        return []

    axes: list[dict[str, Any]] = []
    content = program_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    current: dict[str, Any] | None = None
    for line in lines:
        stripped = line.strip()
        # 새 axis 시작: ### 1. NeoBio & AgTech
        if stripped.startswith("### ") and any(c.isdigit() for c in stripped[:8]):
            if current:
                axes.append(current)
            # 번호와 이름 분리
            parts = stripped.lstrip("# ").split(". ", 1)
            name = parts[1] if len(parts) > 1 else stripped.lstrip("# ")
            current = {"name": name, "keywords": [], "depth": "moderate"}
        elif current is not None:
            if stripped.startswith("- Keywords:"):
                kw_str = stripped[len("- Keywords:"):].strip()
                current["keywords"] = [k.strip() for k in kw_str.split(",")]
            elif stripped.startswith("- Depth:"):
                current["depth"] = stripped[len("- Depth:"):].strip()
            elif stripped.startswith("- Focus:"):
                current["focus"] = stripped[len("- Focus:"):].strip()

    if current:
        axes.append(current)

    return axes


def build_topic_pool(axes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    deep=3x, moderate=1x 비율로 토픽 풀 생성.
    각 axis에서 keywords를 조합하여 토픽 후보 생성.
    """
    pool: list[dict[str, Any]] = []
    for axis in axes:
        depth = axis.get("depth", "moderate")
        weight = 3 if depth == "deep" else 1
        keywords = axis.get("keywords", [])
        focus = axis.get("focus", "")

        # 키워드별 토픽 생성
        for kw in keywords:
            topic = {
                "axis": axis["name"],
                "topic": kw.strip(),
                "depth": depth,
                "focus": focus,
                "weight": weight,
            }
            for _ in range(weight):
                pool.append(topic)

    return pool


# ---------------------------------------------------------------------------
# Lock 파일 관리
# ---------------------------------------------------------------------------

def acquire_lock() -> bool:
    """Atomically create a PID lock file. Returns False when another process owns it."""
    while True:
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                pid = int(LOCK_FILE.read_text().strip())
                # stale lock 감지: PID가 살아있는지 확인
                os.kill(pid, 0)
                print(f"[LOCK] 이미 실행 중입니다 (PID {pid}). 종료합니다.")
                return False
            except (ValueError, ProcessLookupError):
                # stale lock: 제거하고 원자적 생성 재시도
                print("[LOCK] Stale lock 감지. 제거 후 진행합니다.")
                try:
                    LOCK_FILE.unlink()
                except FileNotFoundError:
                    pass
                continue
            except PermissionError:
                print("[LOCK] Lock 소유 프로세스 상태를 확인할 수 없습니다. 종료합니다.")
                return False
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
            return True


def release_lock() -> None:
    try:
        pid = int(LOCK_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return
    if pid == os.getpid():
        LOCK_FILE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 로깅
# ---------------------------------------------------------------------------

def log_wiki(action: str, details: str) -> None:
    """wiki/log.md에 append-only로 기록한다."""
    WIKI_LOG.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    entry = f"- {now} | {action} | {details}\n"
    with WIKI_LOG.open("a", encoding="utf-8") as f:
        f.write(entry)


def log_print(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# subprocess 실행 헬퍼
# ---------------------------------------------------------------------------

def run_script(
    script: Path,
    args: list[str],
    label: str,
    dry_run: bool = False,
    timeout: int = 300,
) -> tuple[bool, str]:
    """
    지정 스크립트를 subprocess로 실행한다.
    Returns: (success, output_or_error)
    """
    if not script.exists():
        msg = f"{script.name} 파일이 없습니다. 건너뜁니다."
        log_print(f"[WARN] {msg}")
        return False, msg

    cmd = [sys.executable, str(script)] + args
    log_print(f"[RUN] {label}: {' '.join(cmd)}")

    if dry_run:
        log_print(f"[DRY-RUN] 실행 생략: {cmd}")
        return True, "dry-run"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PROJECT_ROOT),
        )
        output = result.stdout.strip()
        err = result.stderr.strip()
        if result.returncode != 0:
            msg = f"returncode={result.returncode}\nstderr={err[:500]}"
            log_print(f"[FAIL] {label}: {msg}")
            return False, msg
        return True, output
    except subprocess.TimeoutExpired:
        msg = f"timeout after {timeout}s"
        log_print(f"[TIMEOUT] {label}: {msg}")
        return False, msg
    except Exception as e:
        msg = str(e)
        log_print(f"[ERROR] {label}: {msg}")
        return False, msg


# ---------------------------------------------------------------------------
# raw/ 디렉토리 스캔
# ---------------------------------------------------------------------------

def scan_raw_files() -> list[Path]:
    """raw/ 에서 처리 가능한 파일 목록 반환."""
    if not RAW_DIR.exists():
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        return []
    extensions = {".pdf", ".txt", ".md", ".docx"}
    files = [f for f in RAW_DIR.iterdir() if f.suffix.lower() in extensions]
    return sorted(files)


# ---------------------------------------------------------------------------
# 파이프라인 단계별 실행
# ---------------------------------------------------------------------------

def step_ingest(topic: str, raw_file: Optional[Path], dry_run: bool) -> tuple[bool, str]:
    """raw 파일 인제스트 또는 토픽 기반 인제스트."""
    if raw_file:
        ok, out = run_script(
            INGEST_SCRIPT,
            [str(raw_file), "--wing", "research"],
            "INGEST",
            dry_run=dry_run,
        )
    else:
        # 파일 없으면 topic 텍스트로 dry 인제스트 (insight-forge가 직접 검색)
        ok, out = True, "no-raw-file"
    return ok, out


def step_insight(topic: str, dry_run: bool) -> tuple[bool, str]:
    """InsightForge로 다차원 검색."""
    return run_script(
        INSIGHT_SCRIPT,
        [topic, "--depth", "deep", "--output", "json"],
        "INSIGHT",
        dry_run=dry_run,
    )


def step_council(topic: str, insight_output: str, dry_run: bool) -> tuple[bool, str]:
    """Council 토론 실행. 성공 시 council-report JSON 경로를 stdout으로 반환."""
    council_output = LOGS_DIR / f"council-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    args = [f"--topic={topic}", f"--output={council_output}"]
    ok, out = run_script(
        COUNCIL_SCRIPT,
        args,
        "COUNCIL",
        dry_run=dry_run,
    )
    if ok and council_output.exists():
        return True, str(council_output)
    # fallback: council-logs에서 최신 리포트 찾기
    reports = sorted(PROJECT_ROOT.glob("council-logs/*/council-report.json"), reverse=True)
    if reports:
        return ok, str(reports[0])
    return ok, out


def step_eval(council_report_path: str, dry_run: bool) -> tuple[bool, str]:
    """Eval-agent로 자동 채점. 성공 시 eval-result JSON 경로를 반환."""
    if not council_report_path or not Path(council_report_path).exists():
        # fallback: 최신 council report 검색
        reports = sorted(PROJECT_ROOT.glob("logs/council-report-*.json"), reverse=True)
        if not reports:
            reports = sorted(PROJECT_ROOT.glob("council-logs/*/council-report.json"), reverse=True)
        if reports:
            council_report_path = str(reports[0])
        else:
            return False, "council report 없음"
    eval_output = LOGS_DIR / f"eval-result-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    args = [council_report_path, f"--output={eval_output}"]
    ok, out = run_script(EVAL_SCRIPT, args, "EVAL", dry_run=dry_run)
    if ok and eval_output.exists():
        return True, str(eval_output)
    return ok, out


def step_vault(eval_result_path: str, council_report_path: str, dry_run: bool) -> tuple[bool, str]:
    """Vault-router로 라우팅. eval_result와 council_report 경로를 전달."""
    if not eval_result_path or not Path(eval_result_path).exists():
        return False, "eval result 파일 없음"
    if not council_report_path or not Path(council_report_path).exists():
        return False, "council report 파일 없음"
    args = [eval_result_path, council_report_path]
    if dry_run:
        args.append("--dry-run")
    return run_script(
        VAULT_SCRIPT,
        args,
        "VAULT",
        dry_run=False,  # dry_run은 args로 전달
    )


# ---------------------------------------------------------------------------
# 단일 토픽 파이프라인
# ---------------------------------------------------------------------------

def run_topic_pipeline(
    topic: dict[str, Any],
    dry_run: bool = False,
) -> bool:
    """
    한 토픽에 대해 전체 파이프라인을 실행한다.
    Returns True if pipeline succeeded (eval PASS), False otherwise.
    """
    topic_name = topic["topic"]
    axis = topic["axis"]
    log_print(f"[START] 토픽: {topic_name} (axis: {axis})")
    log_wiki("TOPIC_START", f"topic={topic_name} axis={axis}")

    # raw/ 파일 스캔
    raw_files = scan_raw_files()
    raw_file = raw_files[0] if raw_files else None
    if raw_file:
        log_print(f"[RAW] 인제스트 대상: {raw_file.name}")

    # 1. INGEST
    ok, out = step_ingest(topic_name, raw_file, dry_run)
    if not ok:
        log_wiki("INGEST_FAIL", f"topic={topic_name} err={out[:200]}")
        log_print(f"[SKIP] INGEST 실패. 다음 토픽으로.")
        return False
    log_wiki("INGEST_OK", f"topic={topic_name}")

    # raw 파일 처리 후 이동 (processed/)
    if raw_file and not dry_run:
        processed_dir = RAW_DIR.parent / "processed"
        processed_dir.mkdir(exist_ok=True)
        dest = processed_dir / raw_file.name
        raw_file.rename(dest)
        log_print(f"[RAW] {raw_file.name} → processed/")

    # 2. INSIGHT
    ok, insight_out = step_insight(topic_name, dry_run)
    if not ok:
        log_wiki("INSIGHT_FAIL", f"topic={topic_name} err={insight_out[:200]}")
        log_print(f"[WARN] INSIGHT 실패. 계속 진행.")
    else:
        log_wiki("INSIGHT_OK", f"topic={topic_name}")

    # 3. COUNCIL → council_report_path 반환
    ok, council_report_path = step_council(topic_name, insight_out, dry_run)
    if not ok:
        log_wiki("COUNCIL_FAIL", f"topic={topic_name} err={council_report_path[:200]}")
        log_print(f"[SKIP] COUNCIL 실패. 다음 토픽으로.")
        return False
    log_wiki("COUNCIL_OK", f"topic={topic_name} report={council_report_path}")

    # 4. EVAL → eval_result_path 반환
    ok, eval_result_path = step_eval(council_report_path, dry_run)
    if not ok:
        log_wiki("EVAL_FAIL", f"topic={topic_name} err={eval_result_path[:200]}")
        log_print(f"[WARN] EVAL 실패.")
    else:
        log_wiki("EVAL_OK", f"topic={topic_name} result={eval_result_path}")

    # 5. VAULT ROUTER — eval_result + council_report 전달
    ok, vault_out = step_vault(eval_result_path, council_report_path, dry_run)
    if not ok:
        log_wiki("VAULT_FAIL", f"topic={topic_name} err={vault_out[:200]}")
    else:
        log_wiki("VAULT_OK", f"topic={topic_name}")

    log_wiki("TOPIC_DONE", f"topic={topic_name}")
    log_print(f"[DONE] 토픽 완료: {topic_name}")
    return True


# ---------------------------------------------------------------------------
# 토픽 선택기 (round-robin with weight)
# ---------------------------------------------------------------------------

class TopicSelector:
    """Interest Axis를 순환하며 토픽을 선택한다."""

    def __init__(self, axes: list[dict[str, Any]]) -> None:
        self.axes = axes
        self.pool = build_topic_pool(axes)
        self._index = 0
        self._used: set[str] = set()

    def next(self) -> dict[str, Any]:
        """다음 토픽을 반환한다. 풀이 소진되면 리셋."""
        if not self.pool:
            return {"axis": "Unknown", "topic": "autoresearch", "depth": "light", "focus": "", "weight": 1}

        # 사용하지 않은 토픽 우선
        unused = [t for t in self.pool if t["topic"] not in self._used]
        if not unused:
            # 모두 사용했으면 리셋
            self._used.clear()
            unused = self.pool

        # 가중치 순환: pool 인덱스 기반
        topic = unused[self._index % len(unused)]
        self._index += 1
        self._used.add(topic["topic"])
        return topic

    def preview(self, n: int = 8) -> list[str]:
        """다음 n개 토픽 미리보기."""
        preview_pool = list(self.pool)
        if not preview_pool:
            return []
        seen: set[str] = set()
        result: list[str] = []
        idx = 0
        while len(result) < n and idx < len(preview_pool) * 2:
            t = preview_pool[idx % len(preview_pool)]
            idx += 1
            if t["topic"] not in seen:
                seen.add(t["topic"])
                result.append(f"[{t['axis']}] {t['topic']} (depth={t['depth']})")
        return result


# ---------------------------------------------------------------------------
# 메인 실행
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="MuchaNipo Orchestrator — 전체 파이프라인 자동 루프",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--topic", metavar="TOPIC", help="특정 주제 1회 실행")
    parser.add_argument("--dry-run", action="store_true", help="주제 선택만 미리보기 (실제 실행 없음)")
    parser.add_argument("--max-rounds", type=int, default=0, help="최대 라운드 수 (0=무제한)")
    parser.add_argument("--cooldown", type=int, default=COOLDOWN_SECONDS, help="라운드 간 쿨다운(초)")
    args = parser.parse_args()

    # Enforce minimum cooldown to prevent CPU spin
    args.cooldown = max(5, args.cooldown)

    # 디렉토리 초기화
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    WIKI_LOG.parent.mkdir(parents=True, exist_ok=True)

    # program.md 파싱
    axes = parse_interest_axes(PROGRAM_MD)
    if not axes:
        print(f"[ERROR] program.md에서 Interest Axis를 파싱하지 못했습니다: {PROGRAM_MD}")
        sys.exit(1)

    selector = TopicSelector(axes)

    # --dry-run: 토픽 미리보기만
    if args.dry_run:
        print("\n[DRY-RUN] 다음 토픽 후보 (program.md 기반):")
        for i, line in enumerate(selector.preview(10), 1):
            print(f"  {i:2}. {line}")
        print(f"\n  총 Interest Axes: {len(axes)}개")
        print(f"  총 토픽 풀 크기: {len(selector.pool)}개 (가중치 포함)")
        if args.topic:
            print(f"\n  지정 토픽: {args.topic} (dry-run으로 실행 생략)")
        return

    # --topic: 단일 토픽 1회 실행
    if args.topic:
        topic_obj = {
            "axis": "Manual",
            "topic": args.topic,
            "depth": "deep",
            "focus": "",
            "weight": 1,
        }
        log_wiki("MANUAL_RUN", f"topic={args.topic}")
        run_topic_pipeline(topic_obj, dry_run=False)
        return

    # 자율 루프 시작
    if not acquire_lock():
        sys.exit(1)

    # SIGINT / SIGTERM 처리
    stop_flag = {"stop": False}

    def _handle_signal(signum: int, frame: Any) -> None:
        log_print("[SIGNAL] 종료 신호 수신. 현재 라운드 완료 후 종료합니다.")
        log_wiki("SIGNAL", f"signum={signum}")
        stop_flag["stop"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log_print(f"[ORCHESTRATOR] 자율 루프 시작. max_rounds={args.max_rounds or '무제한'}, cooldown={args.cooldown}s")
    log_wiki("LOOP_START", f"max_rounds={args.max_rounds} cooldown={args.cooldown}")

    round_count = 0
    try:
        while not stop_flag["stop"]:
            if args.max_rounds > 0 and round_count >= args.max_rounds:
                log_print(f"[ORCHESTRATOR] max_rounds={args.max_rounds} 도달. 종료합니다.")
                log_wiki("LOOP_MAX_ROUNDS", f"rounds={round_count}")
                break

            round_count += 1
            topic = selector.next()
            log_print(f"[ROUND {round_count}] 시작")

            try:
                run_topic_pipeline(topic, dry_run=False)
            except Exception as e:
                msg = str(e)
                log_print(f"[ERROR] 파이프라인 예외: {msg}")
                log_wiki("PIPELINE_ERROR", f"topic={topic['topic']} err={msg[:200]}")

            if stop_flag["stop"]:
                break

            log_print(f"[COOLDOWN] {args.cooldown}초 대기 중...")
            # 쿨다운 중에도 신호 감지
            for _ in range(args.cooldown):
                if stop_flag["stop"]:
                    break
                time.sleep(1)

    finally:
        release_lock()
        log_wiki("LOOP_END", f"rounds={round_count}")
        log_print(f"[ORCHESTRATOR] 종료. 총 {round_count} 라운드 완료.")


if __name__ == "__main__":
    main()
