from __future__ import annotations

import json
from pathlib import Path

from src.research.incident_report import build_incident_report, load_run_events, write_incident_report


def _write_jsonl(path: Path, events: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(event, ensure_ascii=False) for event in events), encoding="utf-8")
    return path


def test_incident_report_observes_offtopic_accepted_source_and_records_hypothesis(tmp_path: Path):
    artifact = _write_jsonl(
        tmp_path / "run.jsonl",
        [
            {
                "event": "run_started",
                "topic": "딸기 농가용 저비용 분자진단 키트 시장성",
                "offline": False,
                "source_research": True,
                "depth": "max",
                "app_run_id": "run-observe-1",
                "run_id": "backend-1",
            },
            {
                "event": "research_progress",
                "status": "searching",
                "query": "strawberry molecular diagnostic plant pathogen detection kit low cost farmer field validation market adoption pricing Korea",
            },
            {
                "event": "research_progress",
                "status": "source_evaluated",
                "source_title": "Adoption of AI-Driven Fraud Detection System in the Nigerian Banking Sector: An Analysis of Cost, Compliance, and Competency",
                "source_url": "http://arxiv.org/abs/2511.00061v1",
                "source_grade": "B",
                "source_kind": "arxiv",
                "accepted": True,
                "facet_ids": ["market"],
                "relevance_score": 0.75,
                "reason": "accepted for facets: market",
            },
            {
                "event": "research_progress",
                "status": "facet_summary",
                "facets": {
                    "market": {"accepted_count": 2, "min_accepted_sources": 3},
                    "regional_adoption": {"accepted_count": 0, "min_accepted_sources": 2},
                },
            },
            {"event": "research_progress", "status": "knowledge_gap", "facet_id": "regional_adoption"},
            {"event": "council_round_done", "round": 10},
            {"event": "final_report", "report_path": "/tmp/REPORT.md"},
            {"event": "done", "report_path": "/tmp/REPORT.md"},
        ],
    )

    report = build_incident_report(load_run_events(artifact), artifact_path=artifact)

    assert report["verdict"] == "FAIL"
    assert report["observations"]["done"] is True
    assert report["observations"]["council_round_done"] == 1
    assert report["anomalies"][0]["type"] == "offtopic_accepted_source"
    assert "Nigerian Banking" in report["anomalies"][0]["source_title"]
    assert report["hypotheses"][0]["status"] == "supported"
    assert "generic market/adoption" in report["hypotheses"][0]["hypothesis"]
    assert any(step["phase"] == "RED" for step in report["approach"])


def test_incident_report_classifies_zero_accepted_mock_smoke_without_blaming_gate(tmp_path: Path):
    artifact = _write_jsonl(
        tmp_path / "mock-smoke.jsonl",
        [
            {"event": "run_started", "topic": "딸기 진단키트 시장성 (smoke)", "offline": True, "source_research": True},
            {
                "event": "research_progress",
                "status": "source_evaluated",
                "source_title": "Mock research evidence",
                "source_kind": "mock",
                "accepted": False,
                "facet_ids": ["market"],
                "reason": "rejected: generated/mock/empty source is not live evidence",
            },
            {
                "event": "research_progress",
                "status": "source_evaluated",
                "source_title": "Mock research evidence",
                "source_kind": "pricing_page",
                "accepted": False,
                "facet_ids": ["scientific", "market"],
                "reason": "rejected: generated/mock/empty source is not live evidence",
            },
            {"event": "research_progress", "status": "knowledge_gap", "facet_id": "scientific"},
            {"event": "research_progress", "status": "knowledge_gap", "facet_id": "market"},
            {"event": "final_report", "report_path": "/tmp/REPORT.md"},
            {"event": "done", "report_path": "/tmp/REPORT.md"},
        ],
    )

    report = build_incident_report(load_run_events(artifact), artifact_path=artifact)

    zero_source = next(item for item in report["anomalies"] if item["type"] == "no_accepted_sources")
    assert zero_source["category"] == "evidence_coverage"
    assert zero_source["classification"] == "expected_strict_rejection_of_mock_sources"
    assert zero_source["blocks_product_pass"] is True
    assert zero_source["rejected_source_count"] == 2
    assert zero_source["mock_rejection_count"] == 2
    gap = next(item for item in report["anomalies"] if item.get("facet_id") == "scientific")
    assert gap["category"] == "evidence_coverage"
    assert gap["classification"] == "facet_under_covered_after_completion"


