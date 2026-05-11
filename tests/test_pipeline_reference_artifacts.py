from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.council.persona_generator import FinalPersona
from src.council.parsers import RoundResult
from src.evidence.artifact import EvidenceRef, Finding
from src.hitl.plannotator_adapter import HITLAdapter
from src.pipeline.idea_to_council import (
    IdeaToCouncilPipeline,
    _append_claim_grounding_matrix,
    _claim_with_evidence,
    _fallback_executive_digest,
    _round_digests,
    _source_backed_open_questions,
)
from src.intake.idea_dump import IdeaDump
from src.intent.office_hours import OfficeHours
from src.interview.session import InterviewSession
from src.research.event_contract import validate_research_event_contract


@pytest.fixture
def korean_agtech_topic() -> str:
    return "한국 딸기 농가용 저비용 진단키트 시장성"


def test_pipeline_brief_uses_jsonline_interview_answers():
    raw = "\n".join(
        [
            "[원 요청] 딸기 농가용 저비용 분자진단 키트 시장성",
            "[Q1_research_question] 딸기 농가가 저비용 분자진단 키트를 실제 구매할 시장성과 적정 가격을 알고 싶다",
            "[Q2_purpose] 제품화 go/no-go 결정",
            "[Q3_context] 한국 딸기 농가, 농협 유통, 현장 실증",
            "[Q4_known] 저비용; 현장 사용성; 농가 지불의사",
            "[Q5_deliverable] 6장 시장성 리서치 보고서",
            "[Q6_quality] 실제 출처와 A/B급 근거 중심",
        ]
    )
    idea = IdeaDump(raw_text=raw)
    pipeline = IdeaToCouncilPipeline()
    brief = pipeline._brief_from_interview(
        InterviewSession.from_idea(idea),
        raw,
        OfficeHours().reframe(raw),
    )

    assert brief.research_question.startswith("딸기 농가가 저비용 분자진단 키트")
    assert brief.purpose == "제품화 go/no-go 결정"
    assert brief.context == "한국 딸기 농가, 농협 유통, 현장 실증"
    assert "농가 지불의사" in brief.known_facts
    assert brief.deliverable_type == "6장 시장성 리서치 보고서"
    assert brief.quality_bar == "실제 출처와 A/B급 근거 중심"
    assert brief.planning_prd["overview"]["one_line"].startswith("딸기 농가가 저비용 분자진단 키트")
    assert brief.planning_prd["core_value"]["resolution"] == "제품화 go/no-go 결정"
    assert brief.feature_hierarchy[0]["features"][0]["name"] == "6장 시장성 리서치 보고서"
    assert brief.user_flow["nodes"][0]["id"] == "start"
    assert brief.is_ready
    assert getattr(brief, "interview_trace_source") == "user_interview"
    assert getattr(brief, "synthetic_interview_trace") is False
    assert getattr(brief, "mixed_interview_trace") is False
    assert getattr(brief, "interview_user_answer_count") == 6
    assert getattr(brief, "interview_office_hours_fill_count") == 0
    assert all(item["source"] == "user" for item in getattr(brief, "interview_trace"))
    show_prd = getattr(brief, "show_me_the_prd_artifacts")
    assert show_prd["show_prd_source_commit"] == "7b22b070a685115a8687ea95fb95d398e4daf043"
    assert show_prd["show_prd_runtime_mode"] == "user_interview"
    assert "PRD/01_PRD.md" in show_prd["show_prd_document_outputs"]


def test_ontology_fallback_templates_do_not_inject_product_market_language():
    digest = _fallback_executive_digest([], ["mock-evidence-1"])
    text = "\n".join([digest.key_claim, *digest.body_claims])
    open_questions = "\n".join(_source_backed_open_questions("데이터 사이언스 분야에서의 온톨로지"))
    forbidden = [
        "TAM/SAM/SOM",
        "농가",
        "현장 PCR",
        "제품화 go/no-go",
        "경쟁 제품 가격",
        "시장성 결론",
    ]
    for phrase in forbidden:
        assert phrase not in text
        assert phrase not in open_questions
    assert "데이터 사이언스 분야에서의 온톨로지" in open_questions


