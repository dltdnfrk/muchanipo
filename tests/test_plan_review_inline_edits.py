from src.intake.idea_dump import IdeaDump
from src.evidence.artifact import EvidenceRef, Finding
from src.hitl.plannotator_adapter import HITLResult
from src.intent.office_hours import OfficeHours
from src.interview.session import InterviewSession
from src.pipeline.idea_to_council import (
    IdeaToCouncilPipeline,
    PLAN_REVIEW_EDIT_TARGETS,
    _apply_plan_review_annotations,
    _editable_plan_payload,
)


def test_plan_review_annotations_update_brief_and_planning_projection() -> None:
    raw = "한국 딸기 농가용 진단키트 시장성"
    idea = IdeaDump(raw_text=raw)
    design_doc = OfficeHours().reframe(raw)
    brief = IdeaToCouncilPipeline()._brief_from_interview(
        InterviewSession.from_idea(idea),
        raw,
        design_doc,
    )

    count = _apply_plan_review_annotations(
        brief,
        [
            {
                "type": "edit",
                "plannotator_type": "COMMENT",
                "source": "plannotator-inline-port",
                "blockId": "block-0",
                "lineLabel": "line 1",
                "target": "planning_prd.overview.one_line",
                "replacement": "한국 딸기 농가의 현장 진단키트 구매 가능성 검증",
            },
            {
                "type": "edit",
                "source": "plannotator-inline-port",
                "target": "planning_prd.core_value.resolution",
                "replacement": "제품화 go/no-go와 첫 판매 채널 결정",
            },
            {
                "type": "edit",
                "source": "plannotator-inline-port",
                "target": "feature_hierarchy.0.features.0.name",
                "replacement": "시장성 검증 PRD와 기능명세",
            },
            {
                "type": "edit",
                "source": "plannotator-inline-port",
                "target": "planning_prd.target_scenarios.0.user_group",
                "replacement": "한국 딸기 농가",
            },
            {
                "type": "edit",
                "source": "plannotator-inline-port",
                "target": "user_flow.nodes.output.label",
                "replacement": "검증된 제품화 계획",
            },
        ],
    )

    payload = _editable_plan_payload(brief)

    assert count == 5
    assert brief.research_question == "한국 딸기 농가의 현장 진단키트 구매 가능성 검증"
    assert brief.purpose == "제품화 go/no-go와 첫 판매 채널 결정"
    assert brief.deliverable_type == "시장성 검증 PRD와 기능명세"
    assert brief.planning_prd["overview"]["one_line"] == brief.research_question
    assert brief.planning_prd["core_value"]["resolution"] == brief.purpose
    assert brief.planning_prd["target_scenarios"][0]["user_group"] == "한국 딸기 농가"
    assert brief.feature_hierarchy[0]["features"][0]["name"] == brief.deliverable_type
    assert brief.feature_hierarchy[0]["features"][0]["user_role"] == "한국 딸기 농가"
    assert brief.user_flow["nodes"][-1]["label"] == "검증된 제품화 계획"
    assert brief.planning_review_policy["mode"] == "plannotator_inline_edit"
    assert payload["editable_summary"]["research_question"] == brief.research_question


def test_plan_review_annotations_ignore_unknown_targets() -> None:
    raw = "한국 딸기 농가용 진단키트 시장성"
    idea = IdeaDump(raw_text=raw)
    design_doc = OfficeHours().reframe(raw)
    brief = IdeaToCouncilPipeline()._brief_from_interview(
        InterviewSession.from_idea(idea),
        raw,
        design_doc,
    )
    original_question = brief.research_question

    count = _apply_plan_review_annotations(
        brief,
        [
            {
                "type": "edit",
                "source": "plannotator-inline-port",
                "target": "planning_prd.unknown_field",
                "replacement": "무시되어야 하는 값",
            },
            {
                "type": "edit",
                "source": "plannotator-inline-port",
                "target": "planning_prd.overview.one_line",
                "replacement": "검증된 허용 target",
            },
        ],
    )

    assert "planning_prd.unknown_field" not in PLAN_REVIEW_EDIT_TARGETS
    assert count == 1
    assert brief.research_question == "검증된 허용 target"
    assert brief.research_question != original_question