def test_write_incident_report_renders_anomaly_classification(tmp_path: Path):
    artifact = _write_jsonl(
        tmp_path / "classified.jsonl",
        [
            {"event": "run_started", "topic": "딸기 진단키트 시장성", "offline": True, "source_research": True},
            {"event": "research_progress", "status": "source_evaluated", "accepted": False, "source_title": "Mock research evidence", "source_kind": "mock", "reason": "generated/mock"},
            {"event": "research_progress", "status": "knowledge_gap", "facet_id": "market"},
            {"event": "final_report", "report_path": "/tmp/REPORT.md"},
            {"event": "done", "report_path": "/tmp/REPORT.md"},
        ],
    )

    report = build_incident_report(load_run_events(artifact), artifact_path=artifact)
    out = write_incident_report(report, tmp_path / "classified.md")
    markdown = out.read_text(encoding="utf-8")

    assert "- category: evidence_coverage" in markdown
    assert "- classification: expected_strict_rejection_of_mock_sources" in markdown
    assert "- blocks_product_pass: True" in markdown


def test_incident_report_fails_when_final_report_or_done_is_missing(tmp_path: Path):
    artifact = _write_jsonl(
        tmp_path / "incomplete.jsonl",
        [
            {"event": "run_started", "topic": "딸기 농가용 저비용 분자진단 키트 시장성", "offline": False, "source_research": True},
            {"event": "research_progress", "status": "source_evaluated", "accepted": True, "source_title": "Molecular Approaches for Low-Cost Point-of-Care Pathogen Detection in Agriculture and Forestry"},
            {"event": "research_progress", "status": "facet_summary", "facets": {}},
        ],
    )

    report = build_incident_report(load_run_events(artifact), artifact_path=artifact)

    assert report["verdict"] == "FAIL"
    anomaly_types = {item["type"] for item in report["anomalies"]}
    assert "missing_final_report" in anomaly_types
    assert "missing_done" in anomaly_types


def test_incident_report_normalizes_completed_terminal_run_done_as_completion(tmp_path: Path):
    report_path = tmp_path / "REPORT.md"
    report_path.write_text("# report\n", encoding="utf-8")
    artifact = _write_jsonl(
        tmp_path / "terminal-only.jsonl",
        [
            {"event": "run_started", "topic": "딸기 농가용 저비용 분자진단 키트 시장성", "offline": False, "source_research": True},
            {
                "event": "research_progress",
                "status": "source_evaluated",
                "accepted": True,
                "source_title": "Molecular Approaches for Low-Cost Point-of-Care Pathogen Detection in Agriculture and Forestry",
            },
            {"event": "terminal_run_done", "status": "completed", "report_path": str(report_path)},
        ],
    )

    report = build_incident_report(load_run_events(artifact), artifact_path=artifact)

    assert report["observations"]["final_report"] is True
    assert report["observations"]["done"] is True
    anomaly_types = {item["type"] for item in report["anomalies"]}
    assert "missing_final_report" not in anomaly_types
    assert "missing_done" not in anomaly_types


def test_incident_report_classifies_council_stall_without_weakening_completion(tmp_path: Path):
    artifact = _write_jsonl(
        tmp_path / "council-stall.jsonl",
        [
            {"event": "run_started", "topic": "검증 19", "offline": False, "source_research": True},
            {
                "event": "research_progress",
                "status": "source_evaluated",
                "accepted": True,
                "source_title": "Molecular diagnostic assay paper",
                "facet_ids": ["scientific"],
            },
            {
                "event": "research_progress",
                "status": "facet_summary",
                "facets": {
                    "scientific": {"accepted_count": 5, "min_accepted_sources": 3},
                    "market": {"accepted_count": 3, "min_accepted_sources": 3},
                    "regional_adoption": {"accepted_count": 2, "min_accepted_sources": 2},
                },
            },
        ],
    )

    report = build_incident_report(load_run_events(artifact), artifact_path=artifact)

    anomaly_types = {item["type"] for item in report["anomalies"]}
    council = next(item for item in report["anomalies"] if item["type"] == "council_timeout_or_stall")
    assert council["category"] == "council_runtime"
    assert council["classification"] == "no_council_turns_before_incomplete_run"
    assert council["blocks_product_pass"] is True
    assert "missing_final_report" in anomaly_types
    assert "missing_done" in anomaly_types
    assert report["observations"]["final_report"] is False
    assert report["observations"]["done"] is False