def test_mock_evidence_is_labeled_as_not_source_backed():
    claim = _claim_with_evidence(
        "offline claim",
        ["mock-evidence-1"],
        {"mock-evidence-1": "mock"},
    )
    assert "Mock evidence, not source-backed" in claim
    assert "(Evidence: `mock-evidence-1`)" not in claim

    lines: list[str] = []
    _append_claim_grounding_matrix(
        lines,
        [(1, "offline claim", ["mock-evidence-1"])],
        {"mock-evidence-1": "mock"},
    )
    matrix = "\n".join(lines)
    assert "mock-only, not source-backed: `mock-evidence-1`" in matrix


def test_report_digests_do_not_invent_missing_council_rounds():
    evidence = [
        EvidenceRef(
            id="ref-market",
            source_url="https://doi.org/10.1234/market",
            source_title="Plant diagnostics market source",
            quote="plant diagnostics market source",
            source_grade="A",
            provenance={"kind": "openalex"},
        )
    ]
    council = type(
        "CouncilStub",
        (),
        {
            "rounds": [
                RoundResult(
                    layer_id="L1_market_sizing",
                    chapter_title="시장 규모 + 컨텍스트",
                    key_claim="시장 규모는 직접 출처 범위 안에서만 판단한다.",
                    body_claims=["성공 기준은 내부 체크리스트 문장이라 본문에 노출하지 않는다."],
                    evidence_ref_ids=["ref-market"],
                    confidence_score=0.7,
                )
            ]
        },
    )()

    digests = _round_digests(council, evidence)

    assert all("Round " not in digest.key_claim for digest in digests)
    assert not any("성공 기준은" in claim for digest in digests for claim in digest.body_claims)
    assert any(digest.layer_id == "L10_executive_synthesis" for digest in digests)
    assert not any(digest.layer_id.startswith("L7") for digest in digests)


class RecordingReferenceRunner:
    def __init__(self) -> None:
        self.last_plan = None
        self.completed = False

    def run(self, plan):
        self.last_plan = plan
        refs = [
            EvidenceRef(
                id=f"ref-{idx}",
                source_url=f"https://doi.org/10.1234/strawberry-kit-{idx}",
                source_title=f"Strawberry diagnostics source {idx}",
                quote=query,
                source_grade="A",
                provenance={
                    "kind": "openalex",
                    "doi": f"10.1234/strawberry-kit-{idx}",
                    "source": f"https://doi.org/10.1234/strawberry-kit-{idx}",
                    "source_text": query,
                },
            )
            for idx, query in enumerate(plan.queries[:4], start=1)
        ]
        self.completed = True
        return [Finding(claim=ref.quote or "", support=[ref], confidence=0.8) for ref in refs]


