from __future__ import annotations

from src.interview.brief import ResearchBrief
from src.research.karpathy_autoresearch import build_research_quality_audit
from src.research.max_plus_benchmark import benchmark_metrics, build_b1_probe_fixture
from src.research.planner import (
    ResearchPlanner,
    adaptive_followup_query_plan,
    adaptive_followup_execution_report,
    normalize_route_intent,
    query_route_ledger,
    with_source_discovery_queries,
)
from src.research.runner import WebResearchRunner, build_runner
from src.research.source_decision_ledger import build_source_decision_ledger


def _brief(topic: str, *, context: str = "") -> ResearchBrief:
    return ResearchBrief(
        raw_idea=topic,
        research_question=topic,
        purpose="research_report",
        context=context,
        coverage_score=1.0,
        original_topic=topic,
    )


def test_research_plan_emits_one_generic_source_route_per_query() -> None:
    topic = "urban heat island schoolyard shade interventions evidence source-backed research"

    plan = ResearchPlanner().plan(_brief(topic), max_queries=5)

    assert len(plan.query_routes) == len(plan.queries)
    assert [route["query"] for route in plan.query_routes] == plan.queries
    assert all(route["route_id"].startswith("qr_") for route in plan.query_routes)
    assert all(route["route_version"] == "query-route.v1" for route in plan.query_routes)
    assert len({route["route_id"] for route in plan.query_routes}) == len(plan.query_routes)
    assert {route["facet_id"] for route in plan.query_routes} >= {"canonical_sources", "background_scope", "counter_evidence"}
    assert all(route["source_class"] in {"official", "peer_reviewed", "background"} for route in plan.query_routes)
    assert all(route["purpose"] for route in plan.query_routes)
    assert all(route["continue_reason"] for route in plan.query_routes)
    assert "erwinia" not in "\n".join(str(route).casefold() for route in plan.query_routes)
    assert "b-1" not in "\n".join(str(route).casefold() for route in plan.query_routes)


def test_source_routes_use_domain_general_facets_for_two_non_b1_topics() -> None:
    topics = [
        "urban heat island schoolyard shade interventions evidence source-backed research",
        "B2B SaaS pricing adoption willingness to pay evidence",
    ]

    for topic in topics:
        plan = ResearchPlanner().plan(_brief(topic), max_queries=6)
        by_intent = {route["intent"]: route for route in plan.query_routes}
        facet_ids = {route["facet_id"] for route in plan.query_routes}

        assert by_intent["primary_anchor_recall"]["facet_id"] == "canonical_sources"
        assert by_intent["refutation"]["facet_id"] == "counter_evidence"
        assert "background_scope" in facet_ids
        assert "erwinia" not in "\n".join(route["facet_id"] for route in plan.query_routes).casefold()
        assert "b-1" not in "\n".join(route["facet_id"] for route in plan.query_routes).casefold()


def test_query_route_intent_aliases_normalize_and_ledger_is_json_compatible() -> None:
    assert normalize_route_intent("find_primary") == "primary_anchor_recall"
    assert normalize_route_intent("confirm") == "confirmation"
    assert normalize_route_intent("refute") == "refutation"
    assert normalize_route_intent("compare") == "comparison"

    plan = ResearchPlanner().plan(_brief("urban heat island official statistics evidence"), max_queries=3)
    ledger = query_route_ledger(plan)

    assert ledger["route_count"] == len(plan.queries)
    assert ledger["route_version"] == "query-route.v1"
    assert ledger["routes"] == plan.query_routes
    assert all(isinstance(route["acceptance_rules"], list) for route in ledger["routes"])
    assert all(isinstance(route["reject_patterns"], list) for route in ledger["routes"])


def test_adaptive_followup_query_plan_turns_facet_gaps_into_generic_routed_queries() -> None:
    plan = ResearchPlanner().plan(
        _brief("urban heat island schoolyard shade interventions evidence source-backed research"),
        max_queries=5,
    )
    gap_report = {
        "status": "facet_gaps_pending",
        "scheduled_followups": [
            {
                "facet_id": "counter_evidence",
                "route_id": "route-counter",
                "query": "urban heat island shade counter evidence",
                "intent": "refutation",
                "reason_codes": ["route_facet_needs_review", "claim_coverage_gap", "refutation_gap"],
                "priority": 0,
            },
            {
                "facet_id": "background_scope",
                "route_id": "route-background",
                "query": "urban heat island shade scope",
                "intent": "background_mapping",
                "reason_codes": ["route_facet_gap", "claim_coverage_gap"],
                "priority": 1,
            },
        ],
    }

    payload = adaptive_followup_query_plan(plan, gap_report, max_followups=2)

    assert payload["status"] == "adaptive_followups_planned"
    assert payload["planned_count"] == 2
    assert [route["facet_id"] for route in payload["adaptive_query_routes"]] == ["counter_evidence", "background_scope"]
    assert all(route["route_id"].startswith("aqr_") for route in payload["adaptive_query_routes"])
    assert payload["adaptive_query_routes"][0]["intent"] == "refutation"
    assert "counter evidence" in payload["adaptive_query_routes"][0]["query"].casefold()
    assert "accepted source evidence" in payload["adaptive_query_routes"][1]["query"].casefold()
    assert payload["model_role_routing_plan"]["source_discovery"]["model_tier"] == "cheap_or_local"
    assert payload["model_role_routing_plan"]["quality_gate"]["deterministic"] is True
    assert "erwinia" not in str(payload).casefold()
    assert "b-1" not in str(payload).casefold()