def test_incident_report_classifies_council_provider_call_timeout(tmp_path: Path):
    artifact = _write_jsonl(
        tmp_path / "council-provider-timeout.jsonl",
        [
            {"event": "run_started", "topic": "검증 19e", "offline": False, "source_research": True},
            {
                "event": "research_progress",
                "status": "source_evaluated",
                "accepted": True,
                "source_title": "Molecular diagnostic assay paper",
                "facet_ids": ["scientific"],
            },
            {"event": "stage_started", "stage": "council"},
            {
                "event": "council_provider_call_start",
                "stage": "council_progress",
                "pipeline_stage": "council",
                "provider_route": "opencode",
                "council_stage": "individual",
                "round": 1,
                "layer": "L1_executive_summary",
                "persona": "p1",
            },
            {
                "event": "council_provider_call_timeout",
                "stage": "council_progress",
                "pipeline_stage": "council",
                "provider_route": "opencode",
                "council_stage": "individual",
                "round": 1,
                "layer": "L1_executive_summary",
                "persona": "p1",
                "timeout_sec": 20.0,
                "blocks_product_pass": True,
            },
        ],
    )

    report = build_incident_report(load_run_events(artifact), artifact_path=artifact)

    timeout = next(item for item in report["anomalies"] if item["type"] == "council_provider_call_timeout")
    assert timeout["category"] == "council_runtime"
    assert timeout["classification"] == "provider_call_timeout_during_council"
    assert timeout["blocks_product_pass"] is True
    assert timeout["provider_route"] == "opencode"
    assert timeout["council_stage"] == "individual"
    assert "missing_final_report" in {item["type"] for item in report["anomalies"]}


def test_incident_report_marks_recovered_empty_council_retry_nonblocking(tmp_path: Path):
    artifact = _write_jsonl(
        tmp_path / "recovered-empty-retry.jsonl",
        [
            {"event": "run_started", "topic": "검증 19ar", "offline": False, "source_research": True},
            {
                "event": "research_progress",
                "status": "source_evaluated",
                "accepted": True,
                "source_title": "Strawberry molecular diagnostic assay paper",
                "facet_ids": ["scientific"],
            },
            {
                "event": "research_progress",
                "status": "facet_summary",
                "facets": {"scientific": {"accepted_count": 1, "min_accepted_sources": 1}},
            },
            {
                "event": "council_provider_call_error",
                "stage": "council_progress",
                "pipeline_stage": "council",
                "provider_route": "opencode",
                "council_stage": "individual",
                "round": 1,
                "layer": "L1_executive_summary",
                "persona": "p1",
                "failure_kind": "empty_live_output",
                "retry": "compact_council_prompt",
                "retry_model": "opencode/mimo-v2.5-pro",
                "error_class": "LiveModeViolation",
                "error": "live mode rejected empty or too-short model output at stage 'council'",
                "blocks_product_pass": True,
            },
            {
                "event": "council_provider_call_done",
                "stage": "council_progress",
                "pipeline_stage": "council",
                "provider_route": "opencode",
                "council_stage": "individual",
                "round": 1,
                "layer": "L1_executive_summary",
                "persona": "p1",
                "retry": "compact_council_prompt",
                "retry_model": "opencode/mimo-v2.5-pro",
                "provider": "opencode",
                "model": "opencode/mimo-v2.5-pro",
                "response_chars": 420,
            },
            {"event": "council_turn", "council_stage": "individual", "provider": "opencode"},
            {"event": "council_round_done", "round": 1},
            {"event": "final_report", "report_path": "/tmp/REPORT.md"},
            {"event": "done", "report_path": "/tmp/REPORT.md"},
        ],
    )

    report = build_incident_report(load_run_events(artifact), artifact_path=artifact)

    retry = next(item for item in report["anomalies"] if item["type"] == "council_provider_call_error")
    assert report["verdict"] == "PASS"
    assert retry["classification"] == "recovered_empty_output_retry"
    assert retry["failure_kind"] == "empty_live_output"
    assert retry["blocks_product_pass"] is False
    assert retry["retry_model"] == "opencode/mimo-v2.5-pro"


def test_incident_report_keeps_auth_failure_blocking_even_with_done(tmp_path: Path):
    artifact = _write_jsonl(
        tmp_path / "auth-failure.jsonl",
        [
            {"event": "run_started", "topic": "검증 19ar auth", "offline": False, "source_research": True},
            {
                "event": "research_progress",
                "status": "source_evaluated",
                "accepted": True,
                "source_title": "Strawberry molecular diagnostic assay paper",
                "facet_ids": ["scientific"],
            },
            {
                "event": "council_provider_call_error",
                "stage": "council_progress",
                "pipeline_stage": "council",
                "provider_route": "opencode",
                "council_stage": "individual",
                "round": 1,
                "layer": "L1_executive_summary",
                "persona": "p1",
                "failure_kind": "auth_or_policy_failure",
                "error_class": "RuntimeError",
                "error": "HTTP Error 403: Forbidden",
                "blocks_product_pass": True,
            },
            {"event": "final_report", "report_path": "/tmp/REPORT.md"},
            {"event": "done", "report_path": "/tmp/REPORT.md"},
        ],
    )

    report = build_incident_report(load_run_events(artifact), artifact_path=artifact)

    auth = next(item for item in report["anomalies"] if item["type"] == "council_provider_call_error")
    assert report["verdict"] == "FAIL"
    assert auth["failure_kind"] == "auth_or_policy_failure"
    assert auth["classification"] == "provider_call_error_during_council"
    assert auth["blocks_product_pass"] is True