@pytest.fixture
def reference_pipeline_run(tmp_path: Path, monkeypatch, korean_agtech_topic: str):
    import src.targeting.builder as targeting_builder
    import src.council.persona_generator as persona_mod

    monkeypatch.setattr(
        targeting_builder,
        "query_institutions",
        lambda domains: (
            ["Seoul National University"],
            [{"source": "openalex", "domains": list(domains)}],
        ),
    )
    monkeypatch.setattr(
        targeting_builder,
        "query_journals",
        lambda domains: (
            ["Precision Agriculture"],
            [{"source": "openalex", "domains": list(domains)}],
        ),
    )
    monkeypatch.setattr(
        targeting_builder,
        "query_seed_papers",
        lambda domains: (
            ["doi:10.1234/strawberry-kit"],
            [{"source": "openalex", "domains": list(domains)}],
        ),
    )

    captured_ontology = {}

    def fake_generate(
        self,
        ontology,
        target_count,
        seed_personas=None,
        max_revisions=3,
        diversity_map=None,
        topic_keywords=None,
        topic=None,
    ):
        captured_ontology.update(dict(ontology))
        finals = [
            FinalPersona(
                persona_id="persona-001",
                name="경북 청도 농업 종사원",
                role=(ontology.get("roles") or ["agtech_farmer"])[0],
                manifest={
                    "grounded_seed": {"source": "Nemotron-Personas-Korea"},
                    "validator": "HACHIMI",
                    "diversity_framework": "MAP-Elites",
                    "debate_protocol": "OASIS / CAMEL-AI",
                    "value_axes": dict(ontology.get("value_axes") or {}),
                },
                revision_notes=["validated_against_ontology"],
            )
        ]
        return finals, {"coverage_after_admit": 0.25, "fallbacks_used": 0}

    monkeypatch.setattr(persona_mod.PersonaGenerator, "generate", fake_generate)

    events = []
    runner = RecordingReferenceRunner()

    def record_event(event):
        events.append({**event, "_research_runner_completed": runner.completed})

    pipeline = IdeaToCouncilPipeline(
        hitl_adapter=HITLAdapter(mode="auto_approve"),
        research_runner=runner,
        vault_dir=tmp_path / "vault" / "insights",
        council_log_dir=tmp_path / "council",
        enable_learning=True,
        learning_log_path=tmp_path / "learnings.jsonl",
        progress_callback=record_event,
    )
    result = pipeline.run(korean_agtech_topic)
    return result, events, runner, captured_ontology, tmp_path


def _event(events: list[dict], stage: str) -> dict:
    return next(event for event in events if event["stage"] == stage and "reference_step" in event)


def _research_progress_event(events: list[dict], status: str) -> dict:
    return next(
        event
        for event in events
        if event.get("event") == "research_progress" and event.get("status") == status
    )


def test_step1_interview_records_show_prd_and_office_hours_outputs(reference_pipeline_run):
    result, events, _runner, _ontology, _tmp_path = reference_pipeline_run
    event = _event(events, "interview")

    assert event["reference_step"] == 1
    assert event["reference_projects"] == ["GPTaku show-me-the-prd", "GStack office-hours"]
    assert event["artifacts"]["brief_id"] == result.brief.id
    assert event["artifacts"]["brief_ready"] == "true"
    assert event["artifacts"]["brief_coverage_score"] == "1.00"
    assert "overview" in event["artifacts"]["planning_prd_sections"]
    assert event["artifacts"]["planning_feature_hierarchy_count"] == "1"
    assert int(event["artifacts"]["planning_user_flow_node_count"]) >= 5
    assert event["artifacts"]["planning_review_gate"] == "brief"
    assert event["artifacts"]["interview_trace_source"] == "office_hours_synthetic"
    assert event["artifacts"]["synthetic_interview_trace"] == "true"
    assert event["artifacts"]["mixed_interview_trace"] == "false"
    assert event["artifacts"]["interview_user_answer_count"] == "0"
    assert int(event["artifacts"]["interview_office_hours_fill_count"]) >= 5
    assert int(event["artifacts"]["interview_reconstructed_question_count"]) >= 5
    assert int(event["artifacts"]["interview_question_count"]) >= 5
    assert event["artifacts"]["interview_effective_answer_count"] == event["artifacts"]["interview_question_count"]
    assert event["artifacts"]["show_prd_source_commit"] == "7b22b070a685115a8687ea95fb95d398e4daf043"
    assert event["artifacts"]["show_prd_license"] == "MIT"
    assert event["artifacts"]["show_prd_runtime_mode"] == "synthetic_office_hours_fill"
    assert "research_batch_before_feature_choice" in event["artifacts"]["show_prd_evidence_markers"]
    assert "PRD/04_PROJECT_SPEC.md" in event["artifacts"]["show_prd_document_outputs"]
    assert "Q1_research_question" in event["artifacts"]["interview_question_order"]
    assert "Q4_known" in event["artifacts"]["interview_question_order"]
    assert result.brief.research_question == result.brief.raw_idea
    assert "입력 텍스트에서" not in result.brief.research_question
    assert "실제 pain은" not in result.brief.research_question
    assert result.brief.research_question != result.design_doc.pain_root
    assert result.brief.purpose == result.design_doc.demand_reality
    assert result.brief.context == result.design_doc.contrary_framing
    assert result.brief.known_facts == result.design_doc.implicit_capabilities
    assert result.brief.constraints == result.design_doc.challenged_premises
    assert result.brief.success_criteria == [result.design_doc.narrowest_wedge, result.design_doc.future_fit]