def test_adaptive_followup_execution_report_marks_deferred_routes_pending_with_reason() -> None:
    plan = ResearchPlanner().plan(
        _brief("urban heat island schoolyard shade interventions evidence source-backed research"),
        max_queries=5,
    )
    gap_report = {
        "status": "facet_gaps_pending",
        "candidate_count": 2,
        "scheduled_count": 2,
        "scheduled_followups": [
            {
                "facet_id": "counter_evidence",
                "route_id": "route-counter",
                "query": "urban heat island shade counter evidence",
                "intent": "refutation",
                "reason_codes": ["route_facet_needs_review", "refutation_gap"],
                "priority": 0,
            },
            {
                "facet_id": "background_scope",
                "route_id": "route-background",
                "query": "urban heat island shade scope",
                "intent": "background_mapping",
                "reason_codes": ["route_facet_gap"],
                "priority": 1,
            },
        ],
    }
    adaptive_plan = adaptive_followup_query_plan(plan, gap_report, max_followups=2)

    report = adaptive_followup_execution_report(adaptive_plan, facet_gap_report=gap_report)

    assert report["iteration"] == 2
    assert report["status"] == "adaptive_followups_pending"
    assert report["planned_count"] == 2
    assert report["pending_count"] == 2
    assert report["executed_count"] == 0
    assert all(row["pending_reason"] for row in report["pending_followups"])
    assert report["facet_gap_scheduler_report_iteration_2"]["iteration"] == 2
    assert report["facet_gap_scheduler_report_iteration_2"]["pending_count"] == 2
    assert report["facet_gap_scheduler_report_iteration_2"]["gap_count_after_upper_bound"] <= gap_report["candidate_count"]
    assert "b-1" not in str(report).casefold()


def test_research_plan_routes_queries_by_source_class_and_intent() -> None:
    topic = "B2B SaaS pricing adoption willingness to pay evidence"

    plan = ResearchPlanner().plan(_brief(topic, context="distribution channel regulation"), max_queries=6)

    by_query = {route["query"]: route for route in plan.query_routes}
    official_route = next(route for query, route in by_query.items() if "official statistics" in query.casefold())
    counter_route = next(route for route in by_query.values() if route["intent"] == "refutation")

    assert official_route["source_class"] == "official"
    assert official_route["backend"] == "web"
    assert official_route["authority_requirement"] == "high"
    assert official_route["intent"] == "primary_anchor_recall"
    assert official_route["purpose"] == "find canonical official/statistical sources"
    assert "canonical government/statistics/standards pages" in official_route["continue_reason"]

    assert counter_route["intent"] == "refutation"
    assert counter_route["source_class"] == "peer_reviewed"
    assert counter_route["authority_requirement"] == "high"
    assert counter_route["purpose"] == "test counter-evidence and limitations"
    assert "corroborate" in counter_route["continue_reason"]
    assert "must corroborate before high-confidence claim support" in counter_route["acceptance_rules"]


def test_web_research_runner_backend_trace_carries_source_route_metadata() -> None:
    topic = "urban heat island official statistics evidence"
    plan = ResearchPlanner().plan(_brief(topic), max_queries=3)
    runner = WebResearchRunner(
        web_search=lambda query: [],
        vault_search=lambda query: [],
        academic_search=lambda query: [],
        insight_forge_search=None,
        enable_default_insight_forge=False,
        emit_empty_fallback=False,
    )

    runner.run(plan)

    assert runner.last_backend_trace
    assert all("source_class" in item for item in runner.last_backend_trace)
    assert all("route_intent" in item for item in runner.last_backend_trace)
    assert all("route_id" in item for item in runner.last_backend_trace)
    assert all("route_facet_id" in item for item in runner.last_backend_trace)
    assert all("authority_requirement" in item for item in runner.last_backend_trace)


