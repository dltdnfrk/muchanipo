"""End-to-end Idea-to-Council pipeline with offline and live-product modes."""
from __future__ import annotations

import concurrent.futures
import importlib.util
import inspect
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping
from uuid import uuid4

from src.agents.generator import DebateAgentGenerator, DebateAgentSpec
from src.agents.mirofish import build_mirofish_runtime_record, debate_agent_to_council_persona
from src.council.diversity_mapper import DiversityMap
from src.council.parsers import RoundResult
from src.council.persona_generator import Draft, PersonaGenerator
from src.council.persona_sampler import KoreaPersonaSampler
from src.council.round_layers import DEFAULT_LAYERS
from src.council.session import Session as KarpathySession
from src.evidence.artifact import EvidenceRef, Finding
from src.evidence.findings import annotate_findings
from src.evidence.store import EvidenceStore
from src.execution.gateway_v2 import GatewayV2, default_gateway
from src.execution.models import ModelGateway
from src.execution.providers.mock import MockProvider
from src.hitl.plannotator_adapter import HITLAdapter, HITLResult
from src.intake.normalizer import capture_idea
from src.intent.learnings_log import LearningsLog
from src.intent.office_hours import DesignDoc, OfficeHours
from src.intent.plan_review import ConsensusPlan, PlanReview
from src.intent.retro import Retro, Retrospective
from src.interview.brief import ResearchBrief
from src.interview.ontology_state import (
    OntologyExtractionArtifactInput,
    build_ontology_extraction_stage_artifact,
)
from src.interview.product_planning import build_product_planning_projection, default_research_question
from src.interview.session import InterviewSession
from src.interview.show_me_the_prd_port import show_me_the_prd_artifacts
from src.pipeline.persona_artifact import (
    PersonaGenerationArtifactInput,
    assert_persona_artifact_ready_for_llm_council,
    build_persona_generation_stage_artifact,
    persona_payload_from_stage_artifact,
)
from src.research.autoresearch_runtime import runtime_contract_for_profile
from src.research.depth import ResearchDepthProfile, depth_profile, effective_query_limit, normalize_depth
from src.research.karpathy_autoresearch import (
    KarpathyAutoresearchRunner,
    SourceAuditViolation,
    build_research_quality_audit,
    enforce_source_audit_gate,
    iteration_budget_for_profile,
)
from src.research.evidence_ledger import build_evidence_ledger_report
from src.research.event_contract import RESEARCH_BACKEND_CONTRACT_VERSION, assert_research_event_contract
from src.research.max_plus_benchmark import (
    ahp_quality_gate_report,
    benchmark_metrics,
    build_quality_gate_event,
    selected_max_plus_benchmark_fixture,
)
from src.research.planner import (
    ResearchPlanner,
    adaptive_followup_execution_report,
    adaptive_followup_query_plan,
    query_route_ledger,
    with_source_discovery_queries,
)
from src.research.process_completeness import ProcessCompletenessInput, score_process_completeness
from src.research.readiness import ResearchReadinessInput, decide_research_readiness
from src.research.refutation_loop import RefutationLoopReport, run_refutation_loop
from src.research.runner import MockResearchRunner, build_runner
from src.research.session_contract import ResearchContract, scope_event
from src.research.source_family_contracts import build_source_family_contract_report, parse_json_artifact
from src.research.source_decision_ledger import (
    SourceDecisionLedger,
    build_source_decision_ledger,
    facet_gap_scheduler_report,
)
from src.report.chapter_mapper import ChapterMapper, RoundDigest
from src.report.claim_matrix import (
    ClaimEvidenceMatrix,
    build_claim_evidence_matrix,
    enforce_claim_evidence_gate,
)
from src.report.pyramid_formatter import PyramidFormatter
from src.report.research_audit_appendix import (
    build_research_audit_appendix_payload,
    render_research_audit_appendix,
)
from src.report.schema import ResearchReport
from src.runtime.live_mode import (
    LiveModeViolation,
    assert_live_evidence,
    assert_live_hitl,
    assert_live_report,
    live_requested_from_env,
    require_live_mode,
    source_research_requested_from_env,
)
from src.targeting import TargetingMap
from src.targeting.builder import build_targeting_map

from .stages import Stage
from .state import PipelineState
from .reference_contracts import contract_for_stage
from .reference_runtime import build_reference_runtime_artifacts

ProgressCallback = Callable[[Dict[str, Any]], None]


@dataclass
class IdeaToCouncilResult:
    state: PipelineState
    brief: ResearchBrief
    design_doc: DesignDoc
    consensus_plan: ConsensusPlan
    targeting_map: TargetingMap
    evidence_refs: list[EvidenceRef]
    evidence_summary: dict[str, Any]
    report: ResearchReport
    report_md: str
    vault_path: Path
    hitl_results: dict[str, HITLResult]
    progress_events: list[dict[str, Any]]
    agents: list[DebateAgentSpec]
    council: KarpathySession
    reference_runtime_artifacts: dict[str, Any]
    retrospective: Retrospective | None = None


class ResearchQualityOnlyComplete(RuntimeError):
    """Raised after source/evidence quality artifacts are ready before council."""

    def __init__(self, state: PipelineState) -> None:
        super().__init__("research quality-only run completed before council")
        self.state = state


