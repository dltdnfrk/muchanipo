"""Autoresearch-backed product guard for Muchanipo itself.

This module turns the "keep researching until validated" loop into a local
product-quality barrier. It does not call provider APIs and it does not mutate
the repo under review; it writes mission/result artifacts under `.omx/` and a
Karpathy-style `results.tsv` under `.omc/`.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.pipeline.reference_inventory import reference_readiness_report
from src.research.karpathy_autoresearch import UPSTREAM_REVISION
from src.safety.lockdown import SECRET_PATTERNS


SCHEMA_VERSION = 1
DEFAULT_COMPLETION_ARTIFACT = Path(".omx/specs/autoresearch-product-guard/result.json")
DEFAULT_RESULTS_TSV = Path(".omc/autoresearch/product-guard/results.tsv")
MISSION_PATH = Path(".omx/specs/autoresearch-product-guard/mission.md")
SANDBOX_PATH = Path(".omx/specs/autoresearch-product-guard/sandbox.md")
METRIC_NAME = "product_security_risk_score"
METRIC_DIRECTION = "lower_is_better"
RUNTIME_SMOKE_TIMEOUT_SEC = 90
RUNTIME_SMOKE_TOPIC = "한 문장 제품 정의"
RUNTIME_STAGES = (
    "intake",
    "interview",
    "targeting",
    "research",
    "evidence",
    "council",
    "report",
    "vault",
    "agents",
    "finalize",
)
FORBIDDEN_REPORT_MARKERS = (
    "mock-evidence",
    "empty-evidence",
    "Mock research evidence",
    "조건부 권고",
    "성공 기준은",
    "Round 7 synthesis",
    "Trusted evidence: 0",
)
SCAN_SUFFIXES = {
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".rs",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".md",
}
SKIP_PARTS = {
    ".git",
    ".omc",
    ".omx",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "target",
    "dist",
    "build",
    ".next",
    "third_party",
    "vendor",
    "signoff-queue",
}
MAX_SCAN_BYTES = 512_000
ALLOWED_TEST_SECRET_FRAGMENTS = {
    "abcdefghijklmnopqrst",
    "user@example.com",
}

DANGEROUS_PATTERNS: Sequence[tuple[str, re.Pattern[str], str]] = (
    ("shell_true", re.compile(r"\bshell\s*=\s*True\b"), "subprocess shell=True needs explicit justification"),
    ("eval_exec", re.compile(r"\b(eval|exec)\s*\("), "dynamic Python execution should stay out of runtime paths"),
    ("pickle_loads", re.compile(r"\bpickle\.loads?\s*\("), "pickle loading is unsafe for untrusted data"),
    ("rm_rf", re.compile(r"\brm\s+-rf\b"), "destructive deletion command must remain outside autonomous paths"),
    ("git_reset_hard", re.compile(r"\bgit\s+reset\s+--hard\b"), "hard reset must not be used by product automation"),
    ("network_push", re.compile(r"\b(git\s+push|gh\s+pr\s+merge|gh\s+release)\b"), "network write/publish path needs explicit human approval"),
    ("curl_pipe_shell", re.compile(r"\b(curl|wget)\b[^\n|]*\|\s*(sh|bash)\b"), "curl|shell install pattern must not be automated"),
)


@dataclass(frozen=True)
class GuardFinding:
    path: str
    line: int
    kind: str
    message: str
    severity: str = "warning"
    excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GuardCheck:
    id: str
    status: str
    severity: str
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    findings: tuple[GuardFinding, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["findings"] = [finding.to_dict() for finding in self.findings]
        return payload


@dataclass(frozen=True)
class RuntimeSmokeResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    elapsed_sec: float
    report_path: Path
    events_path: Path


def run_product_guard(
    *,
    repo_root: Path | str | None = None,
    output_path: Path | str | None = None,
    strict: bool = False,
    include_untracked: bool = True,
) -> dict[str, Any]:
    """Run the local product guard and write an artifact-gated result."""
    root = Path(repo_root or Path.cwd()).resolve()
    completion_artifact = root / (Path(output_path) if output_path else DEFAULT_COMPLETION_ARTIFACT)
    checks = [
        _check_reference_parity(root),
        _check_karpathy_autoresearch_surface(root),
        _check_runtime_truth_smoke(root),
        _check_secret_scan(root, include_untracked=include_untracked),
        _check_dangerous_patterns(root, include_untracked=include_untracked),
    ]
    warnings = [
        finding.to_dict()
        for check in checks
        for finding in check.findings
        if finding.severity == "warning"
    ]
    blockers = [
        finding.to_dict()
        for check in checks
        for finding in check.findings
        if finding.severity == "blocker"
    ]
    failed_checks = [check.id for check in checks if check.status == "failed"]
    if strict:
        failed_checks.extend(check.id for check in checks if check.status == "warning")
    passed = not failed_checks and not blockers
    risk_score = _risk_score(checks, strict=strict)
    generated_at = datetime.now(timezone.utc).isoformat()
    mission_path = root / MISSION_PATH
    sandbox_path = root / SANDBOX_PATH
    results_path = root / DEFAULT_RESULTS_TSV
    _write_mission_artifacts(mission_path=mission_path, sandbox_path=sandbox_path)
    _append_results_tsv(
        results_path,
        repo_root=root,
        risk_score=risk_score,
        status="keep" if passed else "discard",
        description="product guard completion audit",
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "command": "muchanipo guard",
        "status": "passed" if passed else "failed",
        "passed": passed,
        "strict": strict,
        "generated_at": generated_at,
        "summary": _summary(passed=passed, checks=checks, warnings=warnings, blockers=blockers),
        "autoresearch": {
            "validation_mode": "mission-validator-script",
            "completion_artifact_path": _display_path(completion_artifact, root),
            "mission_path": _display_path(mission_path, root),
            "sandbox_path": _display_path(sandbox_path, root),
            "results_path": _display_path(results_path, root),
            "metric_name": METRIC_NAME,
            "metric_direction": METRIC_DIRECTION,
            "metric": risk_score,
            "upstream_revision": UPSTREAM_REVISION,
        },
        "checks": [check.to_dict() for check in checks],
        "warnings": warnings,
        "blockers": blockers,
    }
    completion_artifact.parent.mkdir(parents=True, exist_ok=True)
    completion_artifact.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def run_product_guard_iterations(
    *,
    repo_root: Path | str | None = None,
    output_path: Path | str | None = None,
    strict: bool = True,
    include_untracked: bool = True,
    min_iterations: int = 3,
    max_iterations: int = 5,
) -> dict[str, Any]:
    """Run the product guard until clean findings are stable across iterations."""
    root = Path(repo_root or Path.cwd()).resolve()
    completion_artifact = root / (Path(output_path) if output_path else DEFAULT_COMPLETION_ARTIFACT)
    min_iterations = max(1, int(min_iterations))
    max_iterations = max(min_iterations, int(max_iterations))
    iterations: list[dict[str, Any]] = []
    previous_signature: tuple[Any, ...] | None = None
    stable_iterations = 0
    report: dict[str, Any] | None = None

    for iteration in range(1, max_iterations + 1):
        report = run_product_guard(
            repo_root=root,
            output_path=completion_artifact,
            strict=strict,
            include_untracked=include_untracked,
        )
        signature = _issue_signature(report)
        stable_iterations = stable_iterations + 1 if signature == previous_signature else 1
        previous_signature = signature
        clean = bool(report["passed"] and not report["warnings"] and not report["blockers"])
        iterations.append(
            {
                "iteration": iteration,
                "status": report["status"],
                "passed": report["passed"],
                "metric": report["autoresearch"]["metric"],
                "warning_count": len(report["warnings"]),
                "blocker_count": len(report["blockers"]),
                "signature": list(signature),
                "stable_iterations": stable_iterations,
                "clean": clean,
            }
        )
        if iteration >= min_iterations and clean and stable_iterations >= min_iterations:
            break

    assert report is not None
    stable_clean = bool(
        iterations
        and iterations[-1]["clean"]
        and iterations[-1]["stable_iterations"] >= min_iterations
    )
    report = dict(report)
    report["status"] = "passed" if stable_clean else "failed"
    report["passed"] = stable_clean
    report["summary"] = (
        f"iterative product guard passed: {len(iterations)} stable clean iteration(s)"
        if stable_clean
        else f"iterative product guard failed to stabilize after {len(iterations)} iteration(s)"
    )
    report["iterations"] = iterations
    report["autoresearch"] = {
        **report["autoresearch"],
        "iteration_mode": "iterative_stability",
        "iteration_count": len(iterations),
        "min_iterations": min_iterations,
        "max_iterations": max_iterations,
        "stable_iterations": iterations[-1]["stable_iterations"] if iterations else 0,
        "zero_warning_required": True,
    }
    completion_artifact.parent.mkdir(parents=True, exist_ok=True)
    completion_artifact.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def render_product_guard(report: dict[str, Any], *, stdout: Any | None = None) -> None:
    import sys

    out = stdout or sys.stdout
    out.write("\nAutoresearch product guard\n")
    out.write("--------------------------\n")
    out.write(f"status: {report['status']}\n")
    out.write(f"metric: {report['autoresearch']['metric']} ({METRIC_NAME}, {METRIC_DIRECTION})\n")
    out.write(f"artifact: {report['autoresearch']['completion_artifact_path']}\n")
    if report["autoresearch"].get("iteration_mode"):
        out.write(
            "iterations: "
            f"{report['autoresearch'].get('iteration_count')} "
            f"(stable {report['autoresearch'].get('stable_iterations')})\n"
        )
    for check in report["checks"]:
        out.write(f"- {check['id']}: {check['status']} — {check['summary']}\n")
    if report["blockers"]:
        out.write("\nBlockers\n")
        for finding in report["blockers"][:10]:
            out.write(f"- {finding['path']}:{finding['line']} {finding['kind']} — {finding['message']}\n")
    if report["warnings"]:
        out.write("\nWarnings\n")
        for finding in report["warnings"][:10]:
            out.write(f"- {finding['path']}:{finding['line']} {finding['kind']} — {finding['message']}\n")
    out.write("\n")
    out.flush()


def _check_reference_parity(root: Path) -> GuardCheck:
    report = reference_readiness_report(repo_root=root)
    failing = [
        stage
        for stage in report.get("stages", [])
        if not stage.get("ready") or not stage.get("product_standard_ready") or stage.get("gap_count")
    ]
    findings = tuple(
        GuardFinding(
            path="src/pipeline/reference_inventory.py",
            line=1,
            kind="reference_parity",
            severity="blocker",
            message=f"stage {stage.get('step')} is not product-standard ready",
            excerpt=str(stage.get("references", [])),
        )
        for stage in failing
    )
    return GuardCheck(
        id="six_stage_reference_parity",
        status="failed" if failing else "passed",
        severity="blocker",
        summary="all six stages are runtime/product-standard ready" if not failing else f"{len(failing)} stage(s) not ready",
        evidence={
            "stage_count": len(report.get("stages", [])),
            "not_stage_contract_covered_references": report.get("not_stage_contract_covered_references", []),
            "license_warning_count": len(report.get("license_warnings", [])),
        },
        findings=findings,
    )


def _check_karpathy_autoresearch_surface(root: Path) -> GuardCheck:
    required = [
        root / "third_party/karpathy-autoresearch/UPSTREAM.md",
        root / "third_party/karpathy-autoresearch/program.md",
        root / "third_party/karpathy-autoresearch/train.py",
        root / "third_party/karpathy-autoresearch/prepare.py",
        root / "src/research/karpathy_autoresearch.py",
    ]
    missing = [path for path in required if not path.exists()]
    findings = tuple(
        GuardFinding(
            path=_display_path(path, root),
            line=1,
            kind="missing_autoresearch_surface",
            severity="blocker",
            message="required Karpathy Autoresearch vendored/adapter file is missing",
        )
        for path in missing
    )
    return GuardCheck(
        id="karpathy_autoresearch_surface",
        status="failed" if missing else "passed",
        severity="blocker",
        summary="vendored Autoresearch source and Muchanipo adapter are present" if not missing else f"{len(missing)} required file(s) missing",
        evidence={
            "upstream_revision": UPSTREAM_REVISION,
            "required_paths": [_display_path(path, root) for path in required],
        },
        findings=findings,
    )


def _check_runtime_truth_smoke(root: Path) -> GuardCheck:
    result = _run_runtime_truth_smoke(root)
    events = _parse_jsonl_events(result.stdout)
    result.events_path.parent.mkdir(parents=True, exist_ok=True)
    result.events_path.write_text(result.stdout, encoding="utf-8")

    findings: list[GuardFinding] = []
    smoke_path = _display_path(result.events_path, root)
    report_path = _display_path(result.report_path, root)
    if result.timed_out:
        findings.append(
            GuardFinding(
                path=smoke_path,
                line=1,
                kind="runtime_timeout",
                severity="blocker",
                message=f"full pipeline runtime smoke exceeded {RUNTIME_SMOKE_TIMEOUT_SEC}s",
            )
        )
    if result.returncode != 0:
        findings.append(
            GuardFinding(
                path=smoke_path,
                line=1,
                kind="runtime_nonzero_exit",
                severity="blocker",
                message=f"full pipeline runtime smoke exited with {result.returncode}",
                excerpt=result.stderr.strip()[:240],
            )
        )

    started = [str(event.get("stage") or "") for event in events if event.get("event") == "stage_started"]
    completed = [str(event.get("stage") or "") for event in events if event.get("event") == "stage_completed"]
    if started != list(RUNTIME_STAGES):
        findings.append(
            GuardFinding(
                path=smoke_path,
                line=1,
                kind="runtime_stage_started_mismatch",
                severity="blocker",
                message="runtime smoke did not start all expected stages in order",
                excerpt=str(started),
            )
        )
    if completed != list(RUNTIME_STAGES):
        findings.append(
            GuardFinding(
                path=smoke_path,
                line=1,
                kind="runtime_stage_completed_mismatch",
                severity="blocker",
                message="runtime smoke did not complete all expected stages in order",
                excerpt=str(completed),
            )
        )

    started_by_stage = {
        str(event.get("stage") or ""): event
        for event in events
        if event.get("event") == "stage_started"
    }
    for stage in ("targeting", "research"):
        refs = started_by_stage.get(stage, {}).get("reference_projects") or []
        if not refs:
            findings.append(
                GuardFinding(
                    path=smoke_path,
                    line=1,
                    kind="runtime_reference_metadata_missing",
                    severity="blocker",
                    message=f"{stage} runtime event is missing reference_projects metadata",
                )
            )

    run_started = next((event for event in events if event.get("event") == "run_started"), {})
    if run_started.get("offline") is not True or run_started.get("source_research") is not True:
        findings.append(
            GuardFinding(
                path=smoke_path,
                line=1,
                kind="runtime_mode_mismatch",
                severity="blocker",
                message="runtime smoke must run offline with source_research enabled",
                excerpt=json.dumps(run_started, ensure_ascii=False)[:240],
            )
        )

    research_progress = [event for event in events if event.get("event") == "research_progress"]
    source_found = [
        event
        for event in research_progress
        if event.get("status") == "source_found"
        and str(event.get("source_title") or "").strip()
        and str(event.get("source_url") or "").strip()
    ]
    if not research_progress:
        findings.append(
            GuardFinding(
                path=smoke_path,
                line=1,
                kind="runtime_research_progress_missing",
                severity="blocker",
                message="runtime smoke emitted no research_progress events",
            )
        )
    if not source_found:
        findings.append(
            GuardFinding(
                path=smoke_path,
                line=1,
                kind="runtime_source_found_missing",
                severity="blocker",
                message="runtime smoke emitted no source-backed research_progress source_found events",
            )
        )

    council_turn_count = sum(1 for event in events if event.get("event") == "council_turn")
    report_chunk_count = sum(1 for event in events if event.get("event") == "report_chunk")
    final_report_count = sum(1 for event in events if event.get("event") == "final_report")
    done_events = [event for event in events if event.get("event") == "done"]
    if council_turn_count <= 0:
        findings.append(
            GuardFinding(
                path=smoke_path,
                line=1,
                kind="runtime_council_turn_missing",
                severity="blocker",
                message="runtime smoke emitted no council_turn events",
            )
        )
    if report_chunk_count != 6:
        findings.append(
            GuardFinding(
                path=smoke_path,
                line=1,
                kind="runtime_report_chunk_mismatch",
                severity="blocker",
                message=f"runtime smoke emitted {report_chunk_count} report_chunk event(s), expected 6",
            )
        )
    if final_report_count != 1:
        findings.append(
            GuardFinding(
                path=smoke_path,
                line=1,
                kind="runtime_final_report_missing",
                severity="blocker",
                message=f"runtime smoke emitted {final_report_count} final_report event(s), expected 1",
            )
        )
    if not done_events or done_events[-1].get("aborted"):
        findings.append(
            GuardFinding(
                path=smoke_path,
                line=1,
                kind="runtime_done_missing_or_aborted",
                severity="blocker",
                message="runtime smoke did not end with a non-aborted done event",
            )
        )

    report_text = ""
    if result.report_path.exists():
        report_text = result.report_path.read_text(encoding="utf-8", errors="replace")
    else:
        findings.append(
            GuardFinding(
                path=report_path,
                line=1,
                kind="runtime_report_file_missing",
                severity="blocker",
                message="runtime smoke did not write a report file",
            )
        )
    for marker in FORBIDDEN_REPORT_MARKERS:
        if marker in report_text:
            findings.append(
                GuardFinding(
                    path=report_path,
                    line=1,
                    kind="runtime_report_placeholder_marker",
                    severity="blocker",
                    message=f"runtime report still contains placeholder marker: {marker}",
                )
            )
    for match in re.finditer(r"Unsupported finding count:\s*(\d+)", report_text, flags=re.IGNORECASE):
        unsupported_count = int(match.group(1))
        if unsupported_count <= 0:
            continue
        findings.append(
            GuardFinding(
                path=report_path,
                line=1,
                kind="runtime_report_unsupported_findings",
                severity="blocker",
                message=f"runtime report still has {unsupported_count} unsupported finding(s)",
            )
        )
    for match in re.finditer(r"trusted[_\s-]*evidence\s*[:=]\s*0\b", report_text, flags=re.IGNORECASE):
        findings.append(
            GuardFinding(
                path=report_path,
                line=1,
                kind="runtime_report_zero_trusted_evidence",
                severity="blocker",
                message="runtime report still has zero trusted evidence",
                excerpt=match.group(0),
            )
        )

    evidence = {
        "topic": RUNTIME_SMOKE_TOPIC,
        "timeout_sec": RUNTIME_SMOKE_TIMEOUT_SEC,
        "elapsed_sec": round(result.elapsed_sec, 3),
        "returncode": result.returncode,
        "event_count": len(events),
        "stage_started": started,
        "stage_completed": completed,
        "research_progress_count": len(research_progress),
        "source_found_count": len(source_found),
        "council_turn_count": council_turn_count,
        "report_chunk_count": report_chunk_count,
        "final_report_count": final_report_count,
        "done_count": len(done_events),
        "events_path": smoke_path,
        "report_path": report_path,
        "forbidden_report_markers": list(FORBIDDEN_REPORT_MARKERS),
    }
    return GuardCheck(
        id="runtime_truth_smoke",
        status="failed" if findings else "passed",
        severity="blocker",
        summary=(
            "actual serve_full runtime completed all stages with source-backed report evidence"
            if not findings
            else f"{len(findings)} runtime truth failure(s)"
        ),
        evidence=evidence,
        findings=tuple(findings),
    )


def _run_runtime_truth_smoke(root: Path) -> RuntimeSmokeResult:
    smoke_dir = root / ".omc/autoresearch/product-guard/runtime-smoke"
    report_path = smoke_dir / "REPORT.md"
    events_path = smoke_dir / "events.jsonl"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    script = (
        "import io, os, sys\n"
        "from pathlib import Path\n"
        "from src.muchanipo.server import serve_full\n"
        "stdout = io.StringIO()\n"
        "report = Path(os.environ['MUCHANIPO_RUNTIME_SMOKE_REPORT'])\n"
        "rc = serve_full(\n"
        "    os.environ.get('MUCHANIPO_RUNTIME_SMOKE_TOPIC', 'runtime truth smoke'),\n"
        "    report_path=report,\n"
        "    stdout=stdout,\n"
        "    depth='shallow',\n"
        ")\n"
        "sys.stdout.write(stdout.getvalue())\n"
        "raise SystemExit(rc)\n"
    )
    env = os.environ.copy()
    env.update(
        {
            "MUCHANIPO_OFFLINE": "1",
            "MUCHANIPO_SOURCE_RESEARCH": "1",
            "MUCHANIPO_RUNTIME_SMOKE_REPORT": str(report_path),
            "MUCHANIPO_RUNTIME_SMOKE_TOPIC": RUNTIME_SMOKE_TOPIC,
            "MUCHANIPO_PREFER_CLI": "0",
            "MUCHANIPO_USE_CLI": "0",
            "MUCHANIPO_REQUIRE_LIVE": "0",
            "MUCHANIPO_ONLINE": "0",
            "MUCHANIPO_AUTORESEARCH_ITERATIONS": "2",
            "MUCHANIPO_HEARTBEAT_INTERVAL_SEC": "999",
            "ANTHROPIC_USE_CLI": "0",
            "GEMINI_USE_CLI": "0",
            "KIMI_USE_CLI": "0",
            "CODEX_USE_CLI": "0",
            "OPENCODE_USE_CLI": "0",
        }
    )
    start = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=RUNTIME_SMOKE_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as exc:
        return RuntimeSmokeResult(
            returncode=124,
            stdout=str(exc.stdout or ""),
            stderr=str(exc.stderr or ""),
            timed_out=True,
            elapsed_sec=time.monotonic() - start,
            report_path=report_path,
            events_path=events_path,
        )
    return RuntimeSmokeResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        timed_out=False,
        elapsed_sec=time.monotonic() - start,
        report_path=report_path,
        events_path=events_path,
    )


def _parse_jsonl_events(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        raw = line.strip()
        if not raw.startswith("{"):
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("event"):
            events.append(payload)
    return events


def _check_secret_scan(root: Path, *, include_untracked: bool) -> GuardCheck:
    findings: list[GuardFinding] = []
    scanned = 0
    accepted_fixture_count = 0
    for path in _scan_paths(root, include_untracked=include_untracked):
        text = _read_scan_text(path)
        if text is None:
            continue
        scanned += 1
        for line_no, line in enumerate(text.splitlines(), start=1):
            for name, pattern in SECRET_PATTERNS:
                if not pattern.search(line):
                    continue
                if _is_revision_hash_false_positive(name, line):
                    continue
                if _is_low_context_aws_secret_hit(name, line):
                    continue
                if _is_test_fixture_secret(path, line):
                    accepted_fixture_count += 1
                    continue
                severity = "blocker"
                findings.append(
                    GuardFinding(
                        path=_display_path(path, root),
                        line=line_no,
                        kind=name,
                        severity=severity,
                        message="possible secret material detected",
                        excerpt=_mask_secret_excerpt(line),
                    )
                )
    blocker_count = sum(1 for finding in findings if finding.severity == "blocker")
    warning_count = len(findings) - blocker_count
    return GuardCheck(
        id="secret_scan",
        status="failed" if blocker_count else "warning" if warning_count else "passed",
        severity="blocker",
        summary=(
            f"{blocker_count} blocker(s), {warning_count} warning(s), "
            f"{accepted_fixture_count} accepted fixture hit(s) across {scanned} scanned file(s)"
        ),
        evidence={
            "scanned_files": scanned,
            "include_untracked": include_untracked,
            "accepted_fixture_secret_hits": accepted_fixture_count,
        },
        findings=tuple(findings),
    )


def _check_dangerous_patterns(root: Path, *, include_untracked: bool) -> GuardCheck:
    findings: list[GuardFinding] = []
    scanned = 0
    for path in _scan_paths(root, include_untracked=include_untracked):
        text = _read_scan_text(path)
        if text is None:
            continue
        scanned += 1
        for line_no, line in enumerate(text.splitlines(), start=1):
            for kind, pattern, message in DANGEROUS_PATTERNS:
                if not pattern.search(line):
                    continue
                if _is_guard_pattern_definition(path, line):
                    continue
                if kind == "eval_exec" and "regex.exec" in line:
                    continue
                if kind == "eval_exec" and path.suffix == ".rs" and "webview.eval(" in line:
                    continue
                severity = "warning"
                findings.append(
                    GuardFinding(
                        path=_display_path(path, root),
                        line=line_no,
                        kind=kind,
                        severity=severity,
                        message=message,
                        excerpt=line.strip()[:240],
                    )
                )
    return GuardCheck(
        id="dangerous_action_review",
        status="warning" if findings else "passed",
        severity="warning",
        summary=f"{len(findings)} risky pattern(s) require review" if findings else f"no risky patterns across {scanned} scanned file(s)",
        evidence={"scanned_files": scanned, "include_untracked": include_untracked},
        findings=tuple(findings[:50]),
    )


def _scan_paths(root: Path, *, include_untracked: bool) -> list[Path]:
    paths: list[Path] = []
    for rel in _git_paths(root, include_untracked=include_untracked):
        path = root / rel
        if _should_scan(path, root):
            paths.append(path)
    if paths:
        return sorted(set(paths))
    return sorted(path for path in root.rglob("*") if _should_scan(path, root))


def _git_paths(root: Path, *, include_untracked: bool) -> list[str]:
    commands = [["git", "ls-files"]]
    if include_untracked:
        commands.append(["git", "ls-files", "--others", "--exclude-standard"])
    out: list[str] = []
    for command in commands:
        try:
            proc = subprocess.run(command, cwd=root, check=False, capture_output=True, text=True, timeout=10)
        except Exception:  # noqa: BLE001
            continue
        if proc.returncode == 0:
            out.extend(line for line in proc.stdout.splitlines() if line.strip())
    return out


def _should_scan(path: Path, root: Path) -> bool:
    if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
        return False
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    if any(part in SKIP_PARTS for part in rel.parts):
        return False
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return False
    except OSError:
        return False
    return True


def _read_scan_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    except OSError:
        return None


def _is_test_fixture_secret(path: Path, line: str) -> bool:
    if "tests" not in path.parts:
        return False
    return any(fragment in line for fragment in ALLOWED_TEST_SECRET_FRAGMENTS)


def _is_revision_hash_false_positive(secret_kind: str, line: str) -> bool:
    """Avoid treating pinned source revisions as AWS secret keys.

    The lockdown AWS secret pattern intentionally catches generic 40-char
    base64-ish strings. That is useful for free-form evidence text, but source
    code inventories legitimately contain 40-hex git commits. Require a commit
    or hash-like context before suppressing the hit.
    """
    if secret_kind != "AWS_SECRET_KEY":
        return False
    if not re.search(r"\b[0-9a-f]{40}\b", line, flags=re.IGNORECASE):
        return False
    context = line.lower()
    return any(
        marker in context
        for marker in (
            "commit",
            "revision",
            "upstream",
            "pinned",
            "sha",
            "source_commit",
            "source_revision",
        )
    )


def _is_low_context_aws_secret_hit(secret_kind: str, line: str) -> bool:
    if secret_kind != "AWS_SECRET_KEY":
        return False
    context = line.lower()
    return not any(
        marker in context
        for marker in (
            "aws",
            "secret",
            "credential",
            "access_key",
            "secret_key",
            "token",
            "password",
            "api_key",
        )
    )


def _is_guard_pattern_definition(path: Path, line: str) -> bool:
    return path.name == "autoresearch_guard.py" and (
        "DANGEROUS_PATTERNS" in line
        or "re.compile" in line
        or "eval_exec" in line
    )


def _mask_secret_excerpt(line: str) -> str:
    masked = line.strip()
    for _, pattern in SECRET_PATTERNS:
        masked = pattern.sub("[REDACTED]", masked)
    return masked[:240]


def _risk_score(checks: Sequence[GuardCheck], *, strict: bool) -> float:
    blocker_count = sum(1 for check in checks for finding in check.findings if finding.severity == "blocker")
    warning_count = sum(1 for check in checks for finding in check.findings if finding.severity == "warning")
    failed_count = sum(1 for check in checks if check.status == "failed")
    score = min(1.0, (blocker_count * 0.5) + (failed_count * 0.25) + (warning_count * (0.05 if strict else 0.01)))
    return round(score, 4)


def _issue_signature(report: dict[str, Any]) -> tuple[Any, ...]:
    issues = []
    for key in ("blockers", "warnings"):
        for item in report.get(key, []):
            issues.append(
                (
                    key,
                    item.get("path"),
                    item.get("line"),
                    item.get("kind"),
                    item.get("severity"),
                )
            )
    check_statuses = tuple((check.get("id"), check.get("status")) for check in report.get("checks", []))
    return tuple(sorted(issues)) + check_statuses


def _summary(*, passed: bool, checks: Sequence[GuardCheck], warnings: list[dict[str, Any]], blockers: list[dict[str, Any]]) -> str:
    if passed:
        return f"product guard passed: {len(checks)} checks, {len(warnings)} warning(s), 0 blocker(s)"
    return f"product guard failed: {len(blockers)} blocker(s), {len(warnings)} warning(s)"


def _write_mission_artifacts(*, mission_path: Path, sandbox_path: Path) -> None:
    mission_path.parent.mkdir(parents=True, exist_ok=True)
    if not mission_path.exists():
        mission_path.write_text(
            "\n".join(
                [
                    "# Muchanipo Product Guard Mission",
                    "",
                    "Use the Autoresearch completion-artifact pattern to keep reviewing Muchanipo itself.",
                    "The guard passes only when runtime reference parity, vendored Autoresearch wiring,",
                    "an actual source-backed serve_full smoke, secret scanning, and dangerous-action",
                    "review have explicit evidence in result.json.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    if not sandbox_path.exists():
        sandbox_path.write_text(
            "\n".join(
                [
                    "# Sandbox",
                    "",
                    "- Local-only, no provider credentials.",
                    "- No push, merge, deploy, deletion, or privilege escalation.",
                    "- Writes are limited to `.omx/specs/autoresearch-product-guard/` and `.omc/autoresearch/product-guard/`.",
                    "- Runtime truth smoke must complete the actual backend pipeline or fail closed.",
                    "",
                ]
            ),
            encoding="utf-8",
        )


def _append_results_tsv(path: Path, *, repo_root: Path, risk_score: float, status: str, description: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("commit\tval_bpb\tmemory_gb\tstatus\tdescription\n", encoding="utf-8")
    commit = _git_head_short(repo_root)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{commit}\t{risk_score:.4f}\t0.0\t{status}\t{description}\n")


def _git_head_short(root: Path) -> str:
    try:
        proc = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, check=False, capture_output=True, text=True, timeout=5)
    except Exception:  # noqa: BLE001
        return "unknown"
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else "unknown"


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