def test_incident_report_classifies_chairman_timeout_fallback_as_failure(tmp_path: Path):
    artifact = _write_jsonl(
        tmp_path / "chairman-timeout-fallback.jsonl",
        [
            {"event": "run_started", "topic": "검증 19t next", "offline": False, "source_research": True},
            {
                "event": "research_progress",
                "status": "source_evaluated",
                "accepted": True,
                "source_title": "Strawberry molecular diagnostic assay paper",
                "facet_ids": ["scientific"],
            },
            {
                "event": "council_chairman_timeout_fallback",
                "stage": "council_progress",
                "pipeline_stage": "council",
                "round": 1,
                "layer": "L1_market_sizing",
                "council_stage": "chairman",
                "persona": "chairman",
                "provider": "local_timeout_fallback",
                "blocks_product_pass": True,
                "reason": "chairman provider timed out; local synthesis fallback used",
            },
            {"event": "council_turn", "council_stage": "chairman", "provider": "local_timeout_fallback"},
            {"event": "council_round_done", "round": 1},
            {"event": "final_report", "report_path": "/tmp/REPORT.md"},
            {"event": "done", "report_path": "/tmp/REPORT.md"},
        ],
    )

    report = build_incident_report(load_run_events(artifact), artifact_path=artifact)

    fallback = next(item for item in report["anomalies"] if item["type"] == "council_chairman_timeout_fallback")
    assert report["verdict"] == "FAIL"
    assert fallback["category"] == "council_runtime"
    assert fallback["classification"] == "chairman_timeout_local_fallback"
    assert fallback["blocks_product_pass"] is True
    assert fallback["provider_route"] == "local_timeout_fallback"
    assert fallback["council_stage"] == "chairman"


def test_incident_report_classifies_source_search_stall_without_source_evaluations(tmp_path: Path):
    artifact = _write_jsonl(
        tmp_path / "source-search-stall.jsonl",
        [
            {"event": "run_started", "topic": "검증 19c", "offline": False, "source_research": True},
            {"event": "research_progress", "status": "searching", "query": "scientific query", "query_index": 1},
            {"event": "research_progress", "status": "searching", "query": "market query", "query_index": 2},
            {
                "event": "pipeline_heartbeat",
                "stage": "research",
                "detail": "searching",
                "elapsed_sec": 600.0,
            },
        ],
    )

    report = build_incident_report(load_run_events(artifact), artifact_path=artifact)

    source_stall = next(item for item in report["anomalies"] if item["type"] == "source_search_timeout_or_stall")
    assert source_stall["category"] == "source_runtime"
    assert source_stall["classification"] == "search_events_without_source_evaluation_before_incomplete_run"
    assert source_stall["blocks_product_pass"] is True
    assert source_stall["search_query_count"] == 2
    assert source_stall["last_research_elapsed_sec"] == 600.0
    assert report["observations"]["search_query_count"] == 2
    assert report["observations"]["last_research_elapsed_sec"] == 600.0
    assert report["observations"]["source_evaluation_count"] == 0


def test_incident_report_keeps_source_search_stall_blocking_even_with_failed_done(tmp_path: Path):
    artifact = _write_jsonl(
        tmp_path / "source-search-stall-with-failed-done.jsonl",
        [
            {"event": "run_started", "topic": "검증 19ar", "offline": False, "source_research": True},
            {"event": "research_progress", "status": "searching", "query": "scientific query", "query_index": 1},
            {"event": "research_progress", "status": "searching", "query": "market query", "query_index": 2},
            {
                "event": "pipeline_heartbeat",
                "stage": "research",
                "detail": "searching",
                "elapsed_sec": 900.0,
            },
            {
                "event": "done",
                "pipeline": "terminal",
                "aborted": True,
                "status": "failed",
                "error_type": "ResearchBackendTimeout",
            },
        ],
    )

    report = build_incident_report(load_run_events(artifact), artifact_path=artifact)

    source_stall = next(item for item in report["anomalies"] if item["type"] == "source_search_timeout_or_stall")
    assert report["verdict"] == "FAIL"
    assert report["observations"]["done"] is True
    assert source_stall["blocks_product_pass"] is True
    assert source_stall["search_query_count"] == 2
    assert source_stall["last_research_elapsed_sec"] == 900.0


