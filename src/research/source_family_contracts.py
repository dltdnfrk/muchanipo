"""Runtime contracts extracted from Deep Research source-family fan-in.

The contracts are deterministic and backend-only. They do not call external
providers; they turn already-recorded runtime artifacts into named pass/pending
gates so source-family findings stay executable instead of prose-only.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence


SOURCE_FAMILY_CONTRACT_VERSION = "source-family-contracts.v1"


def build_source_family_contract_report(
    *,
    progress_statuses: Iterable[str] = (),
    artifacts: Mapping[str, Any] | None = None,
    source_decision_summary: Mapping[str, Any] | None = None,
    source_decisions: Sequence[Mapping[str, Any]] = (),
    claim_evidence_summary: Mapping[str, Any] | None = None,
    refutation_summary: Mapping[str, Any] | None = None,
    adaptive_followup_execution_report: Mapping[str, Any] | None = None,
    karpathy_autoresearch_runtime: Mapping[str, Any] | None = None,
    max_plus_benchmark_metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contracts = {
        "research_lifecycle_contract": _openai_contract_matrix(progress_statuses, artifacts or {}),
        "source_quality_loop_contract": _perplexity_source_loop(
            source_decision_summary or {},
            source_decisions,
            claim_evidence_summary or {},
            refutation_summary or {},
        ),
        "adaptive_experiment_loop_contract": _manus_github_projects(
            adaptive_followup_execution_report or {},
            karpathy_autoresearch_runtime or {},
        ),
        "benchmark_fixture_quality_contract": _gemini_max_line_matrix(max_plus_benchmark_metrics or {}),
    }
    return {
        "contract_version": SOURCE_FAMILY_CONTRACT_VERSION,
        "contracts": contracts,
        "summary": _status_summary(contracts.values()),
    }


def _openai_contract_matrix(progress_statuses: Iterable[str], artifacts: Mapping[str, Any]) -> dict[str, Any]:
    statuses = [str(status) for status in progress_statuses]
    required_statuses = (
        "research_plan_ready",
        "query_route_ledger_built",
        "source_decision_ledger_built",
        "claim_evidence_gate",
        "facet_gap_scheduler_report",
        "research_process_completeness",
    )
    required_artifacts = (
        "research_query_route_ledger",
        "source_decision_ledger",
        "claim_evidence_matrix_summary",
        "refutation_loop_summary",
        "research_process_completeness",
    )
    missing_statuses = [status for status in required_statuses if status not in statuses]
    missing_artifacts = [name for name in required_artifacts if name not in artifacts]
    return _contract(
        "research_lifecycle_contract.plan_to_quality_gate",
        missing_statuses=missing_statuses,
        missing_artifacts=missing_artifacts,
        evidence={
            "pattern": "plan/search/read/refute/quality lifecycle",
            "observed_statuses": [status for status in required_statuses if status in statuses],
            "observed_artifacts": [name for name in required_artifacts if name in artifacts],
        },
    )


def _perplexity_source_loop(
    source_decision_summary: Mapping[str, Any],
    source_decisions: Sequence[Mapping[str, Any]],
    claim_evidence_summary: Mapping[str, Any],
    refutation_summary: Mapping[str, Any],
) -> dict[str, Any]:
    decisions = [dict(decision) for decision in source_decisions if isinstance(decision, Mapping)]
    missing_confidence = [
        str(decision.get("source_id") or idx)
        for idx, decision in enumerate(decisions)
        if not isinstance(decision.get("source_confidence_axis"), Mapping)
    ]
    missing_freshness = [
        str(decision.get("source_id") or idx)
        for idx, decision in enumerate(decisions)
        if not isinstance(decision.get("source_freshness"), Mapping)
    ]
    stale_without_reason = [
        str(decision.get("source_id") or idx)
        for idx, decision in enumerate(decisions)
        if decision.get("source_freshness_stale") is True and not str(decision.get("source_freshness_followup_reason") or "").strip()
    ]
    accepted_count = int(source_decision_summary.get("accepted_count") or 0)
    supported_count = int(claim_evidence_summary.get("supported_count") or 0)
    missing_requirements = []
    if not decisions:
        missing_requirements.append("source_decisions")
    if accepted_count < min(2, supported_count or 2):
        missing_requirements.append("min_corroboration")
    if str(refutation_summary.get("readiness") or "").casefold() not in {"completed", "skipped", "ready", "pass", "passed"}:
        missing_requirements.append("contradiction_disclosure")
    return _contract(
        "source_quality_loop_contract.freshness_confidence_corroboration",
        missing_statuses=missing_requirements,
        missing_artifacts=[*missing_confidence, *missing_freshness, *stale_without_reason],
        evidence={
            "pattern": "source freshness, confidence axis, min corroboration, contradiction disclosure",
            "decision_count": len(decisions),
            "accepted_count": accepted_count,
            "supported_count": supported_count,
            "stale_source_count": sum(1 for decision in decisions if decision.get("source_freshness_stale") is True),
        },
    )


def _manus_github_projects(
    adaptive_followup_execution_report: Mapping[str, Any],
    karpathy_autoresearch_runtime: Mapping[str, Any],
) -> dict[str, Any]:
    experiments = [
        dict(experiment)
        for experiment in (karpathy_autoresearch_runtime.get("experiments") or ())
        if isinstance(experiment, Mapping)
    ]
    missing_experiment_fields = []
    required_fields = (
        "hypothesis",
        "code_test_change",
        "query_plan_mutation",
        "metrics_before",
        "metrics_after",
        "decision",
        "next_slice",
    )
    for idx, experiment in enumerate(experiments):
        missing = [field for field in required_fields if not _present(experiment.get(field))]
        if missing:
            missing_experiment_fields.append(f"experiment_{idx}:{','.join(missing)}")
    pending = adaptive_followup_execution_report.get("pending_followups") or ()
    pending_without_reason = [
        str(row.get("route_id") or idx)
        for idx, row in enumerate(pending)
        if isinstance(row, Mapping) and not str(row.get("pending_reason") or "").strip()
    ]
    missing_requirements = []
    if not experiments:
        missing_requirements.append("keep_discard_loop")
    if not adaptive_followup_execution_report:
        missing_requirements.append("breadth_depth_recursion")
    return _contract(
        "adaptive_experiment_loop_contract.keep_discard_and_gap_recursion",
        missing_statuses=missing_requirements,
        missing_artifacts=[*missing_experiment_fields, *pending_without_reason],
        evidence={
            "pattern": "keep/discard loop, bounded adaptive recursion, progress gateway",
            "experiment_count": len(experiments),
            "adaptive_iteration": adaptive_followup_execution_report.get("iteration"),
            "pending_followup_count": int(adaptive_followup_execution_report.get("pending_count") or 0),
        },
    )


def _gemini_max_line_matrix(max_plus_benchmark_metrics: Mapping[str, Any]) -> dict[str, Any]:
    required_metrics = ("citation_density", "quant_claim_count")
    if not max_plus_benchmark_metrics:
        return {
            "name": "benchmark_fixture_quality_contract.max_fixture_contract",
            "status": "pending",
            "pending_reason": "gemini_cli_model_not_available_and_no_max_fixture_metrics",
            "evidence": {
                "pattern": "claim typing, citation density, quantitative claims, source roles, gap closure",
                "required_metrics": list(required_metrics),
            },
        }
    missing = [key for key in required_metrics if key not in max_plus_benchmark_metrics]
    if missing:
        return {
            "name": "benchmark_fixture_quality_contract.max_fixture_contract",
            "status": "fail",
            "missing": missing,
            "evidence": {
                "pattern": "claim typing, citation density, quantitative claims, source roles, gap closure",
                "metrics": dict(max_plus_benchmark_metrics),
                "required_metrics": list(required_metrics),
            },
        }
    return {
        "name": "benchmark_fixture_quality_contract.max_fixture_contract",
        "status": "pass",
        "evidence": {
            "pattern": "claim typing, citation density, quantitative claims, source roles, gap closure",
            "metrics": dict(max_plus_benchmark_metrics),
        },
    }


def _contract(
    name: str,
    *,
    missing_statuses: Sequence[str],
    missing_artifacts: Sequence[str],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    missing = [item for item in (*missing_statuses, *missing_artifacts) if str(item).strip()]
    return {
        "name": name,
        "status": "pass" if not missing else "fail",
        "missing": missing,
        "evidence": dict(evidence),
    }


def _status_summary(contracts: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    summary = {"pass": 0, "pending": 0, "fail": 0}
    for contract in contracts:
        status = str(contract.get("status") or "fail")
        summary[status if status in summary else "fail"] += 1
    return summary


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def parse_json_artifact(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value