def test_step2_targeting_records_plan_review_and_academic_outputs(reference_pipeline_run):
    result, events, _runner, _ontology, _tmp_path = reference_pipeline_run
    event = _event(events, "targeting")

    assert event["reference_step"] == 2
    assert event["reference_projects"] == ["GStack plan-review", "학술 자료 검색 API", "GBrain 지식 구조", "Plannotator"]
    assert event["artifacts"]["plan_review_gate"] == ("passed" if result.consensus_plan.gate_passed else "blocked")
    assert event["artifacts"]["plan_review_consensus"] == f"{result.consensus_plan.consensus_score:.2f}"
    assert event["artifacts"]["brief_gate_status"] == "approved"
    assert event["artifacts"]["targeting_domains"] == ",".join(result.targeting_map.domains)
    assert result.targeting_map.target_institutions == ["Seoul National University"]
    assert result.targeting_map.target_journals == ["Precision Agriculture"]
    assert result.targeting_map.seed_papers == ["doi:10.1234/strawberry-kit"]
    assert event["artifacts"]["targeting_academic_sources"] == "openalex"
    assert event["artifacts"]["plan_gate_mode"] == "auto_approve"
    assert event["artifacts"]["plan_gate_synthetic"] == "false"


def test_step3_research_records_autoresearch_memory_policy(reference_pipeline_run):
    result, events, runner, _ontology, _tmp_path = reference_pipeline_run
    event = _event(events, "research")

    assert event["reference_step"] == 3
    assert event["reference_projects"] == ["Karpathy Autoresearch", "InsightForge", "MemPalace", "학술 자료 검색 API"]
    assert event["artifacts"]["research_query_count"] == str(len(runner.last_plan.queries))
    assert "research_query_routes" in event["artifacts"]
    persisted_routes = json.loads(event["artifacts"]["research_query_routes"])
    assert persisted_routes == runner.last_plan.query_routes
    assert all(route["purpose"] for route in persisted_routes)
    assert all(route["continue_reason"] for route in persisted_routes)
    assert runner.last_plan.queries[0] == result.brief.research_question
    assert set(result.targeting_map.search_queries[result.targeting_map.domains[0]]) & set(runner.last_plan.queries)
    assert "counter-evidence query attempted before council" in runner.last_plan.stop_conditions
    assert "prefer academic APIs, official statistics, and local vault before general web snippets" in runner.last_plan.collection_rules
    assert event["artifacts"]["research_runner_kind"] == "RecordingReferenceRunner"
    assert event["artifacts"]["research_backend_kinds"] == "untraced"
    assert event["artifacts"]["research_evidence_kinds"] == "openalex"
    assert event["artifacts"]["research_memory_store"] == "not_executed"
    assert "research_memory_key" not in event["artifacts"]
    assert event["_research_runner_completed"] is True


def test_step3_research_emits_plan_ready_before_searching(reference_pipeline_run):
    _result, events, runner, _ontology, _tmp_path = reference_pipeline_run
    plan_ready_index = next(
        index for index, event in enumerate(events)
        if event.get("event") == "research_progress" and event.get("status") == "research_plan_ready"
    )
    searching_index = next(
        index for index, event in enumerate(events)
        if event.get("event") == "research_progress" and event.get("status") == "searching"
    )
    plan_ready = events[plan_ready_index]

    assert plan_ready_index < searching_index
    assert plan_ready["_research_runner_completed"] is False
    assert plan_ready["query_count"] == len(runner.last_plan.queries)
    assert plan_ready["queries"] == runner.last_plan.queries
    assert plan_ready["query_routes"] == runner.last_plan.query_routes
    assert all(route["facet_id"] for route in plan_ready["query_routes"])
    assert all(route["purpose"] for route in plan_ready["query_routes"])
    assert all(route["source_class"] for route in plan_ready["query_routes"])
    assert all(route["intent"] for route in plan_ready["query_routes"])
    assert all(route["backend"] for route in plan_ready["query_routes"])
    assert all(route["continue_reason"] for route in plan_ready["query_routes"])



