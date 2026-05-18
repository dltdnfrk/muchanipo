from src.research.readiness import ResearchReadinessInput, decide_research_readiness


def _ready_input(**overrides):
    base = {
        "source_audit_summary": {"passed": True},
        "source_decision_summary": {
            "accepted_count": 2,
            "needs_review_count": 0,
            "blocking_unresolved_canonical_count": 0,
        },
        "claim_evidence_summary": {"passed": True, "supported_ratio": 1.0},
        "evidence_ledger_readiness": "ready",
        "evidence_ledger_metrics": {"claim_support_ratio": 1.0},
        "refutation_loop_readiness": "completed",
        "refutation_loop_summary": {"readiness": "completed"},
        "max_plus_benchmark_decision": "keep",
        "max_plus_benchmark_metrics": {"expected_claim_recall": 1.0},
    }
    base.update(overrides)
    return ResearchReadinessInput(**base)


def test_source_decision_needs_review_prevents_ready_even_when_ledger_ready():
    decision = decide_research_readiness(
        _ready_input(
            source_decision_summary={
                "accepted_count": 2,
                "needs_review_count": 1,
                "blocking_unresolved_canonical_count": 0,
            },
            evidence_ledger_readiness="ready",
        )
    )

    assert decision.readiness == "needs_review"
    assert decision.stop_state == "needs_review_before_council"
    assert "source_decision_summary.needs_review_count=1" in decision.reasons


def test_benchmark_blocked_cannot_be_overridden_by_ledger_ready():
    decision = decide_research_readiness(
        _ready_input(
            evidence_ledger_readiness="ready",
            max_plus_benchmark_decision="blocked",
        )
    )

    assert decision.readiness == "blocked"
    assert decision.stop_state == "blocked_before_council"
    assert "max_plus_benchmark_decision=blocked" in decision.reasons


def test_refutation_blocked_cannot_be_overridden_by_ledger_ready():
    decision = decide_research_readiness(
        _ready_input(
            evidence_ledger_readiness="ready",
            refutation_loop_readiness="blocked",
        )
    )

    assert decision.readiness == "blocked"
    assert decision.stop_state == "blocked_before_council"
    assert "refutation_loop_readiness=blocked" in decision.reasons


def test_ready_requires_all_configured_sub_decisions_ready():
    decision = decide_research_readiness(_ready_input())

    assert decision.readiness == "ready"
    assert decision.stop_state == "before_council"
    assert decision.reasons == ("all_configured_research_quality_gates_ready",)
    assert decision.to_dict()["metrics"]["evidence_ledger_readiness"] == "ready"


def test_expected_claim_traceability_gap_prevents_ready_even_when_ledger_says_ready():
    decision = decide_research_readiness(
        _ready_input(
            evidence_ledger_readiness="ready",
            evidence_ledger_metrics={
                "expected_claim_traceability_score": 0.0,
                "expected_claim_gap_count": 2,
            },
        )
    )

    assert decision.readiness == "needs_review"
    assert decision.stop_state == "needs_review_before_council"
    assert "evidence_ledger.expected_claim_gap_count=2" in decision.reasons
    assert decision.to_dict()["metrics"]["evidence_ledger.expected_claim_gap_count"] == 2


def test_supported_claims_cannot_make_ready_when_no_sources_are_accepted():
    decision = decide_research_readiness(
        _ready_input(
            source_audit_summary={"passed": True, "accepted_source_count": 0},
            source_decision_summary={
                "accepted_count": 0,
                "needs_review_count": 0,
                "blocking_unresolved_canonical_count": 0,
            },
            claim_evidence_summary={
                "passed": True,
                "row_count": 2,
                "supported_count": 2,
                "unsupported_count": 0,
                "supported_ratio": 1.0,
            },
        )
    )

    assert decision.readiness == "needs_review"
    assert decision.stop_state == "needs_review_before_council"
    assert "claim_evidence_summary.supported_count_without_accepted_sources=2" in decision.reasons