def test_plan_review_annotations_require_edit_schema_and_trusted_source() -> None:
    raw = "한국 딸기 농가용 진단키트 시장성"
    idea = IdeaDump(raw_text=raw)
    design_doc = OfficeHours().reframe(raw)
    brief = IdeaToCouncilPipeline()._brief_from_interview(
        InterviewSession.from_idea(idea),
        raw,
        design_doc,
    )
    original_question = brief.research_question

    count = _apply_plan_review_annotations(
        brief,
        [
            {
                "type": "comment",
                "source": "plannotator-inline-port",
                "target": "planning_prd.overview.one_line",
                "replacement": "comment는 plan edit가 아니다",
            },
            {
                "type": "edit",
                "source": "unknown-tool",
                "target": "planning_prd.overview.one_line",
                "replacement": "untrusted source는 plan edit가 아니다",
            },
            {
                "type": "edit",
                "source": "plannotator-inline-port",
                "target": "planning_prd.overview.one_line",
                "instruction": "instruction-only annotation은 plan edit가 아니다",
            },
        ],
    )

    assert count == 0
    assert brief.research_question == original_question


class _PlanEditingHITL:
    mode = "jsonline-test"

    def gate(self, gate_name, payload):
        if gate_name == "plan":
            return HITLResult(
                status="approved",
                annotations=[
                    {
                        "type": "edit",
                        "plannotator_type": "COMMENT",
                        "source": "plannotator-inline-port",
                        "blockId": "block-0",
                        "target": "planning_prd.overview.one_line",
                        "replacement": "수정된 PRD 개요",
                    },
                    {
                        "type": "edit",
                        "source": "plannotator-inline-port",
                        "target": "planning_prd.target_scenarios.0.user_group",
                        "replacement": "현장 농가",
                    },
                    {
                        "type": "edit",
                        "source": "plannotator-inline-port",
                        "target": "user_flow.nodes.output.label",
                        "replacement": "수정된 검증 산출물",
                    },
                ],
            )
        return HITLResult(status="approved")

    def gate_brief(self, brief):
        return HITLResult(status="approved")

    def gate_evidence(self, evidence_refs):
        return HITLResult(status="approved")

    def gate_report(self, report_md):
        return HITLResult(status="approved")


class _PlanEditThenBriefChangeHITL(_PlanEditingHITL):
    def gate_brief(self, brief):
        if not hasattr(self, "_brief_requested"):
            self._brief_requested = True
            return HITLResult(status="changes_requested")
        return HITLResult(status="approved")


class _OneFindingRunner:
    last_backend_trace = [{"backend": "academic", "query": "q", "status": "ok", "count": 1}]

    def run(self, plan):
        ref = EvidenceRef(
            id="ref-1",
            source_url="https://doi.org/10.1234/example",
            source_title="Example",
            quote=plan.queries[0],
            source_grade="A",
            provenance={
                "kind": "openalex",
                "doi": "10.1234/example",
                "source": "https://doi.org/10.1234/example",
                "source_text": plan.queries[0],
            },
        )
        return [Finding(claim=plan.queries[0], support=[ref], confidence=0.8)]


def test_pipeline_applies_plan_review_edits_before_targeting(tmp_path) -> None:
    events = []
    pipeline = IdeaToCouncilPipeline(
        hitl_adapter=_PlanEditingHITL(),
        research_runner=_OneFindingRunner(),
        vault_dir=tmp_path / "vault",
        council_log_dir=tmp_path / "council",
        depth="shallow",
        progress_callback=events.append,
    )

    result = pipeline.run("한국 딸기 농가용 진단키트 시장성")

    targeting_event = next(event for event in events if event["stage"] == "targeting")
    assert result.brief.research_question == "수정된 PRD 개요"
    assert result.brief.planning_prd["target_scenarios"][0]["user_group"] == "현장 농가"
    assert result.brief.user_flow["nodes"][-1]["label"] == "수정된 검증 산출물"
    assert result.brief.planning_review_policy["mode"] == "plannotator_inline_edit"
    assert targeting_event["artifacts"]["plan_review_inline_edit_count"] == "3"


def test_pipeline_reapplies_plan_review_edits_after_brief_regeneration(tmp_path) -> None:
    events = []
    pipeline = IdeaToCouncilPipeline(
        hitl_adapter=_PlanEditThenBriefChangeHITL(),
        research_runner=_OneFindingRunner(),
        vault_dir=tmp_path / "vault",
        council_log_dir=tmp_path / "council",
        depth="shallow",
        progress_callback=events.append,
    )

    result = pipeline.run("한국 딸기 농가용 진단키트 시장성")

    targeting_event = next(event for event in events if event["stage"] == "targeting")
    assert result.brief.research_question == "수정된 PRD 개요"
    assert result.brief.planning_prd["target_scenarios"][0]["user_group"] == "현장 농가"
    assert result.brief.user_flow["nodes"][-1]["label"] == "수정된 검증 산출물"
    assert targeting_event["artifacts"]["plan_review_inline_edit_count"] == "3"
    assert targeting_event["artifacts"]["plan_review_inline_reapplied_after_brief_gate"] == "true"
