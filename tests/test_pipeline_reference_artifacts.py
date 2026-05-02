from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.council.persona_generator import FinalPersona
from src.evidence.artifact import EvidenceRef, Finding
from src.hitl.plannotator_adapter import HITLAdapter
from src.pipeline.idea_to_council import IdeaToCouncilPipeline
from src.intake.idea_dump import IdeaDump
from src.intent.office_hours import OfficeHours
from src.interview.session import InterviewSession


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
    return next(event for event in events if event["stage"] == stage)


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
    assert "Q1_research_question" in event["artifacts"]["interview_question_order"]
    assert "Q4_known" in event["artifacts"]["interview_question_order"]
    assert result.brief.research_question == result.design_doc.pain_root
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
    assert event["artifacts"]["plan_gate_synthetic"] == "true"


def test_step3_research_records_autoresearch_memory_policy(reference_pipeline_run):
    result, events, runner, _ontology, _tmp_path = reference_pipeline_run
    event = _event(events, "research")

    assert event["reference_step"] == 3
    assert event["reference_projects"] == ["Karpathy Autoresearch", "InsightForge", "MemPalace", "학술 자료 검색 API"]
    assert event["artifacts"]["research_query_count"] == str(len(runner.last_plan.queries))
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
    assert event["artifacts"]["evidence_gate_synthetic"] == "true"


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
    assert event["artifacts"]["council_id"] == result.report.id
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
    assert "## Chapter 1:" in result.report_md
    assert "## Chapter 6:" in result.report_md
    assert "## ReACT Executed Sections" in result.report_md
    assert "**도구 관찰:**" in result.report_md
    assert "## ReACT Execution Plan" in result.report_md
    assert int(report_event["artifacts"]["react_executed_section_count"]) >= 1
    assert int(report_event["artifacts"]["react_tool_call_count"]) >= 3
    assert "## GBrain Compiled Truth + Timeline" in result.report_md
    assert "### Evidence Summary" in result.report_md
    assert vault_event["artifacts"]["vault_path"] == str(result.vault_path)
    assert done_event["artifacts"]["learning_count"] == str(len(result.retrospective.learnings))
    first_learning = json.loads((tmp_path / "learnings.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first_learning["project_slug"] == "muchanipo"