class IdeaToCouncilPipeline:
    def __init__(
        self,
        *,
        hitl_adapter: HITLAdapter | None = None,
        research_runner: Any | None = None,
        model_gateway: ModelGateway | None = None,
        vault_dir: Path | str = Path("vault/insights"),
        council_log_dir: Path | str = Path("src/council/council-logs"),
        enable_learning: bool = False,
        learning_log_path: Path | str | None = None,
        progress_callback: ProgressCallback | None = None,
        require_live: bool | None = None,
        depth: str = "deep",
        research_contract: ResearchContract | None = None,
    ) -> None:
        self.require_live = live_requested_from_env() if require_live is None else require_live
        self.source_research = source_research_requested_from_env()
        self.depth = normalize_depth(depth)
        self.research_contract = research_contract
        self.depth_profile = depth_profile(self.depth)
        self.hitl_adapter = hitl_adapter or HITLAdapter(timeout_seconds=0)
        base_research_runner = research_runner or build_runner(use_real=_use_real_research_from_env())
        self.research_runner = (
            KarpathyAutoresearchRunner(
                base_research_runner,
                iteration_budget=iteration_budget_for_profile(
                    self.depth_profile,
                    source_research=self.source_research,
                ),
            )
            if self.source_research
            else base_research_runner
        )
        self.gateway_v2 = _coerce_gateway_v2(
            model_gateway,
            require_live_default=self.require_live,
        )
        self.vault_dir = Path(vault_dir)
        self.council_log_dir = Path(council_log_dir)
        self.enable_learning = enable_learning
        self.learning_log_path = Path(learning_log_path) if learning_log_path is not None else None
        self.progress_callback = progress_callback
        self.progress_events: list[dict[str, Any]] = []

    def _effective_quality_gate_depth(self, source_audit: Any) -> str:
        """Keep strict quality gates for live/source-backed runs, not offline mocks.

        Offline unit/demo runs still exercise max/superdeep depth budgets with
        MockResearchRunner. Those mock-only findings are intentionally rejected as
        material evidence, but they should not abort budget-contract tests before
        council/report stages. Live/source-research paths keep the requested depth.
        """

        if self.require_live or self.source_research:
            return self.depth
        evaluations = list(getattr(source_audit, "source_evaluations", ()) or ())
        if evaluations and all(
            getattr(item, "source_kind", "") in {"mock", "empty", "generated"}
            or "generated/mock/empty" in str(getattr(item, "reason", ""))
            for item in evaluations
        ):
            return "standard"
        return self.depth

    def run(self, raw_idea: str) -> IdeaToCouncilResult:
        state = PipelineState(run_id=f"run-{uuid4()}")
        if self.research_contract is None:
            self.research_contract = ResearchContract.new(
                topic=_extract_original_topic_anchor(raw_idea),
                app_run_id=state.run_id,
            )
        elif not self.research_contract.app_run_id:
            self.research_contract = ResearchContract(
                research_session_id=self.research_contract.research_session_id,
                topic=self.research_contract.topic,
                app_run_id=state.run_id,
                memory_policy=self.research_contract.memory_policy,
                imported_knowledge_refs=self.research_contract.imported_knowledge_refs,
                benchmark_fixture_id=self.research_contract.benchmark_fixture_id,
            )
        for key, value in self.research_contract.to_artifacts().items():
            state.record_artifact(key, value)
        runtime_contract = runtime_contract_for_profile(self.depth_profile)
        original_topic = _extract_original_topic_anchor(raw_idea)
        state.record_artifact("topic_anchor", original_topic)
        state.record_artifact("research_depth", self.depth)
        state.record_artifact("source_research_enabled", "true" if self.source_research else "false")
        state.record_artifact("research_depth_description", self.depth_profile.description)
        query_limit = effective_query_limit(self.depth_profile, source_research=self.source_research)
        state.record_artifact("research_profile_query_limit", str(self.depth_profile.query_limit))
        state.record_artifact("research_query_limit", str(query_limit))
        council_round_budget = _effective_council_round_budget(self.depth_profile)
        active_persona_count = _effective_active_persona_count(self.depth_profile)
        state.record_artifact("council_round_budget", str(council_round_budget))
        state.record_artifact("council_profile_round_budget", str(self.depth_profile.council_round_budget))
        state.record_artifact("council_persona_pool_size", str(self.depth_profile.persona_pool_size))
        state.record_artifact("active_council_persona_count", str(active_persona_count))
        state.record_artifact("active_council_profile_persona_count", str(self.depth_profile.active_persona_count))
        state.record_artifact("target_runtime_seconds", str(self.depth_profile.target_runtime_seconds))
        state.record_artifact(
            "extended_test_time_compute",
            "enabled" if self.depth_profile.extended_test_time_compute else "disabled",
        )
        state.record_artifact("autoresearch_execution_mode", runtime_contract.execution_mode)
        state.record_artifact(
            "autoresearch_async_background",
            "enabled" if runtime_contract.async_background else "disabled",
        )
        state.record_artifact(
            "autoresearch_hitl_state_gate",
            "enforced" if runtime_contract.hitl_plan_gate_enforced else "prompt_only",
        )
        state.record_artifact(
            "autoresearch_phase_trace",
            json.dumps(runtime_contract.phase_trace_template(), ensure_ascii=False, sort_keys=True),
        )
        state.record_artifact(
            "autoresearch_stream_event_types",
            ",".join(runtime_contract.stream_event_types),
        )
        state.record_artifact(
            "autoresearch_usage_ledger_fields",
            ",".join(runtime_contract.usage_ledger_fields),
        )
        state.record_artifact("autoresearch_stale_after_seconds", str(runtime_contract.stale_after_seconds))
        state.record_artifact("autoresearch_client_timeout_seconds", str(runtime_contract.client_timeout_seconds))
        if runtime_contract.observed_max_usage is not None:
            max_usage = runtime_contract.observed_max_usage.to_dict()
            state.record_artifact(
                "deep_research_max_observed_usage",
                json.dumps(max_usage, ensure_ascii=False, sort_keys=True),
            )
            state.record_artifact("deep_research_max_observed_total_tokens", str(max_usage["total_tokens"]))

        idea = capture_idea(raw_idea)
        self._emit(state, Stage.IDEA_DUMP)
        state.advance(Stage.INTERVIEW)

        interview = InterviewSession.from_idea(idea)
        design_doc = OfficeHours().reframe(idea.raw_text)
        brief = self._brief_from_interview(interview, idea.raw_text, design_doc)
        if not brief.is_ready:
            raise ValueError(
                "research brief is not ready: "
                f"coverage={brief.coverage_score:.2f}, "
                f"missing={','.join(interview.missing_dimensions)}"
            )
        state.record_artifact("brief_id", brief.id)
        state.record_artifact("brief_ready", "true" if brief.is_ready else "false")
        state.record_artifact("brief_coverage_score", f"{brief.coverage_score:.2f}")
        state.record_artifact(
            "planning_prd_sections",
            ",".join((brief.planning_prd or {}).keys()),
        )
        state.record_artifact("planning_feature_hierarchy_count", str(len(brief.feature_hierarchy or [])))
        state.record_artifact(
            "planning_user_flow_node_count",
            str(len((brief.user_flow or {}).get("nodes", []) or [])),
        )
        state.record_artifact(
            "planning_review_gate",
            str((brief.planning_review_policy or {}).get("review_gate", "brief")),
        )
        state.record_artifact(
            "interview_trace_source",
            str(getattr(brief, "interview_trace_source", "unknown")),
        )
        state.record_artifact(
            "synthetic_interview_trace",
            "true" if getattr(brief, "synthetic_interview_trace", False) else "false",
        )
        reconstructed_question_count = len(getattr(brief, "interview_trace", []) or [])
        state.record_artifact("interview_question_count", str(reconstructed_question_count))
        state.record_artifact(
            "interview_effective_answer_count",
            str(getattr(brief, "interview_effective_answer_count", reconstructed_question_count)),
        )
        state.record_artifact(
            "interview_reconstructed_question_count",
            str(reconstructed_question_count),
        )
        state.record_artifact("interview_user_answer_count", str(getattr(brief, "interview_user_answer_count", 0)))
        state.record_artifact(
            "interview_office_hours_fill_count",
            str(getattr(brief, "interview_office_hours_fill_count", 0)),
        )
        state.record_artifact(
            "mixed_interview_trace",
            "true" if getattr(brief, "mixed_interview_trace", False) else "false",
        )
        state.record_artifact(
            "interview_question_order",
            ",".join(item["dimension_id"] for item in getattr(brief, "interview_trace", []) or []),
        )
        for key, value in (getattr(brief, "show_me_the_prd_artifacts", {}) or {}).items():
            state.record_artifact(key, value)
        self._emit(state, Stage.INTERVIEW)

        consensus_plan = PlanReview().autoplan(design_doc)
        state.record_artifact("plan_review_gate", "passed" if consensus_plan.gate_passed else "blocked")
        state.record_artifact("plan_review_consensus", f"{consensus_plan.consensus_score:.2f}")
        if self.require_live and (not consensus_plan.gate_passed or design_doc.aup_risk_score >= 0.7):
            raise LiveModeViolation(f"live mode blocked by plan review gate: {consensus_plan.gate_reason}")
        if not consensus_plan.gate_passed:
            state.warnings.append(f"plan review gate did not pass: {consensus_plan.gate_reason}")
        hitl_results: dict[str, HITLResult] = {}
        hitl_results["plan"] = self.hitl_adapter.gate(
            "plan",
            {
                "design_doc": design_doc.to_brief(),
                "consensus_plan": consensus_plan.to_ontology(),
                "gate_reason": consensus_plan.gate_reason,
                "editable_plan": _editable_plan_payload(brief),
                "plannotator_edit_contract": {
                    "mode": "inline_plan_annotation",
                    "upstream_commit": "6324a0c859f06030b47d71c02b7c6fed09fa0b92",
                    "runtime": "tauri_embedded_port",
                    "editable_targets": [
                        "planning_prd.overview.one_line",
                        "planning_prd.core_value.resolution",
                        "planning_prd.target_scenarios.0.scenario",
                        "planning_prd.target_scenarios.0.user_group",
                        "feature_hierarchy.0.features.0.name",
                        "planning_prd.success_metrics",
                        "user_flow.nodes.start.label",
                        "user_flow.nodes.questionnaire.label",
                        "user_flow.nodes.output.label",
                    ],
                },
            },
        )
        self._record_hitl_gate(state, "plan", hitl_results["plan"])
        self._require_approved_gate("plan", hitl_results["plan"])
        plan_annotations = list(hitl_results["plan"].annotations or [])
        plan_edit_count = _apply_plan_review_annotations(brief, plan_annotations)
        if plan_edit_count:
            state.record_artifact("plan_review_inline_edit_count", str(plan_edit_count))

        hitl_results["brief"] = self.hitl_adapter.gate_brief(brief)
        self._record_hitl_gate(state, "brief", hitl_results["brief"])
        self._require_approved_gate("brief", hitl_results["brief"])
        if hitl_results["brief"].status == "changes_requested":
            state.warnings.append("brief gate requested changes; re-interviewed once")
            interview = InterviewSession.from_idea(idea)
            brief = self._brief_from_interview(interview, idea.raw_text, design_doc)
            if not brief.is_ready:
                raise ValueError(
                    "research brief is not ready after re-interview: "
                    f"coverage={brief.coverage_score:.2f}, "
                    f"missing={','.join(interview.missing_dimensions)}"
                )
            reapplied_plan_edit_count = _apply_plan_review_annotations(brief, plan_annotations)
            if reapplied_plan_edit_count:
                state.record_artifact("plan_review_inline_edit_count", str(reapplied_plan_edit_count))
                state.record_artifact("plan_review_inline_reapplied_after_brief_gate", "true")

        state.advance(Stage.TARGETING)
        targeting_map = build_targeting_map(brief)
        setattr(brief, "targeting_map", targeting_map)
        state.record_artifact("targeting_domains", ",".join(targeting_map.domains))
        state.record_artifact("targeting_academic_sources", ",".join(_targeting_academic_sources(targeting_map)))
        self._emit(state, Stage.TARGETING)

        state.advance(Stage.RESEARCH)
        benchmark_fixture = selected_max_plus_benchmark_fixture()
        plan = ResearchPlanner().plan(brief, max_queries=query_limit)
        if benchmark_fixture is not None and benchmark_fixture.source_discovery_queries:
            plan = with_source_discovery_queries(
                plan,
                benchmark_fixture.source_discovery_queries,
                max_queries=query_limit + len(benchmark_fixture.source_discovery_queries),
            )
            state.record_artifact(
                "fixture_source_discovery_queries",
                json.dumps(list(benchmark_fixture.source_discovery_queries), ensure_ascii=False),
            )
        if self.require_live or self.source_research:
            _assert_research_plan_preserves_topic_anchor(plan, original_topic)
        route_ledger = query_route_ledger(plan)
        state.record_artifact("research_query_count", str(len(plan.queries)))
        state.record_artifact("research_query_routes", json.dumps(plan.query_routes, ensure_ascii=False, sort_keys=True))
        state.record_artifact("research_query_route_ledger", json.dumps(route_ledger, ensure_ascii=False, sort_keys=True))
        state.record_artifact("research_collection_rules", json.dumps(plan.collection_rules, ensure_ascii=False))
        state.record_artifact("research_stop_conditions", json.dumps(plan.stop_conditions, ensure_ascii=False))
        self._emit_research_plan_progress(plan)
        findings = list(self.research_runner.run(plan))
        self._emit_research_source_progress(findings, plan)
        research_runtime = _research_runtime_artifacts(self.research_runner, findings)
        state.record_artifact("research_runner_kind", research_runtime["runner_kind"])
        state.record_artifact("research_backend_kinds", ",".join(research_runtime["backend_kinds"]))
        state.record_artifact("research_evidence_kinds", ",".join(research_runtime["evidence_kinds"]))
        state.record_artifact("research_backend_trace", json.dumps(research_runtime["backend_trace"], ensure_ascii=False, sort_keys=True))
        _record_karpathy_autoresearch_artifacts(state, self.research_runner)
        state.record_artifact("research_memory_store", research_runtime["memory_store"])
        if research_runtime["memory_store"] != "not_executed":
            state.record_artifact("research_memory_key", brief.id)
        else:
            state.warnings.append("Stage 3 MemPalace adapter did not execute for this research run")
        self._emit(state, Stage.RESEARCH)

        state.advance(Stage.EVIDENCE)
        evidence_store = EvidenceStore(require_live=self.require_live)
        evidence_refs = _dedupe_evidence_refs([ev for finding in findings for ev in finding.support])
        for ref in evidence_refs:
            evidence_store.add(ref)
        grounding_reports = annotate_findings(findings)
        evidence_summary = _evidence_validation_summary(evidence_store, grounding_reports)
        source_audit = build_research_quality_audit(findings, plan)
        quality_gate_depth = self._effective_quality_gate_depth(source_audit)
        source_audit_summary = enforce_source_audit_gate(source_audit, depth=quality_gate_depth)
        if quality_gate_depth != self.depth:
            source_audit_summary["runtime_depth"] = self.depth
            source_audit_summary["quality_gate_depth_override"] = quality_gate_depth
        state.record_artifact("source_audit_summary", json.dumps(source_audit_summary, ensure_ascii=False, sort_keys=True))
        self._emit_progress(
            {
                "event": "research_progress",
                "stage": "quality_gate",
                "status": "source_audit_gate",
                "topic_anchor": getattr(plan, "topic_anchor", ""),
                **source_audit_summary,
            }
        )
        source_decision_ledger = self._record_source_decision_ledger(state, findings, source_audit, plan)
        state.record_artifact("evidence_count", str(len(evidence_refs)))
        state.record_artifact("evidence_validation_summary", json.dumps(evidence_summary, ensure_ascii=False, sort_keys=True))
        self._require_live_evidence(evidence_summary, evidence_refs)

        hitl_results["evidence"] = self.hitl_adapter.gate_evidence(evidence_refs)
        self._record_hitl_gate(state, "evidence", hitl_results["evidence"])
        self._require_approved_gate("evidence", hitl_results["evidence"])
        if hitl_results["evidence"].status == "changes_requested":
            state.warnings.append("evidence gate requested changes; augmented research once")
            findings = list(self.research_runner.run(plan))
            evidence_refs = _dedupe_evidence_refs([ev for finding in findings for ev in finding.support])
            evidence_store = EvidenceStore(require_live=self.require_live)
            for ref in evidence_refs:
                evidence_store.add(ref)
            grounding_reports = annotate_findings(findings)
            evidence_summary = _evidence_validation_summary(evidence_store, grounding_reports)
            source_audit = build_research_quality_audit(findings, plan)
            quality_gate_depth = self._effective_quality_gate_depth(source_audit)
            source_audit_summary = enforce_source_audit_gate(source_audit, depth=quality_gate_depth)
            if quality_gate_depth != self.depth:
                source_audit_summary["runtime_depth"] = self.depth
                source_audit_summary["quality_gate_depth_override"] = quality_gate_depth
            state.record_artifact("source_audit_summary", json.dumps(source_audit_summary, ensure_ascii=False, sort_keys=True))
            source_decision_ledger = self._record_source_decision_ledger(state, findings, source_audit, plan)
            state.record_artifact("evidence_count", str(len(evidence_refs)))
            state.record_artifact("evidence_validation_summary", json.dumps(evidence_summary, ensure_ascii=False, sort_keys=True))
        self._emit(state, Stage.EVIDENCE)

        report = ResearchReport(
            brief_id=brief.id,
            title=brief.research_question,
            executive_summary=f"Initial report for: {brief.research_question}",
            findings=findings,
            evidence_refs=evidence_refs,
            open_questions=_source_backed_open_questions(brief.research_question),
            confidence=0.6,
            limitations=_report_limitations(require_live=self.require_live, source_research=self.source_research),
        )
        state.record_artifact("report_id", report.id)
        source_decision_summary = source_decision_ledger.summary()
        accepted_evidence_ids = set(source_decision_ledger.accepted_source_ids)
        claim_evidence_matrix = build_claim_evidence_matrix(
            findings,
            evidence_refs,
            accepted_evidence_ids=accepted_evidence_ids,
            source_decision_ledger=source_decision_ledger,
        )
        claim_evidence_summary = enforce_claim_evidence_gate(claim_evidence_matrix, depth=quality_gate_depth)
        if quality_gate_depth != self.depth:
            claim_evidence_summary["runtime_depth"] = self.depth
            claim_evidence_summary["quality_gate_depth_override"] = quality_gate_depth
        verification_summaries = _claim_and_citation_verification_summaries(claim_evidence_summary)
        state.record_artifact(
            "claim_evidence_matrix_summary",
            json.dumps(claim_evidence_summary, ensure_ascii=False, sort_keys=True),
        )
        self._emit_progress(
            {
                "event": "research_progress",
                "stage": "quality_gate",
                "status": "claim_evidence_gate",
                "topic_anchor": getattr(plan, "topic_anchor", ""),
                **claim_evidence_summary,
                **verification_summaries,
            }
        )
        refutation_loop_report = self._record_refutation_loop(
            state,
            plan=plan,
            claim_evidence_matrix=claim_evidence_matrix,
            source_decision_ledger=source_decision_ledger,
        )
        facet_gap_report = facet_gap_scheduler_report(
            getattr(plan, "query_routes", []) or [],
            source_decision_summary=source_decision_summary,
            claim_coverage=claim_evidence_summary,
            refutation_summary=refutation_loop_report.summary(),
        )
        state.record_artifact(
            "facet_gap_scheduler_report",
            json.dumps(facet_gap_report, ensure_ascii=False, sort_keys=True),
        )
        adaptive_query_plan = adaptive_followup_query_plan(plan, facet_gap_report)
        state.record_artifact(
            "adaptive_followup_query_plan",
            json.dumps(adaptive_query_plan, ensure_ascii=False, sort_keys=True),
        )
        adaptive_execution_report = adaptive_followup_execution_report(
            adaptive_query_plan,
            facet_gap_report=facet_gap_report,
        )
        state.record_artifact(
            "adaptive_followup_execution_report",
            json.dumps(adaptive_execution_report, ensure_ascii=False, sort_keys=True),
        )
        state.record_artifact(
            "facet_gap_scheduler_report_iteration_2",
            json.dumps(
                adaptive_execution_report["facet_gap_scheduler_report_iteration_2"],
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        self._emit_progress(
            {
                "event": "research_progress",
                "stage": "quality_gate",
                "topic_anchor": getattr(plan, "topic_anchor", ""),
                **adaptive_query_plan,
                "status": "adaptive_followup_query_plan",
                "adaptive_followup_status": adaptive_query_plan["status"],
            }
        )
        self._emit_progress(
            {
                "event": "research_progress",
                "stage": "quality_gate",
                "status": "adaptive_followup_execution_report",
                "topic_anchor": getattr(plan, "topic_anchor", ""),
                **adaptive_execution_report,
            }
        )
        self._emit_progress(
            {
                "event": "research_progress",
                "stage": "quality_gate",
                "status": "facet_gap_scheduler_report_iteration_2",
                "topic_anchor": getattr(plan, "topic_anchor", ""),
                "facet_gap_scheduler_report_iteration_2": adaptive_execution_report[
                    "facet_gap_scheduler_report_iteration_2"
                ],
            }
        )
        self._emit_progress(
            {
                "event": "research_progress",
                "stage": "quality_gate",
                "topic_anchor": getattr(plan, "topic_anchor", ""),
                **facet_gap_report,
                "status": "facet_gap_scheduler_report",
                "facet_gap_scheduler_status": facet_gap_report["status"],
                "facet_gap_scheduler_report": facet_gap_report,
                "by_route_facet_id": source_decision_summary.get("by_route_facet_id", {}),
                "route_facet_statuses": source_decision_summary.get("route_facet_statuses", {}),
                **verification_summaries,
            }
        )
        ledger_expected_claims = benchmark_fixture.expected_claims if benchmark_fixture is not None else ()
        rejected_evidence_reasons = source_decision_ledger.rejected_source_reasons
        evidence_ledger_report = build_evidence_ledger_report(
            findings,
            expected_claims=ledger_expected_claims,
            accepted_source_ids=accepted_evidence_ids,
            rejected_source_reasons=rejected_evidence_reasons,
            source_decision_ledger=source_decision_ledger,
        )
        state.record_artifact(
            "evidence_ledger_report",
            json.dumps(evidence_ledger_report.to_dict(), ensure_ascii=False, sort_keys=True),
        )
        state.record_artifact(
            "evidence_ledger_metrics",
            json.dumps(dict(evidence_ledger_report.metrics), ensure_ascii=False, sort_keys=True),
        )
        for ledger_event in evidence_ledger_report.quality_gate_events:
            self._emit_progress(
                {
                    **ledger_event,
                    "topic_anchor": getattr(plan, "topic_anchor", ""),
                    "readiness": evidence_ledger_report.readiness,
                }
            )
        benchmark_score_vector: dict[str, float] | None = None
        benchmark_decision: str | None = None
        if benchmark_fixture is not None:
            benchmark_score_vector = benchmark_metrics(
                findings,
                fixture=benchmark_fixture,
                accepted_source_ids=accepted_evidence_ids,
            )
            ahp_report = ahp_quality_gate_report(
                findings,
                fixture=benchmark_fixture,
                accepted_source_ids=accepted_evidence_ids,
                benchmark_score_vector=benchmark_score_vector,
                progress_events=[
                    *self.progress_events,
                    {
                        "stage": "quality_gate",
                        "status": "max_plus_benchmark_scored",
                        "research_backend_contract_version": RESEARCH_BACKEND_CONTRACT_VERSION,
                    },
                ],
            )
            benchmark_decision = _max_plus_benchmark_decision(benchmark_score_vector)
            state.record_artifact("max_plus_benchmark_id", benchmark_fixture.benchmark_id)
            state.record_artifact(
                "max_plus_benchmark_metrics",
                json.dumps(benchmark_score_vector, ensure_ascii=False, sort_keys=True),
            )
            state.record_artifact(
                "max_plus_ahp_quality_gate",
                json.dumps(ahp_report, ensure_ascii=False, sort_keys=True),
            )
            state.record_artifact("max_plus_ahp_score", str(ahp_report["score"]))
            state.record_artifact("max_plus_benchmark_decision", benchmark_decision)
            benchmark_event = build_quality_gate_event(
                benchmark_id=benchmark_fixture.benchmark_id,
                metrics=benchmark_score_vector,
                decision=benchmark_decision,
                hypothesis="score live findings against an explicitly selected local Deep Research Max fixture without re-calling paid Max",
                ahp_report=ahp_report,
            )
            benchmark_event["topic_anchor"] = getattr(plan, "topic_anchor", "")
            self._emit_progress(benchmark_event)
        else:
            state.record_artifact("max_plus_benchmark_id", "")
        readiness_decision = decide_research_readiness(
            ResearchReadinessInput(
                source_audit_summary=source_audit_summary,
                source_decision_summary=source_decision_ledger.summary(),
                claim_evidence_summary=claim_evidence_summary,
                evidence_ledger_readiness=evidence_ledger_report.readiness,
                evidence_ledger_metrics=evidence_ledger_report.metrics,
                refutation_loop_readiness=refutation_loop_report.readiness,
                refutation_loop_summary=refutation_loop_report.summary(),
                max_plus_benchmark_decision=benchmark_decision,
                max_plus_benchmark_metrics=benchmark_score_vector,
            )
        )
        state.record_artifact(
            "research_readiness_decision",
            json.dumps(readiness_decision.to_dict(), ensure_ascii=False, sort_keys=True),
        )
        process_completeness = score_process_completeness(
            ProcessCompletenessInput(
                query_route_ledger=route_ledger,
                source_decision_summary=source_decision_ledger.summary(),
                claim_evidence_summary=claim_evidence_summary,
                refutation_loop_summary=refutation_loop_report.summary(),
                evidence_ledger_readiness=evidence_ledger_report.readiness,
                evidence_ledger_metrics=evidence_ledger_report.metrics,
                research_readiness_decision=readiness_decision.to_dict(),
                progress_events=tuple(self.progress_events),
            )
        )
        process_completeness_payload = process_completeness.to_dict()
        state.record_artifact(
            "research_process_completeness",
            json.dumps(process_completeness_payload, ensure_ascii=False, sort_keys=True),
        )
        self._emit_progress(
            {
                "event": "research_progress",
                "stage": "quality_gate",
                "status": "research_process_completeness",
                "topic_anchor": getattr(plan, "topic_anchor", ""),
                **process_completeness_payload,
            }
        )
        source_family_contract_report = build_source_family_contract_report(
            progress_statuses=[str(event.get("status") or "") for event in self.progress_events],
            artifacts=state.artifacts,
            source_decision_summary=source_decision_ledger.summary(),
            source_decisions=source_decision_ledger.to_dict()["decisions"],
            claim_evidence_summary=claim_evidence_summary,
            refutation_summary=refutation_loop_report.summary(),
            adaptive_followup_execution_report=adaptive_execution_report,
            karpathy_autoresearch_runtime=parse_json_artifact(
                state.artifacts.get("karpathy_autoresearch_runtime", {})
            ),
            max_plus_benchmark_metrics=benchmark_score_vector or {},
        )
        state.record_artifact(
            "source_family_contract_report",
            json.dumps(source_family_contract_report, ensure_ascii=False, sort_keys=True),
        )
        self._emit_progress(
            {
                "event": "research_progress",
                "stage": "quality_gate",
                "status": "source_family_contract_report",
                "topic_anchor": getattr(plan, "topic_anchor", ""),
                **source_family_contract_report,
            }
        )
        research_audit_appendix = build_research_audit_appendix_payload(
            query_route_ledger=query_route_ledger(plan),
            source_decision_summary=source_decision_ledger.summary(),
            claim_evidence_summary=claim_evidence_summary,
            refutation_loop_summary=refutation_loop_report.summary(),
            evidence_ledger_metrics=evidence_ledger_report.metrics,
            evidence_ledger_readiness=evidence_ledger_report.readiness,
            research_readiness_decision=readiness_decision.to_dict(),
            research_process_completeness=process_completeness_payload,
        )
        state.record_artifact(
            "research_audit_appendix",
            json.dumps(research_audit_appendix, ensure_ascii=False, sort_keys=True),
        )
        if _research_quality_only_requested():
            research_quality_stop = readiness_decision.stop_state
            research_quality_readiness = readiness_decision.readiness
            state.record_artifact("research_quality_only_stop", research_quality_stop)
            state.record_artifact("research_quality_readiness", research_quality_readiness)
            state.record_artifact("evidence_ledger_readiness", evidence_ledger_report.readiness)
            state.record_artifact("refutation_loop_readiness", refutation_loop_report.readiness)
            state.record_artifact(
                "research_readiness_decision",
                json.dumps(readiness_decision.to_dict(), ensure_ascii=False, sort_keys=True),
            )
            if readiness_decision.readiness != "ready":
                state.record_artifact("research_quality_review_reason", "; ".join(readiness_decision.reasons))
            state.record_artifact(
                "evidence_ledger_readiness_metrics",
                json.dumps(dict(evidence_ledger_report.metrics), ensure_ascii=False, sort_keys=True),
            )
            ready_event = {
                "event": readiness_decision.terminal_event_name(),
                "stage": "quality_gate",
                "status": research_quality_stop if research_quality_stop != "before_council" else "ready_before_council",
                "topic_anchor": getattr(plan, "topic_anchor", ""),
                "research_quality_readiness": research_quality_readiness,
                "research_readiness_decision": readiness_decision.to_dict(),
                "research_readiness_reasons": list(readiness_decision.reasons),
                "evidence_ledger_readiness": evidence_ledger_report.readiness,
                "evidence_ledger_metrics": dict(evidence_ledger_report.metrics),
                "research_process_completeness": process_completeness_payload,
                "refutation_loop_readiness": refutation_loop_report.readiness,
                "refutation_loop_summary": refutation_loop_report.summary(),
                "source_audit_summary": source_audit_summary,
                "source_decision_summary": source_decision_ledger.summary(),
                "claim_evidence_matrix_summary": claim_evidence_summary,
            }
            if benchmark_score_vector is not None and benchmark_decision is not None:
                ready_event["max_plus_benchmark_decision"] = benchmark_decision
                ready_event["max_plus_benchmark_metrics"] = benchmark_score_vector
            self._emit_progress(ready_event)
            raise ResearchQualityOnlyComplete(state)

        agents = DebateAgentGenerator().from_report(report)
        ontology_artifact = _build_pipeline_ontology_extraction_artifact(
            topic=original_topic,
            brief=brief,
            report=report,
            evidence_refs=evidence_refs,
        )
        state.record_artifact(
            "ontology_extraction_artifact",
            json.dumps(ontology_artifact, ensure_ascii=False, sort_keys=True),
        )
        ontology_payload = _ontology_payload_from_stage_artifact(ontology_artifact)
        state.record_artifact("ontology_extraction_consumable", "true" if ontology_payload.get("consumable") else "false")
        state.record_artifact("ontology_entity_count", str(len(ontology_payload.get("entities") or [])))
        state.record_artifact("ontology_relation_count", str(len(ontology_payload.get("relations") or [])))
        self._emit_progress(
            {
                "event": "stage_completed" if ontology_payload.get("consumable") else "stage_blocked",
                "stage": "ontology_extraction",
                "status": ontology_artifact["status"],
                "artifact_ref": "state:ontology_extraction_artifact",
                "ontology_entity_count": len(ontology_payload.get("entities") or []),
                "ontology_relation_count": len(ontology_payload.get("relations") or []),
                "needs_review_entity_count": len(ontology_payload.get("needs_review_entity_labels") or []),
            }
        )
        state.record_artifact("agents", ",".join(agent.name for agent in agents))
        personas, persona_telemetry = _generate_council_personas(
            report=report,
            agents=agents,
            gateway=self.gateway_v2,
            consensus_plan=consensus_plan,
            targeting_map=targeting_map,
            depth_profile=self.depth_profile,
            require_live=self.require_live,
            progress_callback=self.progress_callback,
            ontology_artifact=ontology_payload,
        )
        persona_stage_artifact = build_persona_generation_stage_artifact(
            PersonaGenerationArtifactInput(
                ontology_artifact=ontology_payload,
                personas=personas,
                telemetry=persona_telemetry,
                min_council_size=max(1, min(len(personas), active_persona_count)),
                mode="live" if self.require_live else "offline",
                metadata={
                    "depth_profile": str(self.depth_profile.name),
                    "target_persona_pool_size": self.depth_profile.persona_pool_size,
                    "active_persona_count": active_persona_count,
                },
            )
        )
        persona_payload = persona_payload_from_stage_artifact(persona_stage_artifact)
        state.record_artifact(
            "persona_generation_artifact",
            json.dumps(persona_stage_artifact, ensure_ascii=False, sort_keys=True),
        )
        state.record_artifact(
            "persona_generation_llm_council_ready",
            "true" if persona_payload["downstream_consumability"].get("llm_council_ready") else "false",
        )
        self._emit_progress(
            {
                "event": "stage_completed"
                if persona_payload["downstream_consumability"].get("llm_council_ready")
                else "stage_blocked",
                "stage": "persona_generation",
                "status": persona_stage_artifact["status"],
                "artifact_ref": "state:persona_generation_artifact",
                "admitted_persona_count": len(persona_payload.get("admitted_personas") or []),
                "rejected_persona_count": len(persona_payload.get("rejected_personas") or []),
                "llm_council_ready": bool(
                    persona_payload["downstream_consumability"].get("llm_council_ready")
                ),
            }
        )
        assert_persona_artifact_ready_for_llm_council(persona_payload)

        state.advance(Stage.COUNCIL)
        for key, value in persona_telemetry.items():
            state.record_artifact(key, str(value))
        council = KarpathySession(
            gateway=self.gateway_v2,
            layers=list(DEFAULT_LAYERS[: council_round_budget]),
            personas=personas,
            evidence_refs=evidence_refs,
            active_persona_count=active_persona_count,
            progress_callback=self.progress_callback,
        )
        council.run_all()
        mirofish_runtime = build_mirofish_runtime_record(report=report, council=council)
        state.record_artifact("council_id", report.id)
        state.record_artifact("council_turn_count", str(len(council.turn_transcript)))
        state.record_artifact(
            "mirofish_runtime_valid",
            "true" if mirofish_runtime.get("valid") else "false",
        )
        state.record_artifact(
            "mirofish_workflow_phases",
            ",".join(mirofish_runtime.get("workflow_phases", []) or []),
        )
        graph_building = mirofish_runtime.get("graph_building") or {}
        simulation = mirofish_runtime.get("simulation") or {}
        report_generation = mirofish_runtime.get("report_generation") or {}
        deep_interaction = mirofish_runtime.get("deep_interaction") or {}
        state.record_artifact("mirofish_world_node_count", str(graph_building.get("world_node_count", 0)))
        state.record_artifact("mirofish_world_edge_count", str(graph_building.get("world_edge_count", 0)))
        state.record_artifact("mirofish_simulation_event_count", str(len(simulation.get("events") or [])))
        state.record_artifact(
            "mirofish_report_agent_ready",
            "true" if report_generation.get("report_agent_ready") else "false",
        )
        state.record_artifact(
            "mirofish_deep_interaction_ready",
            "true" if deep_interaction.get("ready") else "false",
        )
        protocol_trace = next(iter(getattr(council, "protocol_traces_by_round", {}).values()), {})
        if isinstance(protocol_trace, dict):
            state.record_artifact("council_protocol_runtime", str(protocol_trace.get("runtime", "")))
            state.record_artifact("council_protocol_phase_count", str(protocol_trace.get("phase_count", "")))
        self._emit(state, Stage.COUNCIL)

        reference_runtime_artifacts = build_reference_runtime_artifacts(
            report=report,
            council=council,
            evidence_summary=evidence_summary,
            gateway=self.gateway_v2,
            require_live=self.require_live,
        )
        state.record_artifact(
            "react_section_count",
            str(reference_runtime_artifacts["react"]["section_count"]),
        )
        state.record_artifact(
            "react_executed_section_count",
            str(reference_runtime_artifacts["react"].get("executed_section_count", 0)),
        )
        state.record_artifact(
            "react_tool_call_count",
            str(reference_runtime_artifacts["react"].get("total_tool_calls", 0)),
        )
        state.record_artifact(
            "react_backend_tool_call_count",
            str(reference_runtime_artifacts["react"].get("backend_tool_calls", 0)),
        )
        state.record_artifact(
            "react_gateway_llm_enabled",
            "true" if reference_runtime_artifacts["react"].get("gateway_llm_enabled") else "false",
        )
        state.record_artifact(
            "react_execution_modes",
            ",".join(reference_runtime_artifacts["react"].get("execution_modes", []) or []),
        )
        state.record_artifact(
            "react_llm_response_count",
            str(reference_runtime_artifacts["react"].get("llm_response_count", 0)),
        )
        state.record_artifact(
            "gbrain_content_hash",
            str(reference_runtime_artifacts["gbrain"]["content_hash"]),
        )
        state.record_artifact(
            "gbrain_runtime_valid",
            "true" if reference_runtime_artifacts["gbrain"].get("gbrain_runtime_valid") else "false",
        )
        state.record_artifact(
            "gbrain_event_count",
            str(reference_runtime_artifacts["gbrain"].get("gbrain_event_count", 0)),
        )
        state.record_artifact(
            "gbrain_typed_link_count",
            str(reference_runtime_artifacts["gbrain"].get("gbrain_typed_link_count", 0)),
        )
        state.record_artifact(
            "gbrain_brain_first_route",
            ",".join(reference_runtime_artifacts["gbrain"].get("gbrain_brain_first_route", []) or []),
        )
        state.record_artifact(
            "gbrain_search_mode",
            str(reference_runtime_artifacts["gbrain"].get("gbrain_search_mode", "")),
        )
        state.record_artifact(
            "gbrain_license",
            str(reference_runtime_artifacts["gbrain"].get("gbrain_license", "")),
        )
        wiki_governance = reference_runtime_artifacts["gbrain"].get("wiki_governance", {})
        if isinstance(wiki_governance, dict):
            state.record_artifact("wiki_raw_path", str(wiki_governance.get("raw_path", "")))
            state.record_artifact("wiki_compiled_path", str(wiki_governance.get("wiki_path", "")))
            state.record_artifact(
                "wiki_dual_path_enforced",
                "true" if wiki_governance.get("separate_paths") else "false",
            )

        state.advance(Stage.REPORT)
        report_md = _compose_six_chapter_report(
            brief,
            report,
            council,
            targeting_map,
            evidence_summary=evidence_summary,
            reference_runtime_artifacts=reference_runtime_artifacts,
            claim_evidence_matrix=claim_evidence_matrix,
            research_audit_appendix=research_audit_appendix,
            require_live=self.require_live,
        )
        self._require_live_report(report_md)
        self._emit(state, Stage.REPORT)

        hitl_results["report"] = self.hitl_adapter.gate_report(report_md)
        self._record_hitl_gate(state, "report", hitl_results["report"])
        self._require_approved_gate("report", hitl_results["report"])

        state.advance(Stage.VAULT)
        vault_path = self._save_to_vault(brief.id, report_md, run_id=state.run_id)
        state.record_artifact("vault_path", str(vault_path))
        retrospective = self._maybe_record_learning(report, council, evidence_summary)
        if retrospective is not None:
            state.record_artifact("learning_count", str(len(retrospective.learnings)))
        self._emit(state, Stage.VAULT)

        state.advance(Stage.AGENTS)
        self._emit(state, Stage.AGENTS)

        state.advance(Stage.DONE)
        self._emit(state, Stage.DONE)

        return IdeaToCouncilResult(
            state=state,
            brief=brief,
            design_doc=design_doc,
            consensus_plan=consensus_plan,
            targeting_map=targeting_map,
            evidence_refs=evidence_refs,
            evidence_summary=evidence_summary,
            report=report,
            report_md=report_md,
            vault_path=vault_path,
            hitl_results=hitl_results,
            progress_events=list(self.progress_events),
            agents=agents,
            council=council,
            reference_runtime_artifacts=reference_runtime_artifacts,
            retrospective=retrospective,
        )

    def _require_approved_gate(self, gate_name: str, result: HITLResult) -> None:
        if self.require_live:
            assert_live_hitl(gate_name, result)

    def _record_hitl_gate(self, state: PipelineState, gate_name: str, result: HITLResult) -> None:
        state.record_artifact(f"{gate_name}_gate_status", result.status)
        state.record_artifact(f"{gate_name}_gate_mode", str(getattr(self.hitl_adapter, "mode", "custom")))
        state.record_artifact(f"{gate_name}_gate_synthetic", "true" if result.synthetic else "false")

    def _require_live_evidence(self, evidence_summary: dict[str, Any], refs: list[EvidenceRef]) -> None:
        if self.require_live:
            assert_live_evidence(evidence_summary, refs)
            if not any(str(ref.source_grade).upper() in {"A", "B"} for ref in refs):
                raise LiveModeViolation("live mode requires at least one A/B-grade evidence record")

    def _require_live_report(self, report_md: str) -> None:
        if self.require_live:
            assert_live_report(report_md)

    def _brief_from_interview(
        self,
        interview: InterviewSession,
        raw_text: str,
        design_doc: DesignDoc,
    ) -> ResearchBrief:
        embedded_answers = _extract_embedded_interview_answers(raw_text)
        user_answer_count = len([value for value in embedded_answers.values() if str(value).strip()])
        answer_bank = {
            "research_question": embedded_answers.get("research_question")
            or default_research_question(raw_text, design_doc=design_doc),
            "purpose": embedded_answers.get("purpose") or design_doc.demand_reality or "decide next action",
            "context": embedded_answers.get("context") or design_doc.contrary_framing or design_doc.status_quo,
            "known": embedded_answers.get("known")
            or "; ".join(design_doc.implicit_capabilities)
            or "no prior facts provided",
            "deliverable_type": embedded_answers.get("deliverable_type") or "research report",
            "quality_bar": embedded_answers.get("quality_bar")
            or "source-backed, council-ready, and scoped by OfficeHours forcing questions",
        }
        trace: list[dict[str, Any]] = []
        for _ in range(6):
            next_item = interview.next_question()
            if next_item is None:
                break
            answer_key = _interview_answer_key(next_item.label)
            answer_text = str(answer_bank.get(answer_key) or answer_bank["research_question"])
            options = interview.question_options(next_item.dimension_id)
            interview.answer(answer_key, answer_text)
            trace.append(
                {
                    "dimension_id": next_item.dimension_id,
                    "label": next_item.label,
                    "answer_key": answer_key,
                    "option_count": len(options),
                    "source": "user" if answer_key in embedded_answers else "office_hours",
                }
            )
        brief = interview.to_brief()
        office_hours_fill_count = sum(1 for item in trace if item["source"] == "office_hours")
        trace_source = (
            "office_hours_synthetic"
            if user_answer_count == 0
            else "user_interview"
            if office_hours_fill_count == 0
            else "mixed_user_office_hours"
        )
        setattr(brief, "interview_trace", trace)
        brief.original_topic = _extract_original_topic_anchor(raw_text)
        setattr(brief, "topic_anchor", brief.original_topic)
        setattr(brief, "interview_trace_source", trace_source)
        setattr(brief, "synthetic_interview_trace", user_answer_count == 0)
        setattr(brief, "mixed_interview_trace", user_answer_count > 0 and office_hours_fill_count > 0)
        setattr(brief, "interview_effective_answer_count", user_answer_count or len(trace))
        setattr(brief, "interview_user_answer_count", user_answer_count)
        setattr(brief, "interview_office_hours_fill_count", office_hours_fill_count)
        show_prd_plan = interview.show_me_the_prd_plan
        if show_prd_plan is not None:
            setattr(brief, "show_me_the_prd_plan", show_prd_plan)
            setattr(
                brief,
                "show_me_the_prd_artifacts",
                show_me_the_prd_artifacts(
                    show_prd_plan,
                    user_answer_count=user_answer_count,
                    office_hours_fill_count=office_hours_fill_count,
                ),
            )
        brief.known_facts = list(design_doc.implicit_capabilities)
        if embedded_answers.get("known"):
            brief.known_facts = _split_interview_list(embedded_answers["known"])
        brief.constraints = list(design_doc.challenged_premises)
        brief.success_criteria = [
            design_doc.narrowest_wedge,
            design_doc.future_fit,
        ]
        if embedded_answers.get("quality_bar"):
            brief.success_criteria.append(embedded_answers["quality_bar"])
        planning_answers = {
            "research_question": brief.research_question,
            "purpose": brief.purpose,
            "context": brief.context,
            "known": "; ".join(brief.known_facts),
            "deliverable_type": brief.deliverable_type,
            "quality_bar": brief.quality_bar,
        }
        planning = build_product_planning_projection(
            raw_text,
            planning_answers,
            design_doc=design_doc,
        )
        brief.planning_prd = planning["planning_prd"]
        brief.feature_hierarchy = planning["feature_hierarchy"]
        brief.user_flow = planning["user_flow"]
        brief.planning_review_policy = planning["planning_review_policy"]
        return brief

    def _emit(self, state: PipelineState, stage: Stage) -> None:
        contract = contract_for_stage(stage)
        event = {
            "run_id": state.run_id,
            "stage": stage.value,
            "artifacts": dict(state.artifacts),
        }
        if contract is not None:
            event["reference_step"] = contract.step
            event["reference_stage_name"] = contract.name
            event["reference_projects"] = list(contract.references)
            event["reference_notes"] = list(contract.notes)
        if self.research_contract is not None:
            event = scope_event(event, self.research_contract)
        self.progress_events.append(event)
        if self.progress_callback is not None:
            self.progress_callback(event)

    def _emit_research_plan_progress(self, plan: Any) -> None:
        queries = list(getattr(plan, "queries", []) or [])
        if not queries:
            return
        backends = _research_backend_labels(self.research_runner)
        query_routes = [dict(route) for route in getattr(plan, "query_routes", []) if isinstance(route, dict)]
        self._emit_progress(
            {
                "event": "research_progress",
                "stage": Stage.RESEARCH.value,
                "status": "query_route_ledger_built",
                "topic_anchor": getattr(plan, "topic_anchor", ""),
                "route_count": len(query_routes),
                "route_ids": [str(route.get("route_id") or "") for route in query_routes],
                "route_version": query_routes[0].get("route_version") if query_routes else None,
                "routes": query_routes,
            }
        )
        self._emit_progress(
            {
                "event": "research_progress",
                "stage": Stage.RESEARCH.value,
                "status": "research_plan_ready",
                "queries": queries,
                "query_routes": query_routes,
                "query_count": len(queries),
                "topic_anchor": getattr(plan, "topic_anchor", ""),
                "backends": backends,
            }
        )
        routes_by_query = {str(route.get("query") or ""): route for route in query_routes}
        for index, query in enumerate(queries, start=1):
            route = routes_by_query.get(str(query), {})
            event = {
                "event": "research_progress",
                "stage": Stage.RESEARCH.value,
                "status": "searching",
                "query": query,
                "topic_anchor": getattr(plan, "topic_anchor", ""),
                "query_index": index,
                "query_count": len(queries),
                **_route_progress_metadata(route),
                "backends": backends,
            }
            self._emit_progress(event)
            self._emit_route_metadata_gap_progress(event, origin_status="searching")

    def _record_source_decision_ledger(
        self,
        state: Any,
        findings: list[Finding],
        audit: Any,
        plan: Any,
    ) -> SourceDecisionLedger:
        ledger = build_source_decision_ledger(findings, audit=audit, plan=plan)
        payload = ledger.to_dict()
        summary = payload["summary"]
        state.record_artifact("source_decision_ledger", json.dumps(payload, ensure_ascii=False, sort_keys=True))
        state.record_artifact("source_decision_summary", json.dumps(summary, ensure_ascii=False, sort_keys=True))
        topic_anchor = getattr(plan, "topic_anchor", "")
        self._emit_progress(
            {
                "event": "research_progress",
                "stage": "quality_gate",
                "status": "source_decision_ledger_built",
                "topic_anchor": topic_anchor,
                **summary,
            }
        )
        max_emitted = int(os.getenv("MUCHANIPO_MAX_RESEARCH_PROGRESS_SOURCES", "24"))
        routes_by_query = {
            str(route.get("query") or ""): route
            for route in getattr(plan, "query_routes", [])
            if isinstance(route, dict)
        }
        for decision in ledger.decisions[:max_emitted]:
            route = routes_by_query.get(str(getattr(decision, "query", "") or ""), {})
            if not route:
                route = next(
                    (
                        route
                        for route in getattr(plan, "query_routes", []) or []
                        if isinstance(route, dict) and str(route.get("route_id") or "") == str(decision.route_id or "")
                    ),
                    {},
                )
            base_event = {
                "event": "research_progress",
                "stage": Stage.RESEARCH.value,
                "topic_anchor": topic_anchor,
                "source_id": decision.source_id,
                **_route_progress_metadata(route, route_id=decision.route_id),
                "route_facet_id": decision.route_facet_id,
                "route_intent": decision.route_intent,
                "route_source_class": decision.route_source_class,
                "route_authority_requirement": decision.route_authority_requirement,
                "route_acceptance_rules": list(decision.route_acceptance_rules),
                "route_purpose": decision.route_purpose,
                "route_backend": decision.route_backend,
                "source_title": decision.raw_title,
                "source_url": decision.raw_url,
                "canonical_id": decision.canonical_id,
                "canonical_url": decision.canonical_url,
                "identifier_kind": decision.identifier_kind,
                "resolver_status": decision.resolver_status,
                "source_kind": decision.source_kind,
                "source_role": decision.source_role,
                "accepted": decision.accepted,
                "decision": decision.decision,
                "relevance_score": decision.relevance_score,
                "rejection_codes": list(decision.rejection_codes),
                "reason": decision.reason,
                "source_confidence_axis": dict(decision.source_confidence_axis),
                "source_freshness": dict(decision.source_freshness),
                "source_freshness_stale": decision.source_freshness_stale,
                "source_freshness_followup_reason": decision.source_freshness_followup_reason,
            }
            self._emit_progress({**base_event, "status": "source_resolved"})
            self._emit_route_metadata_gap_progress(base_event, origin_status="source_resolved")
            self._emit_progress({**base_event, "status": "source_decision"})
            self._emit_route_metadata_gap_progress(base_event, origin_status="source_decision")
        return ledger

    def _record_refutation_loop(
        self,
        state: Any,
        *,
        plan: Any,
        claim_evidence_matrix: ClaimEvidenceMatrix,
        source_decision_ledger: SourceDecisionLedger,
    ) -> RefutationLoopReport:
        report = run_refutation_loop(
            plan,
            claim_matrix=claim_evidence_matrix,
            source_decision_ledger=source_decision_ledger,
        )
        payload = report.to_dict()
        summary = report.summary()
        state.record_artifact("refutation_loop_report", json.dumps(payload, ensure_ascii=False, sort_keys=True))
        state.record_artifact("refutation_loop_summary", json.dumps(summary, ensure_ascii=False, sort_keys=True))
        topic_anchor = getattr(plan, "topic_anchor", "")
        for event in report.events:
            self._emit_progress(
                {
                    "event": "research_progress",
                    "stage": "quality_gate",
                    "topic_anchor": topic_anchor,
                    **event,
                }
            )
        return report

    def _emit_research_source_progress(self, findings: list[Finding], plan: Any) -> None:
        seen: set[str] = set()
        emitted = 0
        audit = build_research_quality_audit(findings, plan)
        evaluations_by_id = {item.source_id: item for item in audit.source_evaluations}
        routes_by_query = {
            str(route.get("query") or ""): route
            for route in getattr(plan, "query_routes", [])
            if isinstance(route, dict)
        }
        for finding in findings:
            for ref in finding.support:
                key = f"{ref.source_title}|{ref.source_url}|{ref.quote}"
                if key in seen:
                    continue
                seen.add(key)
                emitted += 1
                provenance = ref.provenance or {}
                metadata = provenance.get("metadata", {}) if isinstance(provenance, dict) else {}
                query = ""
                if isinstance(metadata, dict):
                    query = str(metadata.get("query") or "")
                if not query and isinstance(provenance, dict):
                    query = str(provenance.get("query") or "")
                claim_prefix = "Initial research direction for: "
                if not query and finding.claim.startswith(claim_prefix):
                    query = finding.claim[len(claim_prefix):]
                evaluation = evaluations_by_id.get(ref.id)
                route = routes_by_query.get(str(query), {})
                base_event = {
                    "event": "research_progress",
                    "stage": Stage.RESEARCH.value,
                    "query": query,
                    **_route_progress_metadata(route),
                    "source_title": ref.source_title,
                    "source_url": ref.source_url,
                    "source_grade": ref.source_grade,
                    "access_status": ref.access_status,
                    "topic_anchor": getattr(plan, "topic_anchor", ""),
                }
                if evaluation is not None:
                    base_event.update(
                        {
                            "source_kind": evaluation.source_kind,
                            "accepted": evaluation.accepted,
                            "facet_ids": list(evaluation.facet_ids),
                            "relevance_score": evaluation.relevance_score,
                            "reason": evaluation.reason,
                        }
                    )
                self._emit_progress({**base_event, "status": "source_found"})
                self._emit_route_metadata_gap_progress(base_event, origin_status="source_found")
                if evaluation is not None:
                    self._emit_progress({**base_event, "status": "source_evaluated"})
                    self._emit_route_metadata_gap_progress(base_event, origin_status="source_evaluated")
                max_emitted = int(os.getenv("MUCHANIPO_MAX_RESEARCH_PROGRESS_SOURCES", "24"))
                if emitted >= max_emitted:
                    break
            if emitted >= max_emitted:
                break
        for gap in audit.gaps:
            self._emit_progress(
                {
                    "event": "research_progress",
                    "stage": Stage.RESEARCH.value,
                    "status": "knowledge_gap",
                    "topic_anchor": getattr(plan, "topic_anchor", ""),
                    **gap.to_dict(),
                }
            )
        self._emit_progress(
            {
                "event": "research_progress",
                "stage": Stage.RESEARCH.value,
                "status": "facet_summary",
                "facets": audit.to_dict()["facets"],
                "gap_count": len(audit.gaps),
                "topic_anchor": getattr(plan, "topic_anchor", ""),
            }
        )

    def _emit_progress(self, event: dict[str, Any]) -> None:
        if self.research_contract is not None:
            event = scope_event(event, self.research_contract)
        event = assert_research_event_contract(event)
        self.progress_events.append(event)
        if self.progress_callback is not None:
            self.progress_callback(event)

    def _emit_route_metadata_gap_progress(
        self,
        event: dict[str, Any],
        *,
        origin_status: str,
        reason: str = "planned_route_not_found",
    ) -> None:
        if event.get("route_metadata_gap") is not True:
            return
        gap_event: dict[str, Any] = {
            "event": "research_progress",
            "stage": event.get("stage") or Stage.RESEARCH.value,
            "status": "route_metadata_gap",
            "topic_anchor": event.get("topic_anchor", ""),
            "origin_status": origin_status,
            "reason": reason,
            "route_id": event.get("route_id") or "unrouted",
        }
        for key in (
            "query",
            "query_index",
            "query_count",
            "source_id",
            "source_title",
            "source_url",
            "decision",
            "resolver_status",
        ):
            if key in event:
                gap_event[key] = event[key]
        self._emit_progress(gap_event)

    def _save_to_vault(self, brief_id: str, report_md: str, *, run_id: str | None = None) -> Path:
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{brief_id}.md"
        if self.require_live:
            suffix = _safe_filename(run_id or datetime.now(timezone.utc).isoformat())
            filename = f"{brief_id}-{suffix}.md"
        path = self.vault_dir / filename
        path.write_text(report_md, encoding="utf-8")
        return path

    def _maybe_record_learning(
        self,
        report: ResearchReport,
        council: KarpathySession,
        evidence_summary: dict[str, Any],
    ) -> Retrospective | None:
        if not self.enable_learning:
            return None
        log = LearningsLog(log_path=self.learning_log_path) if self.learning_log_path else LearningsLog()
        score = min(100.0, max(0.0, report.confidence * 100.0))
        verdict = "PASS" if evidence_summary.get("unsupported_finding_count", 0) == 0 else "UNCERTAIN"
        return Retro(log=log).summarize(
            council_id=report.id,
            topic=report.title,
            verdict=verdict,
            score=score,
            eval_result={
                "scores": {},
                "grounding": {
                    "verified_claim_ratio": evidence_summary.get("verified_claim_ratio", 0.0),
                    "unsupported_critical_claim_count": evidence_summary.get("unsupported_finding_count", 0),
                },
            },
            council_report={
                "consensus": report.executive_summary,
                "open_questions": list(report.open_questions),
                "personas": [
                    {"name": getattr(persona, "name", ""), "confidence": 0.0}
                    for persona in getattr(council, "personas", [])
                ],
            },
            rounds=len(getattr(council, "rounds", [])),
            duration_minutes=0.0,
        )


def _compose_six_chapter_report(
    brief: ResearchBrief,
    report: ResearchReport,
    council: KarpathySession,
    targeting_map: TargetingMap,
    *,
    evidence_summary: dict[str, Any] | None = None,
    reference_runtime_artifacts: dict[str, Any] | None = None,
    claim_evidence_matrix: ClaimEvidenceMatrix | None = None,
    research_audit_appendix: dict[str, Any] | None = None,
    require_live: bool = False,
) -> str:
    digests = _round_digests(council, report.evidence_refs, require_live=require_live)
    chapters = PyramidFormatter().reorder_all(ChapterMapper().map(digests))
    chapter_evidence = _chapter_evidence_map(digests, report.evidence_refs)
    evidence_kind_by_id = _evidence_kind_by_id(report.evidence_refs)
    grounding_rows: list[tuple[int, str, list[str]]] = []
    lines = [
        f"# {report.title}",
        "",
        f"Brief ID: `{brief.id}`",
        f"Targeting domains: {', '.join(targeting_map.domains)}",
        "",
        "## Run Metadata",
        "",
    ]
    for limitation in report.limitations:
        lines.append(f"- Limitation: {limitation}")
    if not report.limitations:
        lines.append("- Limitation: none recorded")
    lines.extend([
        "",
        "## Evidence Index",
        "",
    ])
    _append_evidence_health(lines, evidence_summary or {}, report.evidence_refs)
    for ref in report.evidence_refs:
        lines.extend(_evidence_index_lines(ref))
    lines.append("")

    for chapter in chapters:
        evidence_ids = chapter_evidence.get(chapter.chapter_no, [])
        lead_claim = _claim_with_evidence(chapter.lead_claim, evidence_ids, evidence_kind_by_id)
        grounding_rows.append((chapter.chapter_no, chapter.lead_claim, evidence_ids))
        lines.extend([
            f"## Chapter {chapter.chapter_no}: {chapter.title}",
            "",
            lead_claim,
            "",
        ])
        for claim in chapter.body_claims:
            lines.append(f"- {_claim_with_evidence(claim, evidence_ids, evidence_kind_by_id)}")
            grounding_rows.append((chapter.chapter_no, claim, evidence_ids))
        lines.append("")
    _append_claim_grounding_matrix(lines, grounding_rows, evidence_kind_by_id)
    if claim_evidence_matrix is not None:
        _append_strict_claim_evidence_matrix(lines, claim_evidence_matrix)
    if research_audit_appendix:
        lines.append(render_research_audit_appendix(research_audit_appendix).rstrip())
    if reference_runtime_artifacts:
        _append_react_plan(lines, reference_runtime_artifacts.get("react", {}))
        _append_gbrain_snapshot(lines, reference_runtime_artifacts.get("gbrain", {}))
    return "\n".join(lines).strip() + "\n"


def _chapter_evidence_map(
    digests: list[RoundDigest],
    evidence_refs: list[EvidenceRef],
) -> dict[int, list[str]]:
    mapper = ChapterMapper()
    known_ids = {ref.id for ref in evidence_refs}
    out: dict[int, list[str]] = {}
    for digest in digests:
        chapter = mapper.layer_to_chapter.get(digest.layer_id.split("_", 1)[0])
        if chapter is None:
            continue
        ids = [evidence_id for evidence_id in digest.evidence_ref_ids if evidence_id in known_ids]
        out.setdefault(chapter, [])
        out[chapter].extend(ids)
    for chapter, ids in list(out.items()):
        out[chapter] = _dedupe_strings(ids)
    return out


def _evidence_kind_by_id(evidence_refs: list[EvidenceRef]) -> dict[str, str]:
    out: dict[str, str] = {}
    for ref in evidence_refs:
        provenance = ref.provenance or {}
        kind = str(provenance.get("kind") or "").strip().lower()
        if not kind and ref.id.startswith("mock-"):
            kind = "mock"
        out[ref.id] = kind
    return out


def _append_evidence_health(
    lines: list[str],
    evidence_summary: dict[str, Any],
    evidence_refs: list[EvidenceRef],
) -> None:
    grade_counts: dict[str, int] = {}
    for ref in evidence_refs:
        grade = str(ref.source_grade or "?").upper()
        grade_counts[grade] = grade_counts.get(grade, 0) + 1
    grade_text = ", ".join(f"{grade}:{count}" for grade, count in sorted(grade_counts.items())) or "none"
    lines.extend([
        "### Evidence Health",
        "",
        f"- Trusted evidence: {int(evidence_summary.get('trusted', 0) or 0)} / {len(evidence_refs)}",
        f"- Verified claim ratio: {float(evidence_summary.get('verified_claim_ratio', 0.0) or 0.0):.2f}",
        f"- Unsupported finding count: {int(evidence_summary.get('unsupported_finding_count', 0) or 0)}",
        f"- Source grade counts: {grade_text}",
        "",
        "### Sources",
        "",
    ])


def _evidence_index_lines(ref: EvidenceRef) -> list[str]:
    provenance = ref.provenance or {}
    provenance_kind = str(provenance.get("kind") or "unknown")
    provenance_source = str(provenance.get("source") or provenance.get("url") or "").strip()
    source = ref.source_url or provenance_source or "-"
    title = ref.source_title or "(untitled source)"
    quote = _snippet(ref.quote or str(provenance.get("source_text") or ""), limit=180)
    lines = [
        f"- `{ref.id}` {title}",
        f"  - URL: {source}",
        f"  - Grade: {ref.source_grade}",
        f"  - Provenance: {provenance_kind}",
    ]
    if ref.access_status:
        lines.append(f"  - Access status: {ref.access_status}")
    if provenance_source and provenance_source != source:
        lines.append(f"  - Provenance source: {provenance_source}")
    if quote:
        lines.append(f"  - Quote: {quote}")
    return lines


def _snippet(value: str, *, limit: int) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def _claim_with_evidence(
    claim: str,
    evidence_ids: list[str],
    evidence_kind_by_id: dict[str, str] | None = None,
) -> str:
    cleaned = claim.strip()
    if not cleaned:
        cleaned = "추가 검증이 필요한 빈 주장"
    if _is_gap_or_policy_claim(cleaned):
        return f"{cleaned} (Evidence gap)"
    if not evidence_ids:
        return f"{cleaned} (Evidence: none)"
    evidence_kind_by_id = evidence_kind_by_id or {}
    refs = ", ".join(f"`{evidence_id}`" for evidence_id in evidence_ids)
    if _mock_only_evidence(evidence_ids, evidence_kind_by_id):
        return f"{cleaned} (Mock evidence, not source-backed: {refs})"
    return f"{cleaned} (Evidence: {refs})"


def _is_gap_or_policy_claim(claim: str) -> bool:
    normalized = " ".join(str(claim or "").split())
    return normalized.startswith(
        (
            "부족한 근거 범위:",
            "외부 시장성 주장은",
            "TAM/SAM/SOM, 경쟁 제품 가격, 구매의향은",
            "확보된 출처가 직접 지지하는 관찰과",
        )
    )


def _append_claim_grounding_matrix(
    lines: list[str],
    grounding_rows: list[tuple[int, str, list[str]]],
    evidence_kind_by_id: dict[str, str] | None = None,
) -> None:
    evidence_kind_by_id = evidence_kind_by_id or {}
    lines.extend([
        "## Claim Grounding Matrix",
        "",
        "| Chapter | Claim | Evidence |",
        "| --- | --- | --- |",
    ])
    for chapter_no, claim, evidence_ids in grounding_rows:
        evidence = _evidence_cell(claim, evidence_ids, evidence_kind_by_id)
        lines.append(f"| {chapter_no} | {_table_cell(claim)} | {evidence} |")
    lines.append("")


def _append_strict_claim_evidence_matrix(lines: list[str], matrix: ClaimEvidenceMatrix) -> None:
    summary = matrix.to_dict()
    lines.extend([
        "## Strict Claim-Evidence Matrix",
        "",
        f"- Supported claims: {summary['supported_count']} / {summary['row_count']}",
        f"- Partial claims: {summary['partial_count']}",
        f"- Unsupported claims: {summary['unsupported_count']}",
        f"- Supported ratio: {float(summary['supported_ratio']):.2f}",
        "",
        "| Status | Claim | Evidence | Reason |",
        "| --- | --- | --- | --- |",
    ])
    for row in matrix.rows:
        evidence = ", ".join(f"`{evidence_id}`" for evidence_id in row.evidence_ids) or "none"
        lines.append(
            f"| {row.status} | {_table_cell(row.claim)} | {evidence} | {_table_cell(row.reason)} |"
        )
    lines.append("")


def _evidence_cell(claim: str, evidence_ids: list[str], evidence_kind_by_id: dict[str, str]) -> str:
    if _is_gap_or_policy_claim(claim):
        return "evidence gap / backlog"
    if not evidence_ids:
        return "none"
    refs = ", ".join(f"`{evidence_id}`" for evidence_id in evidence_ids)
    if _mock_only_evidence(evidence_ids, evidence_kind_by_id):
        return f"mock-only, not source-backed: {refs}"
    return refs


def _mock_only_evidence(evidence_ids: list[str], evidence_kind_by_id: dict[str, str]) -> bool:
    return bool(evidence_ids) and all(evidence_kind_by_id.get(evidence_id) == "mock" for evidence_id in evidence_ids)


def _table_cell(value: str) -> str:
    return " ".join(value.replace("|", "\\|").split())


def _append_react_plan(lines: list[str], react: dict[str, Any]) -> None:
    lines.extend([
        "## ReACT Executed Sections",
        "",
        (
            "These sections are generated by executing the local ReACT loop: "
            "tool calls are parsed, observations are collected, and final answers "
            "are rendered from those observations."
        ),
        "",
    ])
    for idx, section in enumerate(react.get("sections", []), start=1):
        section_markdown = str(section.get("section_markdown") or section.get("final_answer") or "").strip()
        if not section_markdown:
            continue
        lines.extend([
            f"### ReACT Output {idx}: {section.get('title', '')}",
            "",
            section_markdown,
            "",
        ])
    lines.extend([
        "## ReACT Execution Plan",
        "",
        (
            "This appendix is generated by `src/search/react-report.py` and records "
            "the Think -> Act -> Observe -> Write plan required before report prose is finalized."
        ),
        "",
        f"- Minimum tool calls per section: {react.get('min_tool_calls', 0)}",
        f"- Available tools: {', '.join(str(tool) for tool in react.get('available_tools', []))}",
        "",
    ])
    for idx, section in enumerate(react.get("sections", []), start=1):
        lines.extend([
            f"### ReACT Section {idx}: {section.get('title', '')}",
            "",
            f"- THINK: {section.get('think', '')}",
            f"- ACT: {section.get('act', '')}",
            f"- OBSERVE: {section.get('observe', '')}",
            f"- WRITE: {section.get('write', '')}",
            "",
        ])


def _append_gbrain_snapshot(lines: list[str], gbrain: dict[str, Any]) -> None:
    lines.extend([
        "## GBrain Compiled Truth + Timeline",
        "",
        (
            "This section is generated through `src/hitl/vault-router.py` helpers. "
            "Compiled truth is the current best answer; timeline is the audit trail."
        ),
        "",
        f"- Slug: `{gbrain.get('slug', '')}`",
        f"- Content hash: `{gbrain.get('content_hash', '')}`",
        f"- Timeline entry: {gbrain.get('timeline_entry', '')}",
        "",
    ])
    summary = gbrain.get("evidence_summary") or {}
    if isinstance(summary, dict):
        lines.extend([
            "### Evidence Summary",
            "",
            f"- Trusted evidence: {summary.get('trusted', 0)}",
            f"- Verified claim ratio: {summary.get('verified_claim_ratio', 0.0)}",
            f"- Unsupported finding count: {summary.get('unsupported_finding_count', 0)}",
            "",
        ])
    lines.extend([
        "### Compiled Truth Snapshot",
        "",
        str(gbrain.get("compiled_truth", "")).strip(),
        "",
    ])
    governance = gbrain.get("wiki_governance") or {}
    if isinstance(governance, dict):
        lines.extend([
            "### Raw/Wiki Governance",
            "",
            f"- Raw path: `{governance.get('raw_path', '')}`",
            f"- Wiki path: `{governance.get('wiki_path', '')}`",
            f"- Raw SHA-256: `{governance.get('raw_sha256', '')}`",
            f"- Wiki SHA-256: `{governance.get('wiki_sha256', '')}`",
            f"- Separate paths: {governance.get('separate_paths', False)}",
            "",
        ])
    runtime = gbrain.get("gbrain_runtime") or {}
    if isinstance(runtime, dict):
        page = runtime.get("page") or {}
        source = runtime.get("source_attribution") or {}
        lines.extend([
            "### GBrain Runtime Record",
            "",
            f"- Runtime valid: {runtime.get('valid', False)}",
            f"- Page slug: `{page.get('slug', '')}`",
            f"- Event ledger entries: {len(runtime.get('event_ledger') or [])}",
            f"- Typed links: {len(runtime.get('typed_links') or [])}",
            f"- Brain-first route: {', '.join(runtime.get('brain_first_route') or [])}",
            f"- Search mode: `{(runtime.get('search_index') or {}).get('mode', '')}`",
            f"- Source IDs: {len(source.get('source_ids') or [])}",
            "",
        ])


def _round_digests(
    council: KarpathySession,
    evidence_refs: list[EvidenceRef],
    *,
    require_live: bool = False,
) -> list[RoundDigest]:
    evidence_ids = [ref.id for ref in evidence_refs]
    digests: list[RoundDigest] = []
    required_round_count = len(getattr(council, "layers", []) or []) if require_live else 10
    for idx in range(1, max(1, required_round_count) + 1):
        round_record = council.rounds[idx - 1] if idx <= len(council.rounds) else None
        if isinstance(round_record, RoundResult):
            key_claim = _visible_report_claim(round_record.key_claim)
            body_claims = [
                claim
                for claim in (_visible_report_claim(value) for value in list(round_record.body_claims))
                if claim and claim != key_claim
            ]
            round_evidence_ids = list(round_record.evidence_ref_ids)
            if not round_evidence_ids and not require_live:
                round_evidence_ids = evidence_ids
            digests.append(
                RoundDigest(
                    layer_id=round_record.layer_id,
                    chapter_title=round_record.chapter_title,
                    key_claim=key_claim or _fallback_layer_claim(round_record.chapter_title),
                    body_claims=body_claims,
                    evidence_ref_ids=round_evidence_ids,
                    confidence=round_record.confidence_score,
                    framework=round_record.framework,
                )
            )
            continue

        if round_record is None:
            if require_live:
                raise LiveModeViolation(
                    f"live mode requires structured council synthesis for layer L{idx}; got no round record"
                )
            continue

        round_mapping = round_record if isinstance(round_record, dict) else {}
        results = list(round_mapping.get("results", []))
        first = results[0] if results else {}
        analysis = str(first.get("analysis") or round_mapping.get("consensus") or "")
        if require_live and not analysis.strip():
            raise LiveModeViolation(
                f"live mode requires structured council synthesis for layer L{idx}; got synthetic fallback"
            )
        analysis = _visible_report_claim(analysis)
        if not analysis:
            continue
        key_points = [
            claim
            for claim in (_visible_report_claim(str(point)) for point in first.get("key_points", []) if point)
            if claim and claim != analysis
        ]
        digests.append(
            RoundDigest(
                layer_id=f"L{idx}_fallback",
                chapter_title=f"Layer {idx}",
                key_claim=analysis,
                body_claims=key_points,
                evidence_ref_ids=evidence_ids,
                confidence=float(first.get("confidence") or round_mapping.get("confidence") or 0.6),
            )
        )
    if digests and not any(digest.layer_id.startswith("L10") for digest in digests):
        digests.append(_fallback_executive_digest(digests, evidence_ids))
    return digests


def _visible_report_claim(value: str) -> str:
    cleaned = " ".join(str(value or "").split())
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if re.fullmatch(r"round\s+\d+\s+synthesis", lowered):
        return ""
    if cleaned.startswith("조건부 권고:"):
        return ""
    if cleaned.startswith("성공 기준은"):
        return ""
    return cleaned


def _fallback_layer_claim(title: str) -> str:
    return f"{title}은 직접 근거 범위를 확인한 뒤에만 결론으로 승격한다."


def _fallback_executive_digest(
    digests: list[RoundDigest],
    evidence_ids: list[str],
) -> RoundDigest:
    cited = _dedupe_strings([evidence_id for digest in digests for evidence_id in digest.evidence_ref_ids])
    if not cited:
        cited = list(evidence_ids[:4])
    return RoundDigest(
        layer_id="L10_executive_synthesis",
        chapter_title="Executive Summary + Recommendation",
        key_claim="현재 확보 근거로는 최종 결론을 확정하지 말고, 출처가 직접 지지하는 주장과 추가 검증이 필요한 주장을 분리해야 한다.",
        body_claims=[
            "확보된 출처가 직접 지지하는 관찰만 결론 후보로 승격한다.",
            "근거가 부족한 범위는 후속 조사 질문과 검증 backlog로 남긴다.",
            "다음 의사결정은 결론 확정이 아니라 보강할 출처·개념·반례를 정하는 것이다.",
        ],
        evidence_ref_ids=cited,
        confidence=min(0.64, max((digest.confidence for digest in digests), default=0.6)),
        framework="SCR",
    )


def _coerce_gateway_v2(
    model_gateway: ModelGateway | None,
    *,
    require_live_default: bool = False,
) -> GatewayV2:
    if model_gateway is None:
        return default_gateway(
            force_offline=_detect_offline_mode(),
            require_live_default=require_live_default,
        )
    if isinstance(model_gateway, GatewayV2):
        model_gateway.require_live_default = bool(
            getattr(model_gateway, "require_live_default", False)
            or require_live_default
        )
        return model_gateway

    provider = model_gateway.provider
    if provider is None and model_gateway.providers:
        provider = next(iter(model_gateway.providers.values()))
    if provider is None:
        if require_live_default:
            raise LiveModeViolation("live mode requires a non-mock model provider")
        provider = MockProvider(response="mock council critique")
    provider_name = getattr(provider, "name", provider.__class__.__name__)
    if require_live_default and str(provider_name).lower() == "mock":
        raise LiveModeViolation("live mode requires a non-mock model provider")
    return GatewayV2(
        providers={provider_name: provider},
        stage_routes={"council": provider_name},
        fallback_chain={"council": [provider_name]},
        budget=model_gateway.budget,
        audit=model_gateway.audit,
        require_live_default=require_live_default,
    )


def _chain_watchdog_timeout_sec(gateway: Any, stage: str, per_provider_timeout_sec: float) -> float:
    """Allow every live fallback candidate its own timeout plus a small handoff grace.

    The council watchdog should catch true chain stalls, not preempt the fallback
    chain at the exact moment the first provider's per-call timeout fires.  In
    MIMO/opencode-only live runs this gives MIMO one bounded attempt and still
    leaves time for the opencode-go fallback before declaring a product-blocking
    council timeout.
    """

    try:
        names = list((getattr(gateway, "fallback_chain", {}) or {}).get(stage) or [])
    except Exception:
        names = []
    candidate_count = max(1, len(names))
    if candidate_count <= 1:
        return float(per_provider_timeout_sec)
    grace = max(2.0, min(10.0, float(per_provider_timeout_sec) * 0.25))
    return float(per_provider_timeout_sec) * candidate_count + grace


def _council_compact_retry_enabled() -> bool:
    raw = os.environ.get("MUCHANIPO_COUNCIL_COMPACT_RETRY", "1")
    return raw.strip().casefold() not in {"0", "false", "no", "off", "disabled"}


def _council_progress_failure_kind(exc: Exception) -> str:
    text = str(exc).casefold()
    if "empty or too-short" in text:
        return "empty_live_output"
    if isinstance(exc, TimeoutError) or "timed out" in text:
        return "provider_timeout"
    if any(
        marker in text
        for marker in (
            "401",
            "403",
            "unauthorized",
            "forbidden",
            "invalid key",
            "invalid_key",
            "api key is not configured",
            "missing_credential",
            "mock_or_offline",
            "no live provider",
        )
    ):
        return "auth_or_policy_failure"
    if "rejected mock model result" in text or "placeholder model output" in text:
        return "mock_live_output"
    return "provider_error"


def _should_compact_retry_council_progress(exc: Exception) -> bool:
    if not _council_compact_retry_enabled():
        return False
    return _council_progress_failure_kind(exc) in {"empty_live_output", "provider_timeout"}


def _compact_council_retry_prompt(
    prompt: str,
    *,
    council_stage: str,
    layer_id: str,
    persona: str,
) -> str:
    max_chars = _council_compact_retry_prompt_chars()
    prompt_excerpt = _head_tail_excerpt(prompt, max_chars)
    return "\n".join(
        [
            "Return only valid JSON. No markdown.",
            "This is a compact retry after a live council provider returned empty, too-short, or timed out.",
            "Preserve the exact JSON schema requested by the original prompt.",
            "If evidence is insufficient, express uncertainty with needs_review or the closest schema field; do not fabricate facts.",
            f"Council stage: {council_stage}",
            f"Layer: {layer_id}",
            f"Persona: {persona}",
            "Original prompt excerpt follows:",
            prompt_excerpt,
        ]
    )


def _head_tail_excerpt(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head_chars = max(1, max_chars // 2)
    tail_chars = max(1, max_chars - head_chars)
    return f"{text[:head_chars]}\n\n[...middle of original prompt omitted for compact retry...]\n\n{text[-tail_chars:]}"


def _council_compact_retry_prompt_chars() -> int:
    raw = os.environ.get("MUCHANIPO_COUNCIL_COMPACT_RETRY_PROMPT_CHARS", "6000")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 6000
    return max(1000, min(value, 12000))


def _council_compact_retry_max_tokens(council_stage: str, current_max_tokens: Any) -> int:
    raw = os.environ.get("MUCHANIPO_COUNCIL_COMPACT_RETRY_MAX_TOKENS", "")
    try:
        configured = int(raw) if raw else 2048
    except (TypeError, ValueError):
        configured = 2048
    try:
        current = int(current_max_tokens)
    except (TypeError, ValueError):
        current = _council_stage_max_tokens(council_stage)
    return max(512, min(current, configured, 4096))


class _CouncilProviderProgressGateway:
    """Emit council provider-call progress around council preparation calls."""

    def __init__(
        self,
        gateway: GatewayV2,
        progress_callback: Callable[[dict], None] | None,
    ) -> None:
        self._gateway = gateway
        self._progress_callback = progress_callback

    def __getattr__(self, name: str) -> Any:
        return getattr(self._gateway, name)

    def call(self, stage: str, prompt: str, **kwargs: Any) -> Any:
        if stage != "council":
            return self._gateway.call(stage, prompt, **kwargs)

        timeout_sec = _council_provider_call_timeout_sec()
        council_stage = str(kwargs.get("council_stage") or "council_preparation")
        layer_id = str(kwargs.get("layer_id") or "council_preparation")
        provider_route = _provider_route_for_stage(self._gateway, "council")
        base_event = {
            "round": 0,
            "layer": layer_id,
            "stage": "council_progress",
            "pipeline_stage": "council",
            "council_stage": council_stage,
            "persona": str(kwargs.get("persona") or "persona_generator"),
            "provider_route": provider_route,
            "timeout_sec": timeout_sec,
            "prompt_chars": len(prompt),
        }
        self._emit({"event": "council_provider_call_start", **base_event})
        kwargs.setdefault("max_tokens", _council_stage_max_tokens(council_stage))
        if timeout_sec > 0:
            kwargs.setdefault("timeout", timeout_sec)
        started_at = time.monotonic()
        try:
            result = self._call_once(stage, prompt, timeout_sec, kwargs)
        except Exception as exc:
            result, base_event, started_at = self._retry_compact_or_raise(
                stage=stage,
                prompt=prompt,
                kwargs=kwargs,
                timeout_sec=timeout_sec,
                base_event=base_event,
                started_at=started_at,
                exc=exc,
            )

        response_text = getattr(result, "text", str(result)) if result else ""
        self._emit(
            {
                "event": "council_provider_call_done",
                **base_event,
                "elapsed_sec": round(time.monotonic() - started_at, 3),
                "provider": str(getattr(result, "provider", "")),
                "model": str(getattr(result, "model", "")),
                "response_chars": len(response_text),
                "http_status_class": "2xx",
                **_usage_token_fields_from_result(result),
            }
        )
        return result

    def _call_once(
        self,
        stage: str,
        prompt: str,
        timeout_sec: float,
        kwargs: dict[str, Any],
    ) -> Any:
        if timeout_sec > 0:
            return self._call_with_watchdog(
                stage,
                prompt,
                _chain_watchdog_timeout_sec(self._gateway, stage, timeout_sec),
                kwargs,
            )
        return self._gateway.call(stage, prompt, **kwargs)

    def _retry_compact_or_raise(
        self,
        *,
        stage: str,
        prompt: str,
        kwargs: dict[str, Any],
        timeout_sec: float,
        base_event: dict[str, Any],
        started_at: float,
        exc: Exception,
    ) -> tuple[Any, dict[str, Any], float]:
        failure_kind = _council_progress_failure_kind(exc)
        should_retry = _should_compact_retry_council_progress(exc)
        self._emit_provider_failure(
            base_event,
            started_at,
            exc,
            failure_kind=failure_kind,
            retry="compact_council_prompt" if should_retry else "none",
        )
        if not should_retry:
            raise exc

        council_stage = str(base_event["council_stage"])
        persona = str(base_event["persona"])
        compact_prompt = _compact_council_retry_prompt(
            prompt,
            council_stage=council_stage,
            layer_id=str(base_event["layer"]),
            persona=persona,
        )
        retry_kwargs = dict(kwargs)
        retry_kwargs["max_tokens"] = _council_compact_retry_max_tokens(
            council_stage,
            retry_kwargs.get("max_tokens"),
        )
        retry_event = {
            **base_event,
            "prompt_chars": len(compact_prompt),
            "retry": "compact_council_prompt",
            "failure_kind": failure_kind,
            "retry_max_tokens": retry_kwargs["max_tokens"],
        }
        self._emit({"event": "council_provider_call_start", **retry_event})
        retry_started_at = time.monotonic()
        try:
            result = self._call_once(stage, compact_prompt, timeout_sec, retry_kwargs)
        except Exception as retry_exc:
            retry_failure_kind = _council_progress_failure_kind(retry_exc)
            self._emit_provider_failure(
                retry_event,
                retry_started_at,
                retry_exc,
                failure_kind=retry_failure_kind,
                retry="compact_council_prompt",
            )
            raise
        return result, retry_event, retry_started_at

    def _emit_provider_failure(
        self,
        base_event: dict[str, Any],
        started_at: float,
        exc: Exception,
        *,
        failure_kind: str,
        retry: str,
    ) -> None:
        event_name = (
            "council_provider_call_timeout"
            if failure_kind == "provider_timeout"
            else "council_provider_call_error"
        )
        event = {
            "event": event_name,
            **base_event,
            "elapsed_sec": round(time.monotonic() - started_at, 3),
            "failure_kind": failure_kind,
            "retry": retry,
            "error_class": exc.__class__.__name__,
            "http_status_class": _http_status_class_from_exception(exc),
            "error": _redact_text(exc),
            "blocks_product_pass": True,
        }
        self._emit(event)

    def _call_with_watchdog(
        self,
        stage: str,
        prompt: str,
        timeout_sec: float,
        kwargs: dict[str, Any],
    ) -> Any:
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._gateway.call, stage, prompt, **kwargs)
        try:
            return future.result(timeout=timeout_sec)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TimeoutError(f"council provider call timed out after {timeout_sec:.3g}s") from exc
        finally:
            executor.shutdown(wait=False)

    def _emit(self, event: dict[str, Any]) -> None:
        if self._progress_callback is not None:
            self._progress_callback(event)


def _council_provider_call_timeout_sec() -> float:
    raw = (
        os.environ.get("MUCHANIPO_COUNCIL_PROVIDER_TIMEOUT_SEC")
        or os.environ.get("MUCHANIPO_COUNCIL_CALL_TIMEOUT_SEC")
        or os.environ.get("MUCHANIPO_OPENCODE_CLI_TIMEOUT_SEC")
        or ""
    )
    try:
        timeout_sec = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return timeout_sec if timeout_sec > 0 else 0.0


def _council_stage_max_tokens(council_stage: str) -> int:
    env_stage = f"MUCHANIPO_COUNCIL_{council_stage.upper()}_MAX_TOKENS"
    raw = (
        os.environ.get(env_stage)
        or os.environ.get("MUCHANIPO_OPENCODE_COUNCIL_MAX_TOKENS")
        or os.environ.get("MUCHANIPO_COUNCIL_MAX_TOKENS")
        or "4096"
    )
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 4096
    return max(1024, min(value, 8192))


def _provider_route_for_stage(gateway: GatewayV2, stage: str) -> str:
    stage_routes = getattr(gateway, "stage_routes", {}) or {}
    route = stage_routes.get(stage)
    if route:
        return str(route)
    fallback_chain = getattr(gateway, "fallback_chain", {}) or {}
    chain = fallback_chain.get(stage) or []
    return str(chain[0]) if chain else ""


def _redact_text(value: Any) -> str:
    return re.sub(
        r"(?i)(api[_-]?key|token|authorization|bearer|password|secret)\s*[:=]\s*[^\s,}]+",
        lambda match: f"{match.group(1)}=[REDACTED]",
        str(value),
    )


def _http_status_class_from_exception(exc: Exception) -> str:
    code = getattr(exc, "code", None) or getattr(exc, "status", None) or getattr(exc, "status_code", None)
    if code is None:
        match = re.search(r"\b([1-5]\d{2})\b", str(exc))
        code = match.group(1) if match else None
    try:
        status = int(code)
    except (TypeError, ValueError):
        return "unknown"
    return f"{status // 100}xx"


def _usage_token_fields_from_result(result: Any) -> dict[str, int]:
    raw = getattr(result, "raw", None)
    if not isinstance(raw, dict):
        return {}
    usage = raw.get("usage") or raw.get("usageMetadata") or {}
    if not isinstance(usage, dict):
        return {}
    aliases = {
        "usage_prompt_tokens": ("prompt_tokens", "input_tokens", "promptTokenCount"),
        "usage_completion_tokens": ("completion_tokens", "output_tokens", "candidatesTokenCount"),
        "usage_total_tokens": ("total_tokens", "totalTokenCount"),
    }
    fields: dict[str, int] = {}
    for output_key, input_keys in aliases.items():
        for input_key in input_keys:
            if input_key in usage:
                try:
                    fields[output_key] = max(0, int(usage.get(input_key) or 0))
                except (TypeError, ValueError):
                    pass
                break
    return fields


def _use_real_research_from_env() -> bool:
    return live_requested_from_env() or source_research_requested_from_env()


def _effective_council_round_budget(profile: ResearchDepthProfile) -> int:
    return _bounded_int_env(
        "MUCHANIPO_COUNCIL_ROUND_BUDGET",
        default=profile.council_round_budget,
        lower=1,
        upper=profile.council_round_budget,
    )


def _effective_active_persona_count(profile: ResearchDepthProfile) -> int:
    return _bounded_int_env(
        "MUCHANIPO_ACTIVE_PERSONA_COUNT",
        default=profile.active_persona_count,
        lower=1,
        upper=profile.persona_pool_size,
    )


def _bounded_int_env(name: str, *, default: int, lower: int, upper: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(lower, min(upper, value))


def _interview_answer_key(label: str) -> str:
    return {
        "deliverable": "deliverable_type",
        "quality": "quality_bar",
    }.get(label, label)


_EMBEDDED_INTERVIEW_LABELS = {
    "Q1_research_question": "research_question",
    "Q2_purpose": "purpose",
    "Q3_context": "context",
    "Q4_known": "known",
    "Q5_deliverable": "deliverable_type",
    "Q6_quality": "quality_bar",
}


PLAN_REVIEW_EDIT_TARGETS: frozenset[str] = frozenset(
    {
        "planning_prd.overview.one_line",
        "planning_prd.core_value.resolution",
        "planning_prd.target_scenarios.0.scenario",
        "planning_prd.target_scenarios.0.user_group",
        "feature_hierarchy.0.features.0.name",
        "planning_prd.success_metrics",
        "user_flow.nodes.start.label",
        "user_flow.nodes.questionnaire.label",
        "user_flow.nodes.output.label",
    }
)
PLAN_REVIEW_EDIT_SOURCES: frozenset[str] = frozenset(
    {
        "plannotator-inline-port",
        "plannotator-http",
        "plannotator",
    }
)


def _extract_embedded_interview_answers(raw_text: str) -> dict[str, str]:
    """Parse serve-mode interview answers merged into the pipeline topic.

    The Tauri JSONL flow sends the answered interview back as:
    ``[Q1_research_question] ...``. The pipeline still runs its internal
    InterviewSession for artifact compatibility, so we explicitly seed that
    session from the user answers instead of letting OfficeHours analysis text
    become the research query.
    """
    answers: dict[str, str] = {}
    pattern = re.compile(r"^\[(Q[1-6]_[^\]]+)\]\s*(.*)$", re.MULTILINE)
    matches = list(pattern.finditer(raw_text or ""))
    for idx, match in enumerate(matches):
        qid = match.group(1)
        key = _EMBEDDED_INTERVIEW_LABELS.get(qid)
        if key is None:
            continue
        start = match.start(2)
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw_text)
        value = raw_text[start:end].strip()
        if value:
            answers[key] = value
    return answers


def _extract_original_topic_anchor(raw_text: str) -> str:
    """Return the per-run user topic before embedded interview answers."""
    text = str(raw_text or "").strip()
    if not text:
        return ""
    match = re.search(r"^\[원 요청\]\s*(.+)$", text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    first_q = re.search(r"^\[Q[1-6]_[^\]]+\]", text, re.MULTILINE)
    if first_q:
        return text[: first_q.start()].strip()
    return text


def _assert_research_plan_preserves_topic_anchor(plan: Any, topic_anchor: str) -> None:
    anchor = str(getattr(plan, "topic_anchor", "") or topic_anchor or "").strip()
    if not anchor:
        return
    queries = list(getattr(plan, "queries", []) or [])
    first_query = str(queries[0] if queries else "")
    if first_query.strip() == anchor:
        return
    anchor_tokens = _topic_anchor_terms(anchor)
    if anchor_tokens and all(token in first_query for token in anchor_tokens):
        return
    raise LiveModeViolation(
        "source/live research plan lost the run topic anchor before first search query: "
        f"anchor={anchor!r}, first_query={first_query!r}"
    )


def _topic_anchor_terms(topic: str) -> list[str]:
    tokens = re.findall(r"[가-힣A-Za-z0-9]+", topic or "")
    stop = {"source", "backed", "deep", "research", "council", "persona"}
    return [token for token in tokens if len(token) >= 2 and token.casefold() not in stop][:8]


def _split_interview_list(value: str) -> list[str]:
    parts = [
        part.strip(" -•\t\r\n")
        for part in re.split(r"[;\n]+|,\s*(?=[가-힣A-Za-z0-9])", value or "")
    ]
    return [part for part in parts if part]


def _editable_plan_payload(brief: ResearchBrief) -> dict[str, Any]:
    return {
        "planning_prd": brief.planning_prd,
        "feature_hierarchy": brief.feature_hierarchy,
        "user_flow": brief.user_flow,
        "editable_summary": {
            "research_question": brief.research_question,
            "purpose": brief.purpose,
            "context": brief.context,
            "deliverable_type": brief.deliverable_type,
            "quality_bar": brief.quality_bar,
        },
    }


def _apply_plan_review_annotations(brief: ResearchBrief, annotations: list[dict[str, Any]]) -> int:
    edits: dict[str, str] = {}
    for item in annotations or []:
        edit = _plan_review_edit_from_annotation(item)
        if edit is not None:
            target, cleaned = edit
            edits[target] = cleaned
    if not edits:
        return 0

    if "planning_prd.overview.one_line" in edits:
        brief.research_question = edits["planning_prd.overview.one_line"]
    if "planning_prd.core_value.resolution" in edits:
        brief.purpose = edits["planning_prd.core_value.resolution"]
    if "planning_prd.target_scenarios.0.scenario" in edits:
        brief.context = edits["planning_prd.target_scenarios.0.scenario"]
    target_user = edits.get("planning_prd.target_scenarios.0.user_group", "")
    if "feature_hierarchy.0.features.0.name" in edits:
        brief.deliverable_type = edits["feature_hierarchy.0.features.0.name"]
    if "planning_prd.success_metrics" in edits:
        metrics = _split_interview_list(edits["planning_prd.success_metrics"])
        if metrics:
            brief.success_criteria = metrics
            brief.quality_bar = metrics[0]

    planning = build_product_planning_projection(
        brief.raw_idea,
        {
            "research_question": brief.research_question,
            "purpose": brief.purpose,
            "context": brief.context,
            "known": "; ".join(brief.known_facts),
            "deliverable_type": brief.deliverable_type,
            "quality_bar": brief.quality_bar,
        },
    )
    brief.planning_prd = planning["planning_prd"]
    brief.feature_hierarchy = planning["feature_hierarchy"]
    brief.user_flow = planning["user_flow"]
    if target_user:
        scenarios = brief.planning_prd.get("target_scenarios")
        if isinstance(scenarios, list) and scenarios and isinstance(scenarios[0], dict):
            scenarios[0]["user_group"] = target_user
        if brief.feature_hierarchy and isinstance(brief.feature_hierarchy[0], dict):
            features = brief.feature_hierarchy[0].get("features")
            if isinstance(features, list) and features and isinstance(features[0], dict):
                features[0]["user_role"] = target_user
    _apply_user_flow_label_edits(brief.user_flow, edits)
    brief.planning_review_policy = {
        **planning["planning_review_policy"],
        "mode": "plannotator_inline_edit",
        "applied_edit_count": len(edits),
    }
    return len(edits)


def _plan_review_edit_from_annotation(item: Any) -> tuple[str, str] | None:
    if not isinstance(item, dict):
        return None
    if str(item.get("type") or "").strip().lower() != "edit":
        return None
    source = str(item.get("source") or "").strip()
    if source not in PLAN_REVIEW_EDIT_SOURCES:
        return None
    target = str(item.get("target") or "").strip()
    if target not in PLAN_REVIEW_EDIT_TARGETS:
        return None
    for value_key in ("replacement", "value", "text"):
        value = item.get(value_key)
        if value is None:
            continue
        cleaned = str(value).strip()
        if cleaned:
            return target, cleaned
    return None


def _apply_user_flow_label_edits(user_flow: dict[str, Any], edits: dict[str, str]) -> None:
    target_to_node_id = {
        "user_flow.nodes.start.label": "start",
        "user_flow.nodes.questionnaire.label": "questionnaire",
        "user_flow.nodes.output.label": "output",
    }
    nodes = user_flow.get("nodes") if isinstance(user_flow, dict) else None
    if not isinstance(nodes, list):
        return
    for target, node_id in target_to_node_id.items():
        label = edits.get(target)
        if not label:
            continue
        for node in nodes:
            if isinstance(node, dict) and node.get("id") == node_id:
                node["label"] = label
                break


def _targeting_academic_sources(targeting_map: TargetingMap) -> list[str]:
    sources: list[str] = []
    for entries in (targeting_map.provenance or {}).values():
        if not isinstance(entries, list):
            continue
        for item in entries:
            if isinstance(item, dict) and item.get("source"):
                sources.append(str(item["source"]))
    return _dedupe_strings(sources) or ["none"]


def _report_limitations(*, require_live: bool, source_research: bool = False) -> list[str]:
    if require_live:
        return ["live run; source coverage, recency, and rate-limit gaps must be reviewed before external use"]
    if source_research:
        return [
            "source-backed research run with local/mock LLM synthesis; review source coverage before external use"
        ]
    return ["offline demonstration run; not suitable as source-backed product research"]


def _source_backed_open_questions(topic: str) -> list[str]:
    subject = topic.strip() or "해당 주제"
    return [
        f"{subject}에 대해 직접 근거가 있는 핵심 정의·범위·맥락을 우선 확인한다.",
        f"{subject}에 대한 주요 관점, 반례, 한계를 신뢰도 높은 출처로 교차 검증한다.",
        f"{subject}를 설명하거나 판단하기 위해 추가로 필요한 데이터·문헌·사례를 식별한다.",
    ]


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value).strip("-")


def _max_plus_benchmark_decision(metrics: dict[str, float]) -> str:
    expected_claim_recall = float(metrics.get("expected_claim_recall", 0.0) if metrics.get("expected_claim_recall") is not None else 0.0)
    evidence_quote_coverage = float(metrics.get("evidence_quote_coverage", 0.0) if metrics.get("evidence_quote_coverage") is not None else 0.0)
    weak_source_penalty = float(metrics.get("weak_source_penalty", 1.0) if metrics.get("weak_source_penalty") is not None else 1.0)
    if expected_claim_recall >= 0.5 and evidence_quote_coverage >= 0.5 and weak_source_penalty <= 0.5:
        return "keep"
    return "blocked"


def _research_quality_only_requested() -> bool:
    return os.environ.get("MUCHANIPO_RESEARCH_QUALITY_ONLY", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _evidence_validation_summary(
    evidence_store: EvidenceStore,
    grounding_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    base = evidence_store.summary()
    ratios = [
        float(report.get("verified_claim_ratio", 0.0))
        for report in grounding_reports
    ]
    verified_ratio = sum(ratios) / len(ratios) if ratios else 0.0
    unsupported = sum(1 for ratio in ratios if ratio < 1.0)
    return {
        **base,
        "verified_claim_ratio": round(verified_ratio, 4),
        "unsupported_finding_count": unsupported,
    }


def _research_runtime_artifacts(runner: Any, findings: list[Finding]) -> dict[str, Any]:
    backend_trace = [
        {
            "backend": str(item.get("backend") or "unknown"),
            "query": str(item.get("query") or ""),
            "status": str(item.get("status") or "unknown"),
            "count": int(item.get("count") or 0),
            **({"error": str(item.get("error"))} if item.get("error") else {}),
            **(
                {"autoresearch_iteration": int(item.get("autoresearch_iteration"))}
                if item.get("autoresearch_iteration") is not None
                else {}
            ),
            **(
                {"autoresearch_candidate_id": str(item.get("autoresearch_candidate_id"))}
                if item.get("autoresearch_candidate_id")
                else {}
            ),
            **(
                {
                    "autoresearch_candidate_description": str(
                        item.get("autoresearch_candidate_description")
                    )
                }
                if item.get("autoresearch_candidate_description")
                else {}
            ),
        }
        for item in getattr(runner, "last_backend_trace", []) or []
        if isinstance(item, dict)
    ]
    backend_kinds = _dedupe_strings([
        item["backend"]
        for item in backend_trace
        if item.get("backend")
    ])
    evidence_kinds = _dedupe_strings([
        str((ref.provenance or {}).get("kind") or "unknown")
        for finding in findings
        for ref in finding.support
    ])
    memory_trace = [
        item
        for item in backend_trace
        if item.get("backend") in {"vault", "insight_forge", "mempalace"}
    ]
    memory_evidence = any(kind in {"vault", "insight_forge", "mempalace"} for kind in evidence_kinds)
    if any(int(item.get("count") or 0) > 0 for item in memory_trace) or memory_evidence:
        memory_store = "MemPalace"
    elif any(item.get("status") == "error" for item in memory_trace):
        memory_store = "MemPalace:error"
    elif memory_trace:
        memory_store = "MemPalace:no_hits"
    else:
        memory_store = "not_executed"
    return {
        "runner_kind": type(runner).__name__,
        "backend_trace": backend_trace,
        "backend_kinds": backend_kinds or ["untraced"],
        "evidence_kinds": evidence_kinds or ["none"],
        "memory_store": memory_store,
    }


def _record_karpathy_autoresearch_artifacts(state: PipelineState, runner: Any) -> None:
    loop_result = getattr(runner, "last_loop_result", None)
    if loop_result is None:
        return
    payload = loop_result.to_dict() if hasattr(loop_result, "to_dict") else {}
    if not isinstance(payload, dict):
        return
    experiments = payload.get("experiments") if isinstance(payload.get("experiments"), list) else []
    state.record_artifact(
        "karpathy_autoresearch_runtime",
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
    )
    state.record_artifact("karpathy_autoresearch_source_revision", str(payload.get("source_revision") or "unknown"))
    state.record_artifact("karpathy_autoresearch_source_path", str(payload.get("source_path") or "unknown"))
    state.record_artifact("karpathy_autoresearch_program_path", str(payload.get("program_path") or ""))
    state.record_artifact("karpathy_autoresearch_results_path", str(payload.get("results_path") or ""))
    state.record_artifact("karpathy_autoresearch_metric", str(payload.get("metric_name") or ""))
    state.record_artifact("karpathy_autoresearch_metric_direction", str(payload.get("metric_direction") or ""))
    state.record_artifact("karpathy_autoresearch_iteration_count", str(len(experiments)))
    state.record_artifact("karpathy_autoresearch_best_iteration", str(payload.get("best_iteration") or 0))
    state.record_artifact(
        "karpathy_autoresearch_retained_count",
        str(payload.get("retained_iteration_count") or 0),
    )
    state.record_artifact(
        "karpathy_autoresearch_discarded_count",
        str(payload.get("discarded_iteration_count") or 0),
    )


def _claim_and_citation_verification_summaries(claim_evidence_summary: dict[str, Any]) -> dict[str, Any]:
    rows = claim_evidence_summary.get("rows") if isinstance(claim_evidence_summary.get("rows"), list) else []
    supporting_source_ids = {
        str(source_id)
        for row in rows
        if isinstance(row, dict)
        for source_id in row.get("supporting_source_ids", []) or []
        if str(source_id).strip()
    }
    canonical_ids = {
        str(canonical_id)
        for row in rows
        if isinstance(row, dict)
        for canonical_id in row.get("canonical_ids", []) or []
        if str(canonical_id).strip()
    }
    return {
        "claim_verification_summary": {
            "row_count": int(claim_evidence_summary.get("row_count") or 0),
            "supported_count": int(claim_evidence_summary.get("supported_count") or 0),
            "partial_count": int(claim_evidence_summary.get("partial_count") or 0),
            "unsupported_count": int(claim_evidence_summary.get("unsupported_count") or 0),
            "supported_ratio": float(claim_evidence_summary.get("supported_ratio") or 0.0),
            "passed": bool(claim_evidence_summary.get("passed")),
        },
        "citation_verification_summary": {
            "strict_citation_row_count": int(claim_evidence_summary.get("row_count") or 0),
            "supporting_source_count": len(supporting_source_ids),
            "canonical_id_count": len(canonical_ids),
        },
    }


def _route_progress_metadata(route: Any, *, route_id: str | None = None) -> dict[str, Any]:
    """Return JSON-safe route metadata for research_progress events.

    Missing route matches are explicit so downstream UI/audit code sees the
    routing gap instead of silently treating absent metadata as unavailable.
    """

    if not isinstance(route, dict) or not route:
        return {
            "route_id": route_id or "unrouted",
            "route_metadata_gap": True,
        }
    payload: dict[str, Any] = {
        "route_id": route.get("route_id") or route_id or "unrouted",
        "route_version": route.get("route_version"),
        "facet_id": route.get("facet_id"),
        "route_facet_id": route.get("facet_id"),
        "purpose": route.get("purpose"),
        "route_purpose": route.get("purpose"),
        "source_class": route.get("source_class"),
        "route_source_class": route.get("source_class"),
        "intent": route.get("intent"),
        "route_intent": route.get("intent"),
        "backend": route.get("backend"),
        "route_backend": route.get("backend"),
        "authority_requirement": route.get("authority_requirement"),
        "route_authority_requirement": route.get("authority_requirement"),
        "acceptance_rules": list(route.get("acceptance_rules") or []),
        "route_acceptance_rules": list(route.get("acceptance_rules") or []),
        "continue_reason": route.get("continue_reason"),
        "route_metadata_gap": False,
    }
    if route.get("reject_patterns"):
        payload["reject_patterns"] = list(route.get("reject_patterns") or [])
    return payload


def _research_backend_labels(runner: Any) -> list[str]:
    labels: list[str] = []
    for attr, label in (
        ("insight_forge_search", "InsightForge"),
        ("vault_search", "Local vault"),
        ("academic_search", "Academic APIs"),
        ("web_search", "Web search"),
        ("exa_search", "Exa"),
    ):
        if getattr(runner, attr, None) is not None:
            labels.append(label)
    if labels:
        return labels
    runner_name = runner.__class__.__name__.replace("ResearchRunner", "").strip()
    return [runner_name or "Research runner"]


def _dedupe_evidence_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    out: list[EvidenceRef] = []
    seen: set[str] = set()
    for ref in refs:
        if ref.id in seen:
            continue
        seen.add(ref.id)
        out.append(ref)
    return out


def _dedupe_strings(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _detect_offline_mode() -> bool:
    import shutil

    if os.environ.get("MUCHANIPO_OFFLINE", "").strip().lower() in ("1", "true", "yes"):
        return True
    if os.environ.get("MUCHANIPO_ONLINE", "").strip().lower() in ("1", "true", "yes"):
        return False

    true_values = ("1", "true", "yes", "on")
    running_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    explicit_cli_preference = os.environ.get("MUCHANIPO_PREFER_CLI")
    default_prefer_cli = "0" if running_pytest else "1"
    prefer_cli = os.environ.get("MUCHANIPO_PREFER_CLI", default_prefer_cli).strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    cli_global = os.environ.get("MUCHANIPO_USE_CLI", "").strip().lower() in true_values
    provider_cli_requested = any(
        os.environ.get(flag, "").strip().lower() in true_values
        for flag in ("ANTHROPIC_USE_CLI", "GEMINI_USE_CLI", "KIMI_USE_CLI", "CODEX_USE_CLI")
    )
    if running_pytest and explicit_cli_preference is None and not cli_global and not provider_cli_requested:
        return True
    cli_pairs = [
        ("ANTHROPIC_USE_CLI", "CLAUDE_BIN", "claude"),
        ("GEMINI_USE_CLI", "GEMINI_BIN", "gemini"),
        ("KIMI_USE_CLI", "KIMI_BIN", "kimi"),
        ("CODEX_USE_CLI", "CODEX_BIN", "codex"),
    ]
    for use_flag, bin_var, bin_name in cli_pairs:
        local_flag = os.environ.get(use_flag, "").strip().lower() in true_values
        if not (prefer_cli or cli_global or local_flag):
            continue
        explicit = os.environ.get(bin_var)
        if explicit and os.path.exists(explicit):
            return False
        if shutil.which(bin_name):
            return False

    for key in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "KIMI_API_KEY",
        "MOONSHOT_API_KEY",
        "XIAOMI_MIMO_API_KEY",
        "MIMO_API_KEY",
    ):
        if os.environ.get(key):
            return False
    return True


def _ontology_payload_from_stage_artifact(stage_artifact: Mapping[str, Any]) -> dict[str, Any]:
    for output in stage_artifact.get("outputs", []) or []:
        if isinstance(output, Mapping) and output.get("artifact_id") == "ontology_extraction":
            payload = output.get("payload")
            if isinstance(payload, Mapping):
                return dict(payload)
    raise ValueError("ontology_extraction stage artifact is missing ontology payload")


def _build_pipeline_ontology_extraction_artifact(
    *,
    topic: str,
    brief: ResearchBrief,
    report: ResearchReport,
    evidence_refs: list[EvidenceRef],
) -> dict[str, Any]:
    interview_turns: list[dict[str, Any]] = []
    for idx, turn in enumerate(getattr(brief, "interview_trace", []) or [], start=1):
        if isinstance(turn, Mapping):
            interview_turns.append(
                {
                    "turn_id": str(turn.get("id") or turn.get("turn_id") or f"interview:turn-{idx}"),
                    "question": str(turn.get("question") or ""),
                    "answer": str(turn.get("answer") or turn.get("response") or ""),
                    "source_ref": str(turn.get("source_ref") or f"interview:turn-{idx}"),
                }
            )
    if not interview_turns:
        interview_turns.append(
            {
                "turn_id": "brief:summary",
                "question": "canonical research brief",
                "answer": " ".join(
                    str(item)
                    for item in (
                        getattr(brief, "objective", ""),
                        getattr(brief, "audience", ""),
                        getattr(brief, "domain_boundary", ""),
                        getattr(brief, "decision_criteria", ""),
                    )
                    if str(item).strip()
                ),
                "source_ref": "brief:summary",
            }
        )
    source_fragments = [
        {
            "source_ref": "report:title",
            "text": str(getattr(report, "title", "") or topic),
        }
    ]
    source_fragments.extend(
        {
            "source_ref": str(getattr(ref, "id", "") or getattr(ref, "source_url", "") or f"evidence:{idx}"),
            "text": " ".join(
                str(value)
                for value in (
                    getattr(ref, "source_title", ""),
                    getattr(ref, "quote", ""),
                    getattr(ref, "snippet", ""),
                    getattr(ref, "source_url", ""),
                )
                if str(value).strip()
            ),
        }
        for idx, ref in enumerate(evidence_refs, start=1)
    )
    source_fragments.extend(
        {
            "source_ref": f"report:finding-{idx}",
            "text": str(getattr(finding, "claim", "") or ""),
        }
        for idx, finding in enumerate(getattr(report, "findings", []) or [], start=1)
    )
    manual_entities = [
        {
            "label": str(topic),
            "kind": "research_topic",
            "source_refs": ["topic:anchor"],
            "confidence": 0.76,
        },
        {
            "label": str(getattr(report, "title", "") or topic),
            "kind": "research",
            "source_refs": ["report:title", "topic:anchor"],
            "confidence": 0.74,
        },
    ]
    if getattr(brief, "audience", ""):
        manual_entities.append(
            {
                "label": str(getattr(brief, "audience")),
                "kind": "actor",
                "source_refs": ["brief:summary"],
                "confidence": 0.68,
            }
        )
    relations = [
        {
            "source": str(topic),
            "predicate": "scopes",
            "target": str(getattr(report, "title", "") or topic),
            "source_refs": ["topic:anchor", "report:title"],
            "confidence": 0.64,
        }
    ]
    if getattr(brief, "audience", ""):
        relations.append(
            {
                "source": str(getattr(brief, "audience")),
                "predicate": "evaluates",
                "target": str(getattr(report, "title", "") or topic),
                "source_refs": ["brief:summary"],
                "confidence": 0.62,
            }
        )
    return build_ontology_extraction_stage_artifact(
        OntologyExtractionArtifactInput(
            topic=topic,
            interview_turns=interview_turns,
            source_fragments=source_fragments,
            manual_entities=manual_entities,
            relations=relations,
        )
    )


def _ontology_entities_for_persona_generation(
    ontology_artifact: Mapping[str, Any] | None,
    *,
    topic: str,
) -> list[dict[str, Any]]:
    if not isinstance(ontology_artifact, Mapping):
        raise ValueError("persona generation requires canonical ontology_extraction artifact")
    if ontology_artifact.get("artifact_id") != "ontology_extraction":
        ontology_artifact = _ontology_payload_from_stage_artifact(ontology_artifact)
    if not ontology_artifact.get("consumable"):
        raise ValueError("ontology_extraction artifact is not consumable by downstream stages")
    entities: list[dict[str, Any]] = []
    for entity in ontology_artifact.get("entities", []) or []:
        if not isinstance(entity, Mapping) or entity.get("status") != "supported":
            continue
        entities.append(
            {
                "name": str(entity.get("label") or entity.get("normalized_id") or topic),
                "type": str(entity.get("kind") or "ontology_entity"),
                "summary": f"Source-grounded ontology entity {entity.get('normalized_id', '')}",
                "facts": [str(ref) for ref in entity.get("source_refs", []) or []],
                "attributes": {
                    "normalized_id": str(entity.get("normalized_id") or ""),
                    "aliases": list(entity.get("aliases", []) or []),
                    "uncertainty": entity.get("uncertainty"),
                    "status": str(entity.get("status") or ""),
                },
                "source": "ontology_extraction_artifact",
            }
        )
    if not entities:
        raise ValueError("ontology_extraction artifact has no supported entities for persona generation")
    return entities


def _generate_council_personas(
    *,
    report: ResearchReport,
    agents: list[DebateAgentSpec],
    gateway: GatewayV2,
    consensus_plan: ConsensusPlan,
    targeting_map: TargetingMap,
    depth_profile: ResearchDepthProfile,
    require_live: bool = False,
    progress_callback: Callable[[dict], None] | None = None,
    ontology_artifact: Mapping[str, Any] | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    consensus_ontology = consensus_plan.to_ontology()
    ontology_entities = _ontology_entities_for_persona_generation(
        ontology_artifact,
        topic=report.title,
    )
    base_value_axes = dict(
        consensus_ontology.get("value_axes") or {
            "time_horizon": "mid",
            "risk_tolerance": 0.35,
            "stakeholder_priority": ["primary", "secondary", "tertiary"],
            "innovation_orientation": 0.55,
        }
    )
    mirofish_drafts = _mirofish_entity_drafts(
        ontology_entities,
        topic=report.title,
        limit=max(1, min(len(ontology_entities), depth_profile.persona_pool_size // 4)),
        value_axes=base_value_axes,
    )
    ontology = {
        **consensus_ontology,
        "topic": report.title,
        "entities": ontology_entities,
        "roles": list(dict.fromkeys(
            list(consensus_ontology.get("roles", []))
            + [agent.role for agent in agents]
            + [draft.role for draft in mirofish_drafts]
        )) or ["evidence_reviewer"],
        "intents": list(consensus_ontology.get("intents", [])) + [
            agent.system_prompt or agent.perspective or "Evaluate topic-specific evidence."
            for agent in agents
        ] or ["Evaluate topic-specific evidence."],
        "allowed_tools": list(dict.fromkeys(
            list(consensus_ontology.get("allowed_tools", []))
            + ["model_gateway"]
        )),
        "required_outputs": ["council_round_response"],
        "value_axes": base_value_axes,
        "targeting_domains": list(targeting_map.domains),
    }
    generator = PersonaGenerator(
        gateway=_CouncilProviderProgressGateway(gateway, progress_callback)
        if progress_callback is not None
        else gateway
    )
    diversity_map = DiversityMap(
        bins_per_axis=_diversity_bins_for_pool(depth_profile.persona_pool_size)
    )
    mirofish_personas, mirofish_telemetry = generator.finalize_drafts(
        mirofish_drafts,
        ontology,
        target_count=len(mirofish_drafts),
        diversity_map=diversity_map,
        topic=report.title,
        allow_fallbacks=False,
        repair_duplicate_drafts=True,
        revision_notes=[
            "mirofish_ontology_entity_profile",
            "schema_grounded",
        ],
    )
    remaining_target = max(depth_profile.persona_pool_size - len(mirofish_personas), 0)
    seed_personas = None
    if _vertical_seed_personas_enabled() and not require_live:
        seed_personas = _korean_agtech_seed_personas(
            ontology=ontology,
            report=report,
            count=remaining_target,
        )
    generate_kwargs = {
        "target_count": remaining_target,
        "seed_personas": seed_personas,
        "diversity_map": diversity_map,
        "topic": report.title,
    }
    if "allow_fallbacks" in inspect.signature(generator.generate).parameters:
        generate_kwargs["allow_fallbacks"] = not require_live
    generated_personas, generated_telemetry = generator.generate(
        ontology,
        **generate_kwargs,
    )
    finals = (mirofish_personas + generated_personas)[: depth_profile.persona_pool_size]
    telemetry = _combine_persona_telemetry(
        mirofish_telemetry,
        generated_telemetry,
        diversity_map=diversity_map,
        persona_pool_size=len(finals),
        target_count=depth_profile.persona_pool_size,
    )
    persona_telemetry = _persona_generation_telemetry(
        finals,
        telemetry,
        depth_profile=depth_profile,
        ontology_entity_count=len(ontology_entities),
        mirofish_entity_persona_count=len(mirofish_drafts),
        mirofish_validated_entity_persona_count=len(mirofish_personas),
        diversity_map=diversity_map,
    )
    fallback_count = int(telemetry.get("fallbacks_used", 0) or 0)
    if require_live and fallback_count > 0:
        raise LiveModeViolation(
            f"live mode rejected fallback council personas: {fallback_count} generated"
        )
    if finals:
        return finals, persona_telemetry
    if require_live:
        raise LiveModeViolation("live mode requires generated council personas")
    return [debate_agent_to_council_persona(agent) for agent in agents], persona_telemetry


def _persona_generation_telemetry(
    personas: list[Any],
    telemetry: dict[str, Any],
    *,
    depth_profile: ResearchDepthProfile,
    ontology_entity_count: int,
    mirofish_entity_persona_count: int,
    mirofish_validated_entity_persona_count: int,
    diversity_map: DiversityMap,
) -> dict[str, Any]:
    seed_source = ""
    for persona in personas:
        manifest = getattr(persona, "manifest", {}) or {}
        grounded_seed = manifest.get("grounded_seed") if isinstance(manifest, dict) else None
        if isinstance(grounded_seed, dict) and grounded_seed.get("source"):
            seed_source = str(grounded_seed["source"])
            break
    return {
        "persona_seed_source": seed_source or "none",
        "ontology_entity_count": str(ontology_entity_count),
        "mirofish_entity_persona_count": str(mirofish_entity_persona_count),
        "mirofish_validated_entity_persona_count": str(
            mirofish_validated_entity_persona_count
        ),
        "persona_pool_size": str(len(personas)),
        "persona_pool_target_size": str(depth_profile.persona_pool_size),
        "active_persona_count": str(depth_profile.active_persona_count),
        "persona_validation_framework": "HACHIMI",
        "persona_diversity_framework": "MAP-Elites",
        "council_protocol": "OASIS / CAMEL-AI",
        "council_persona_strategy": "MiroFish ontology-derived pool with active sequential speakers",
        "persona_diversity_coverage": f"{float(telemetry.get('coverage_after_admit', 0.0) or 0.0):.4f}",
        "persona_diversity_bins_per_axis": str(diversity_map.bins_per_axis),
        "persona_fallbacks_used": str(int(telemetry.get("fallbacks_used", 0) or 0)),
    }


def _build_mirofish_ontology_entities(
    *,
    report: ResearchReport,
    agents: list[DebateAgentSpec],
    consensus_plan: ConsensusPlan,
    targeting_map: TargetingMap,
) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = [
        {
            "name": report.title,
            "type": "research",
            "summary": report.executive_summary,
            "facts": [finding.claim for finding in report.findings[:4]],
        }
    ]
    for domain in targeting_map.domains:
        entities.append({
            "name": domain,
            "type": "market",
            "summary": f"Targeting domain for {report.title}",
            "facts": targeting_map.search_queries.get(domain, [])[:4],
        })
    for institution in targeting_map.target_institutions[:6]:
        entities.append({
            "name": institution,
            "type": "organization",
            "summary": f"Candidate institution linked to {report.title}",
        })
    for journal in targeting_map.target_journals[:4]:
        entities.append({
            "name": journal,
            "type": "research",
            "summary": f"Candidate publication venue for {report.title}",
        })
    for agent in agents:
        entities.append({
            "name": agent.name,
            "type": "expert",
            "summary": agent.system_prompt or agent.perspective or agent.role,
            "attributes": {
                "role": agent.role,
                "expertise": ", ".join(agent.expertise),
            },
        })
    for role in consensus_plan.to_ontology().get("roles", []) or []:
        entities.append({
            "name": str(role),
            "type": "expert",
            "summary": f"Consensus-plan role for {report.title}",
        })
    return entities


def _combine_persona_telemetry(
    mirofish_telemetry: dict[str, Any],
    generated_telemetry: dict[str, Any],
    *,
    diversity_map: DiversityMap,
    persona_pool_size: int,
    target_count: int,
) -> dict[str, Any]:
    fast_failed_ids = list(mirofish_telemetry.get("fast_failed_ids", []) or [])
    fast_failed_ids.extend(generated_telemetry.get("fast_failed_ids", []) or [])
    deep_failed_ids = list(mirofish_telemetry.get("deep_failed_ids", []) or [])
    deep_failed_ids.extend(generated_telemetry.get("deep_failed_ids", []) or [])
    return {
        **generated_telemetry,
        "fast_failed_ids": fast_failed_ids,
        "deep_failed_ids": deep_failed_ids,
        "mirofish_fast_failed_ids": list(mirofish_telemetry.get("fast_failed_ids", []) or []),
        "mirofish_deep_failed_ids": list(mirofish_telemetry.get("deep_failed_ids", []) or []),
        "fallbacks_used": (
            int(mirofish_telemetry.get("fallbacks_used", 0) or 0)
            + int(generated_telemetry.get("fallbacks_used", 0) or 0)
        ),
        "coverage_after_admit": float(diversity_map.coverage()),
        "persona_pool_size": int(persona_pool_size),
        "target_count": int(target_count),
    }


def _mirofish_entity_drafts(
    entities: list[dict[str, Any]],
    *,
    topic: str,
    limit: int,
    value_axes: dict[str, Any],
) -> list[Draft]:
    if limit < 1 or not entities:
        return []
    try:
        runner = _load_council_runner_module()
        generate_from_entity = getattr(runner, "generate_persona_from_entity")
    except Exception:
        return []

    drafts: list[Draft] = []
    for index, entity in enumerate(entities[:limit], start=1):
        try:
            profile = generate_from_entity(entity, topic)
        except Exception:
            continue
        role = str(profile.get("role") or "ontology_reviewer")
        intent = str(profile.get("perspective_bias") or "Evaluate ontology-grounded evidence.")
        manifest = {
            "expertise": _list_of_strings(profile.get("expertise")),
            "argument_style": str(profile.get("argument_style") or ""),
            "entity_context": str(profile.get("entity_context") or ""),
            "entity_type": str(profile.get("entity_type") or entity.get("type") or ""),
            "mirofish_source": "generate_persona_from_entity",
            "debate_protocol": "OASIS / CAMEL-AI",
        }
        drafts.append(
            Draft(
                persona_id=f"mirofish-entity-{index:03d}",
                name=str(profile.get("name") or entity.get("name") or f"Entity {index}"),
                role=role,
                intent=intent,
                allowed_tools=["model_gateway"],
                required_outputs=["council_round_response"],
                value_axes=_distributed_value_axes(value_axes, index - 1, limit),
                manifest=manifest,
            )
        )
    return drafts


def _distributed_value_axes(
    base_value_axes: dict[str, Any],
    index: int,
    target_count: int,
) -> dict[str, Any]:
    axes = dict(base_value_axes)
    if target_count <= 1:
        return axes
    grid = max(2, int((target_count - 1) ** 0.5) + 1)
    row = index // grid
    col = index % grid
    axes["risk_tolerance"] = round((col + 0.5) / grid, 4)
    axes["innovation_orientation"] = round((row + 0.5) / grid, 4)
    return axes


def _list_of_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return []


def _vertical_seed_personas_enabled() -> bool:
    """Return true only when a caller explicitly opts into vertical seed personas.

    Muchanipo's core pipeline is a general-purpose research tool. Domain-specific
    persona seeds (for example, Korea AgTech/farmer samples) should not be
    inferred solely from topic keywords because they can override live LLM persona
    proposal and produce fallback-only council pools.
    """

    raw = os.getenv("MUCHANIPO_ENABLE_VERTICAL_SEED_PERSONAS", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _load_council_runner_module() -> Any:
    path = Path(__file__).resolve().parents[1] / "council" / "council-runner.py"
    spec = importlib.util.spec_from_file_location("src.council.council_runner_runtime", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load council runner from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _korean_agtech_seed_personas(
    *,
    ontology: dict[str, Any],
    report: ResearchReport,
    count: int,
) -> list[dict[str, Any]] | None:
    if count < 1:
        return None
    text = " ".join([
        report.title,
        report.executive_summary,
        " ".join(str(role) for role in ontology.get("roles", []) or []),
        " ".join(str(intent) for intent in ontology.get("intents", []) or []),
    ]).lower()
    ag_signals = ("agtech", "농가", "농업", "farmer", "agriculture", "agricultural")
    if not any(signal.lower() in text for signal in ag_signals):
        return None
    return KoreaPersonaSampler(
        data_path=Path("vault/personas/seeds/korea/agtech-farmers-sample500.jsonl"),
        seed=17,
    ).agtech_farmer_seed(count)


def _diversity_bins_for_pool(persona_pool_size: int) -> int:
    bins = 2
    while bins * bins < persona_pool_size:
        bins += 1
    return max(4, bins)