def test_incident_report_distinguishes_completed_zero_eval_research_from_stall(tmp_path: Path):
    artifact = _write_jsonl(
        tmp_path / "completed-zero-eval-research.jsonl",
        [
            {"event": "run_started", "topic": "검증 zero eval", "offline": False, "source_research": True},
            {"event": "research_progress", "status": "searching", "query": "scientific query", "query_index": 1},
            {
                "event": "research_progress",
                "status": "facet_summary",
                "facets": {"scientific": {"accepted_count": 0, "min_accepted_sources": 1}},
                "gap_count": 1,
            },
            {"event": "research_progress", "status": "knowledge_gap", "facet_id": "scientific"},
            {"event": "final_report", "report_path": "/tmp/REPORT.md"},
            {"event": "done", "report_path": "/tmp/REPORT.md"},
        ],
    )

    report = build_incident_report(load_run_events(artifact), artifact_path=artifact)

    anomaly_types = {item["type"] for item in report["anomalies"]}
    zero_eval = next(item for item in report["anomalies"] if item["type"] == "zero_source_evaluations")
    assert "source_search_timeout_or_stall" not in anomaly_types
    assert report["verdict"] == "FAIL"
    assert zero_eval["category"] == "evidence_coverage"
    assert zero_eval["classification"] == "completed_research_without_source_evaluations"
    assert zero_eval["blocks_product_pass"] is True
    assert zero_eval["search_query_count"] == 1
    assert report["observations"]["source_evaluation_count"] == 0


def test_incident_report_classifies_terminal_live_mode_violation(tmp_path: Path):
    artifact = _write_jsonl(
        tmp_path / "terminal-live-mode-violation.jsonl",
        [
            {
                "event": "terminal_run_error",
                "topic": "검증 19w2 opencode-go-api-only",
                "message": "live mode has no live provider candidates for stage 'council': mimo:mock_or_offline, opencode:mock_or_offline",
                "error_type": "LiveModeViolation",
            }
        ],
    )

    report = build_incident_report(load_run_events(artifact), artifact_path=artifact)

    terminal = next(item for item in report["anomalies"] if item["type"] == "terminal_run_error")
    assert report["verdict"] == "FAIL"
    assert report["run"]["topic"] == "검증 19w2 opencode-go-api-only"
    assert terminal["category"] == "runtime"
    assert terminal["classification"] == "LiveModeViolation"
    assert terminal["blocks_product_pass"] is True
    assert terminal["provider_route"] == "mimo, opencode"
    assert "mimo:mock_or_offline" in terminal["error"]
    assert "missing_final_report" in {item["type"] for item in report["anomalies"]}


def test_incident_report_accepts_terminal_failure_done_as_abort_completion(tmp_path: Path):
    artifact = _write_jsonl(
        tmp_path / "terminal-live-mode-violation-done.jsonl",
        [
            {
                "event": "terminal_run_error",
                "topic": "검증 19w2 opencode-go-api-only",
                "message": "live mode has no live provider candidates for stage 'council': mimo:mock_or_offline, opencode:mock_or_offline",
                "error_type": "LiveModeViolation",
            },
            {
                "event": "done",
                "pipeline": "terminal",
                "aborted": True,
                "status": "failed",
                "error_type": "LiveModeViolation",
            },
        ],
    )

    report = build_incident_report(load_run_events(artifact), artifact_path=artifact)

    anomaly_types = {item["type"] for item in report["anomalies"]}
    assert report["verdict"] == "FAIL"
    assert report["observations"]["done"] is True
    assert "missing_done" not in anomaly_types
    assert "missing_final_report" in anomaly_types


def test_write_incident_report_creates_markdown_with_evidence_and_next_steps(tmp_path: Path):
    artifact = _write_jsonl(
        tmp_path / "run.jsonl",
        [
            {"event": "run_started", "topic": "범용 리서치 주제", "offline": False, "source_research": True},
            {"event": "done", "report_path": "/tmp/REPORT.md"},
        ],
    )

    report = build_incident_report(load_run_events(artifact), artifact_path=artifact)
    out = write_incident_report(report, tmp_path / "incident.md")

    markdown = out.read_text(encoding="utf-8")
    assert "# Muchanipo 장애 보고서" in markdown
    assert "## 관측 시스템" in markdown
    assert "## 가설과 접근" in markdown
    assert "## 다음 조치" in markdown
    assert "범용 리서치 주제" in markdown