def test_step3_research_events_satisfy_backend_contract(reference_pipeline_run):
    _result, events, _runner, _ontology, _tmp_path = reference_pipeline_run
    research_events = [event for event in events if event.get("event") == "research_progress"]

    assert research_events
    for event in research_events:
        decision = validate_research_event_contract(event)
        assert decision.in_scope is True
        assert decision.valid is True, decision.to_dict()
        assert event["research_session_id"]
        assert event["app_run_id"]
        assert event["memory_policy"] == "no_implicit_cross_session_memory"
        assert event["topic_anchor"]


def test_step4_evidence_records_grounding_and_plannotator_result(reference_pipeline_run):
    result, events, _runner, _ontology, _tmp_path = reference_pipeline_run
    event = _event(events, "evidence")

    assert event["reference_step"] == 4
    assert event["reference_projects"] == ["GBrain 현재 결론 + 사건 기록", "출처 기반 연구 원칙", "Plannotator"]
    assert event["artifacts"]["evidence_count"] == "4"
    assert json.loads(event["artifacts"]["evidence_validation_summary"]) == result.evidence_summary
    assert result.evidence_summary["trusted"] == 4
    assert result.evidence_summary["verified_claim_ratio"] == 1.0
    assert event["artifacts"]["evidence_gate_status"] == result.hitl_results["evidence"].status == "approved"
    assert event["artifacts"]["evidence_gate_synthetic"] == "false"


def test_step4_evidence_records_refutation_loop_before_quality_readiness(reference_pipeline_run):
    result, events, _runner, _ontology, _tmp_path = reference_pipeline_run

    summary = json.loads(result.state.artifacts["refutation_loop_summary"])
    report = json.loads(result.state.artifacts["refutation_loop_report"])
    facet_gap_report = json.loads(result.state.artifacts["facet_gap_scheduler_report"])
    adaptive_plan = json.loads(result.state.artifacts["adaptive_followup_query_plan"])
    assert summary["readiness"] in {"completed", "skipped"}
    assert report["summary"] == summary
    assert "tasks" in report
    assert facet_gap_report["status"] in {"complete", "facet_gaps_pending"}
    assert "scheduled_followups" in facet_gap_report
    assert adaptive_plan["status"] in {"adaptive_followups_planned", "no_adaptive_followups"}
    assert "adaptive_query_routes" in adaptive_plan
    assert adaptive_plan["model_role_routing_plan"]["quality_gate"]["deterministic"] is True

    status_order = [event.get("status") for event in events if event.get("event") == "research_progress"]
    claim_index = status_order.index("claim_evidence_gate")
    refute_start_index = status_order.index("refutation_pass_started")
    adaptive_index = status_order.index("adaptive_followup_query_plan")
    facet_gap_index = status_order.index("facet_gap_scheduler_report")
    ledger_index = status_order.index("evidence_ledger_built")
    assert claim_index < refute_start_index < adaptive_index < facet_gap_index < ledger_index


