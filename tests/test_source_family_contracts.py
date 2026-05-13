from __future__ import annotations

from src.research.source_family_contracts import build_source_family_contract_report


def test_source_family_contract_report_converts_line_research_patterns_to_runtime_gates() -> None:
    report = build_source_family_contract_report(
        progress_statuses=[
            "research_plan_ready",
            "query_route_ledger_built",
            "source_decision_ledger_built",
            "claim_evidence_gate",
            "refutation_pass_started",
            "facet_gap_scheduler_report",
            "research_process_completeness",
        ],
        artifacts={
            "research_query_route_ledger": "{}",
            "source_decision_ledger": "{}",
            "claim_evidence_matrix_summary": "{}",
            "refutation_loop_summary": "{}",
            "research_process_completeness": "{}",
        },
        source_decision_summary={
            "accepted_count": 2,
            "route_facet_statuses": {"canonical_sources": "satisfied"},
        },
        source_decisions=[
            {
                "source_id": "source-a",
                "source_confidence_axis": {
                    "authority_level": "high",
                    "relevance_score": 0.9,
                    "source_grade": "A",
                    "source_role": "core_evidence",
                    "source_kind": "doi",
                },
                "source_freshness": {"status": "fresh", "published_at": "2026-01-01"},
                "source_freshness_stale": False,
                "source_freshness_followup_reason": None,
            },
            {
                "source_id": "source-b",
                "source_confidence_axis": {
                    "authority_level": "medium",
                    "relevance_score": 0.75,
                    "source_grade": "B",
                    "source_role": "comparison",
                    "source_kind": "government",
                },
                "source_freshness": {"status": "stale", "published_at": "2020-01-01"},
                "source_freshness_stale": True,
                "source_freshness_followup_reason": "source_freshness_stale",
            },
        ],
        claim_evidence_summary={"supported_count": 2, "unsupported_count": 0},
        refutation_summary={"readiness": "completed", "task_count": 1},
        adaptive_followup_execution_report={
            "iteration": 2,
            "planned_count": 1,
            "pending_count": 1,
            "pending_followups": [{"route_id": "aqr_1", "pending_reason": "deferred_to_next_bounded_retrieval_pass"}],
        },
        karpathy_autoresearch_runtime={
            "experiments": [
                {
                    "hypothesis": "baseline will establish source gap",
                    "code_test_change": "research_plan_query_mutation",
                    "query_plan_mutation": {"surface": "research_plan.queries"},
                    "metrics_before": {"best_metric": None},
                    "metrics_after": {"metric": 0.4},
                    "decision": "keep",
                    "next_slice": "continue",
                },
                {
                    "hypothesis": "mutation will lower source gap",
                    "code_test_change": "research_plan_query_mutation",
                    "query_plan_mutation": {"surface": "research_plan.queries"},
                    "metrics_before": {"best_metric": 0.4},
                    "metrics_after": {"metric": 0.4},
                    "decision": "discard",
                    "next_slice": "try next",
                },
            ]
        },
        max_plus_benchmark_metrics={"citation_density": 0.8, "quant_claim_count": 2},
    )

    assert report["contract_version"] == "source-family-contracts.v1"
    assert report["contracts"]["research_lifecycle_contract"]["status"] == "pass"
    assert report["contracts"]["source_quality_loop_contract"]["status"] == "pass"
    assert report["contracts"]["adaptive_experiment_loop_contract"]["status"] == "pass"
    assert report["contracts"]["benchmark_fixture_quality_contract"]["status"] == "pass"
    assert report["summary"] == {"pass": 4, "pending": 0, "fail": 0}


def test_source_family_contract_report_marks_gemini_pending_without_max_artifacts() -> None:
    report = build_source_family_contract_report(max_plus_benchmark_metrics={})

    benchmark = report["contracts"]["benchmark_fixture_quality_contract"]
    assert benchmark["status"] == "pending"
    assert benchmark["pending_reason"] == "gemini_cli_model_not_available_and_no_max_fixture_metrics"


def test_source_family_contract_report_fails_partial_max_metrics_without_density_and_quant_counts() -> None:
    report = build_source_family_contract_report(
        max_plus_benchmark_metrics={"source_authority_score": 0.9, "claim_traceability": 0.8}
    )

    benchmark = report["contracts"]["benchmark_fixture_quality_contract"]
    assert benchmark["status"] == "fail"
    assert benchmark["missing"] == ["citation_density", "quant_claim_count"]