def test_source_decision_ledger_preserves_runner_route_metadata() -> None:
    topic = "B2B SaaS pricing adoption willingness to pay evidence"
    plan = ResearchPlanner().plan(_brief(topic), max_queries=2)

    def web_search(query: str) -> list[dict[str, object]]:
        return [
            {
                "title": f"Government statistics for {query}",
                "url": "https://data.example.gov/item/saas-pricing-adoption",
                "source": "https://data.example.gov/item/saas-pricing-adoption",
                "text": f"Government statistics market adoption pricing willingness survey evidence for {query}",
                "score": 1.0,
                "source_grade": "A",
            }
        ]

    runner = WebResearchRunner(
        web_search=web_search,
        vault_search=lambda query: [],
        academic_search=lambda query: [],
        insight_forge_search=None,
        enable_default_insight_forge=False,
        emit_empty_fallback=False,
    )

    findings = runner.run(plan)
    audit = build_research_quality_audit(findings, plan)
    ledger = build_source_decision_ledger(findings, audit=audit, plan=plan)

    planned_routes_by_id = {route["route_id"]: route for route in plan.query_routes}
    decision_route_ids = {decision.route_id for decision in ledger.decisions}

    assert decision_route_ids
    assert decision_route_ids <= set(planned_routes_by_id)
    assert all(decision.route_id for decision in ledger.decisions)

    for decision in ledger.decisions:
        route = planned_routes_by_id[decision.route_id]
        assert decision.route_facet_id == route["facet_id"]
        assert decision.route_intent == route["intent"]
        assert decision.route_source_class == route["source_class"]
        assert decision.route_authority_requirement == route["authority_requirement"]
        assert decision.route_acceptance_rules == tuple(route["acceptance_rules"])
        row = decision.to_dict()
        assert row["facet_ids"] != [row["route_facet_id"]]
        assert row["route_purpose"] == route["purpose"]
        assert row["route_backend"] == route["backend"]

    summary = ledger.summary()
    assert set(summary["route_facet_counts"]) <= {route["facet_id"] for route in plan.query_routes}
    assert summary["route_intent_counts"]
    event = ledger.quality_gate_events()[0]
    assert event["route_facet_counts"] == summary["route_facet_counts"]


def test_fixture_source_discovery_queries_are_explicit_and_do_not_change_generic_plans() -> None:
    topic = "urban heat island schoolyard shade interventions evidence source-backed research"
    generic_plan = ResearchPlanner().plan(_brief(topic), max_queries=5)
    fixture = build_b1_probe_fixture()

    assert all("10.1016" not in query for query in generic_plan.queries)

    fixture_plan = with_source_discovery_queries(
        generic_plan,
        fixture.source_discovery_queries,
        max_queries=7,
    )
    joined = "\n".join(fixture_plan.queries).casefold()

    assert fixture_plan.queries[0] == generic_plan.queries[0]
    assert "10.1016/j.isci.2023.106557" in joined
    assert "10.1016/j.xpro.2023.102412" in joined
    assert len(fixture_plan.query_routes) == len(fixture_plan.queries)
    doi_routes = [route for route in fixture_plan.query_routes if "10.1016" in route["query"]]
    assert doi_routes
    assert all(route["source_class"] == "peer_reviewed" for route in doi_routes)
    assert all(route["backend"] == "scholar" for route in doi_routes)


def test_web_research_runner_sends_fixture_doi_anchor_queries_to_academic_backend() -> None:
    generic_plan = ResearchPlanner().plan(_brief("generic source-backed research topic"), max_queries=2)
    fixture = build_b1_probe_fixture()
    plan = with_source_discovery_queries(generic_plan, fixture.source_discovery_queries, max_queries=4)
    academic_queries: list[str] = []

    runner = WebResearchRunner(
        web_search=lambda query: [],
        vault_search=lambda query: [],
        academic_search=lambda query: academic_queries.append(query) or [],
        insight_forge_search=None,
        enable_default_insight_forge=False,
        emit_empty_fallback=False,
    )

    runner.run(plan)

    joined = "\n".join(academic_queries).casefold()
    assert "10.1016/j.isci.2023.106557" in joined
    assert "10.1016/j.xpro.2023.102412" in joined


def test_explicit_benchmark_fixture_can_drive_offline_source_backed_runner(monkeypatch) -> None:
    monkeypatch.setenv("MUCHANIPO_MAX_PLUS_BENCHMARK_ID", "b1")
    topic = "B-1 turn-on fluorescent probe detection of Erwinia amylovora fire blight field validation market evidence"
    fixture = build_b1_probe_fixture()
    generic_plan = ResearchPlanner().plan(_brief(topic), max_queries=3)
    plan = with_source_discovery_queries(
        generic_plan,
        fixture.source_discovery_queries,
        max_queries=5,
    )

    runner = build_runner(use_real=False)
    findings = runner.run(plan)
    audit = build_research_quality_audit(findings, plan)
    accepted_ids = {item.source_id for item in audit.source_evaluations if item.accepted}
    metrics = benchmark_metrics(findings, fixture, accepted_source_ids=accepted_ids)

    assert accepted_ids
    assert getattr(runner, "last_backend_trace")
    assert any(item.get("backend") == "fixture_source" for item in runner.last_backend_trace)
    assert metrics["expected_claim_recall"] >= 0.667
    assert metrics["source_authority_score"] >= 0.9
    assert metrics["weak_source_penalty"] == 0.0
    generic_unselected_plan = ResearchPlanner().plan(
        _brief("urban heat island schoolyard shade interventions evidence source-backed research"),
        max_queries=3,
    )
    assert "erwinia" not in "\n".join(generic_unselected_plan.queries).casefold()
    assert "10.1016" not in "\n".join(generic_unselected_plan.queries).casefold()