def test_step4_research_progress_exposes_smart_research_ui_contract(reference_pipeline_run):
    result, events, _runner, _ontology, _tmp_path = reference_pipeline_run
    source_summary = json.loads(result.state.artifacts["source_decision_summary"])
    facet_gap_report = json.loads(result.state.artifacts["facet_gap_scheduler_report"])

    ledger_event = _research_progress_event(events, "source_decision_ledger_built")
    assert ledger_event["by_route_facet_id"] == source_summary["by_route_facet_id"]
    assert ledger_event["route_facet_statuses"] == source_summary["route_facet_statuses"]

    claim_event = _research_progress_event(events, "claim_evidence_gate")
    assert claim_event["claim_verification_summary"] == {
        "row_count": claim_event["row_count"],
        "supported_count": claim_event["supported_count"],
        "partial_count": claim_event["partial_count"],
        "unsupported_count": claim_event["unsupported_count"],
        "supported_ratio": claim_event["supported_ratio"],
        "passed": claim_event["passed"],
    }
    assert claim_event["citation_verification_summary"] == {
        "strict_citation_row_count": claim_event["row_count"],
        "supporting_source_count": len({
            source_id
            for row in claim_event["rows"]
            for source_id in row.get("supporting_source_ids", [])
        }),
        "canonical_id_count": len({
            canonical_id
            for row in claim_event["rows"]
            for canonical_id in row.get("canonical_ids", [])
        }),
    }

    facet_gap_event = _research_progress_event(events, "facet_gap_scheduler_report")
    assert facet_gap_event["facet_gap_scheduler_report"] == facet_gap_report
    assert facet_gap_event["by_route_facet_id"] == source_summary["by_route_facet_id"]
    assert facet_gap_event["route_facet_statuses"] == source_summary["route_facet_statuses"]
    assert facet_gap_event["claim_verification_summary"] == claim_event["claim_verification_summary"]
    assert facet_gap_event["citation_verification_summary"] == claim_event["citation_verification_summary"]


def test_step5_council_records_persona_protocol_telemetry(reference_pipeline_run):
    result, events, _runner, ontology, _tmp_path = reference_pipeline_run
    event = _event(events, "council")

    assert event["reference_step"] == 5
    assert event["reference_projects"] == ["MiroFish", "OASIS / CAMEL-AI", "Nemotron-Personas-Korea", "HACHIMI", "MAP-Elites"]
    assert "mirofish" in result.state.artifacts["agents"].split(",")
    assert ontology["roles"]
    assert event["artifacts"]["persona_seed_source"] == "Nemotron-Personas-Korea"
    assert event["artifacts"]["persona_validation_framework"] == "HACHIMI"
    assert event["artifacts"]["persona_diversity_framework"] == "MAP-Elites"
    assert event["artifacts"]["council_protocol"] == "OASIS / CAMEL-AI"
    assert event["artifacts"]["council_protocol_runtime"] == "clean-room local social simulation protocol"
    assert event["artifacts"]["council_protocol_phase_count"] == "3"
    assert event["artifacts"]["council_id"] == result.report.id
    assert event["artifacts"]["mirofish_runtime_valid"] == "true"
    assert event["artifacts"]["mirofish_workflow_phases"] == (
        "graph_building,environment_setup,simulation,report_generation,deep_interaction"
    )
    assert int(event["artifacts"]["mirofish_world_node_count"]) >= 2
    assert int(event["artifacts"]["mirofish_world_edge_count"]) >= 1
    assert int(event["artifacts"]["mirofish_simulation_event_count"]) == len(result.council.turn_transcript)
    assert event["artifacts"]["mirofish_report_agent_ready"] == "true"
    assert event["artifacts"]["mirofish_deep_interaction_ready"] == "true"
    assert int(event["artifacts"]["persona_pool_size"]) >= int(event["artifacts"]["active_persona_count"])
    assert event["artifacts"]["persona_pool_target_size"] == result.state.artifacts["council_persona_pool_size"]
    assert event["artifacts"]["active_persona_count"] == result.state.artifacts["active_council_persona_count"]
    assert int(event["artifacts"]["mirofish_entity_persona_count"]) >= 1
    assert event["artifacts"]["mirofish_entity_persona_count"] == event["artifacts"][
        "mirofish_validated_entity_persona_count"
    ]
    assert int(event["artifacts"]["council_turn_count"]) == len(result.council.turn_transcript)
    assert result.council.rounds


def test_step6_report_vault_agents_done_record_learning_outputs(reference_pipeline_run):
    result, events, _runner, _ontology, tmp_path = reference_pipeline_run
    report_event = _event(events, "report")
    vault_event = _event(events, "vault")
    agents_event = _event(events, "agents")
    done_event = _event(events, "done")

    assert report_event["reference_step"] == 6
    assert vault_event["reference_step"] == 6
    assert agents_event["reference_step"] == 6
    assert done_event["reference_step"] == 6
    assert "ReACT 보고서 작성 패턴" in report_event["reference_projects"]
    assert "Karpathy LLM Wiki Pattern" in report_event["reference_projects"]
    assert "GStack retro" in done_event["reference_projects"]
    assert "GStack learnings_log" in done_event["reference_projects"]
    assert f"Brief ID: `{result.brief.id}`" in result.report_md
    assert "## Evidence Index" in result.report_md
    assert "### Evidence Health" in result.report_md
    assert "- Trusted evidence: 4 / 4" in result.report_md
    assert "URL: https://doi.org/10.1234/strawberry-kit-1" in result.report_md
    assert "Grade: A" in result.report_md
    assert "Provenance: openalex" in result.report_md
    assert "## Claim Grounding Matrix" in result.report_md
    assert "(Evidence: `ref-" in result.report_md
    assert "mock-evidence-" not in result.report_md
    assert "## Strict Claim-Evidence Matrix" in result.report_md
    assert "## Research Audit Appendix" in result.report_md
    audit_payload = json.loads(result.state.artifacts["research_audit_appendix"])
    assert audit_payload["route_ledger"]["route_count"] >= 1
    assert "source_decision_summary" in audit_payload
    assert "claim_evidence_matrix_summary" in audit_payload
    assert "refutation_loop_summary" in audit_payload
    assert "evidence_ledger" in audit_payload
    assert "research_readiness_decision" in audit_payload
    assert "research_process_completeness" in result.state.artifacts
    process_payload = json.loads(result.state.artifacts["research_process_completeness"])
    assert process_payload["readiness"] == "complete"
    assert process_payload["score"] == 1.0
    assert audit_payload["research_process_completeness"]["readiness"] == "complete"
    assert "### Query Route Ledger" in result.report_md
    assert "### Source Decision Summary" in result.report_md
    assert "### Claim / Refutation / Evidence Readiness" in result.report_md
    assert "## Chapter 1:" in result.report_md
    assert "## Chapter 6:" in result.report_md
    assert "## ReACT Executed Sections" in result.report_md
    assert "**도구 관찰:**" in result.report_md
    assert "## ReACT Execution Plan" in result.report_md
    assert int(report_event["artifacts"]["react_executed_section_count"]) >= 1
    assert int(report_event["artifacts"]["react_tool_call_count"]) >= 3
    assert "## GBrain Compiled Truth + Timeline" in result.report_md
    assert "### Evidence Summary" in result.report_md
    assert "### Raw/Wiki Governance" in result.report_md
    assert "### GBrain Runtime Record" in result.report_md
    assert report_event["artifacts"]["wiki_raw_path"].startswith("raw/")
    assert report_event["artifacts"]["wiki_compiled_path"].startswith("wiki/")
    assert report_event["artifacts"]["wiki_dual_path_enforced"] == "true"
    assert report_event["artifacts"]["gbrain_runtime_valid"] == "true"
    assert int(report_event["artifacts"]["gbrain_event_count"]) >= 3
    assert int(report_event["artifacts"]["gbrain_typed_link_count"]) >= 4
    assert report_event["artifacts"]["gbrain_brain_first_route"] == "search,query,get_page,external_after_empty"
    assert report_event["artifacts"]["gbrain_search_mode"] == "keyword_graph_hybrid"
    assert report_event["artifacts"]["gbrain_license"] == "MIT"
    assert vault_event["artifacts"]["vault_path"] == str(result.vault_path)
    assert done_event["artifacts"]["learning_count"] == str(len(result.retrospective.learnings))
    first_learning = json.loads((tmp_path / "learnings.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first_learning["project_slug"] == "muchanipo"
