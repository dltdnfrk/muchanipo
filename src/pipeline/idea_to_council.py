"""End-to-end Idea-to-Council pipeline with offline and live-product modes."""
from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict
from uuid import uuid4

from src.agents.generator import DebateAgentGenerator, DebateAgentSpec
from src.agents.mirofish import debate_agent_to_council_persona
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
from src.interview.session import InterviewSession
from src.research.autoresearch_runtime import runtime_contract_for_profile
from src.research.depth import ResearchDepthProfile, depth_profile, normalize_depth
from src.research.planner import ResearchPlanner
from src.research.runner import MockResearchRunner, build_runner
from src.report.chapter_mapper import ChapterMapper, RoundDigest
from src.report.pyramid_formatter import PyramidFormatter
from src.report.schema import ResearchReport
from src.runtime.live_mode import (
    LiveModeViolation,
    assert_live_evidence,
    assert_live_hitl,
    assert_live_report,
    live_requested_from_env,
    require_live_mode,
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
    ) -> None:
        self.require_live = live_requested_from_env() if require_live is None else require_live
        self.depth = normalize_depth(depth)
        self.depth_profile = depth_profile(self.depth)
        self.hitl_adapter = hitl_adapter or HITLAdapter(timeout_seconds=0)
        self.research_runner = research_runner or build_runner(use_real=_use_real_research_from_env())
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

    def run(self, raw_idea: str) -> IdeaToCouncilResult:
        state = PipelineState(run_id=f"run-{uuid4()}")
        runtime_contract = runtime_contract_for_profile(self.depth_profile)
        state.record_artifact("research_depth", self.depth)
        state.record_artifact("research_depth_description", self.depth_profile.description)
        state.record_artifact("research_query_limit", str(self.depth_profile.query_limit))
        state.record_artifact("council_round_budget", str(self.depth_profile.council_round_budget))
        state.record_artifact("council_persona_pool_size", str(self.depth_profile.persona_pool_size))
        state.record_artifact("active_council_persona_count", str(self.depth_profile.active_persona_count))
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
        state.record_artifact("brief_id", brief.id)
        state.record_artifact("interview_question_count", str(len(getattr(brief, "interview_trace", []) or [])))
        state.record_artifact(
            "interview_question_order",
            ",".join(item["dimension_id"] for item in getattr(brief, "interview_trace", []) or []),
        )
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
            },
        )
        self._record_hitl_gate(state, "plan", hitl_results["plan"])
        self._require_approved_gate("plan", hitl_results["plan"])

        state.advance(Stage.TARGETING)
        targeting_map = build_targeting_map(brief)
        setattr(brief, "targeting_map", targeting_map)
        state.record_artifact("targeting_domains", ",".join(targeting_map.domains))
        state.record_artifact("targeting_academic_sources", ",".join(_targeting_academic_sources(targeting_map)))
        self._emit(state, Stage.TARGETING)

        hitl_results["brief"] = self.hitl_adapter.gate_brief(brief)
        self._record_hitl_gate(state, "brief", hitl_results["brief"])
        self._require_approved_gate("brief", hitl_results["brief"])
        if hitl_results["brief"].status == "changes_requested":
            state.warnings.append("brief gate requested changes; re-interviewed once")
            interview = InterviewSession.from_idea(idea)
            brief = self._brief_from_interview(interview, idea.raw_text, design_doc)
            targeting_map = build_targeting_map(brief)
            setattr(brief, "targeting_map", targeting_map)

        state.advance(Stage.RESEARCH)
        plan = ResearchPlanner().plan(brief, max_queries=self.depth_profile.query_limit)
        state.record_artifact("research_query_count", str(len(plan.queries)))
        state.record_artifact("research_collection_rules", json.dumps(plan.collection_rules, ensure_ascii=False))
        state.record_artifact("research_stop_conditions", json.dumps(plan.stop_conditions, ensure_ascii=False))
        findings = list(self.research_runner.run(plan))
        research_runtime = _research_runtime_artifacts(self.research_runner, findings)
        state.record_artifact("research_runner_kind", research_runtime["runner_kind"])
        state.record_artifact("research_backend_kinds", ",".join(research_runtime["backend_kinds"]))
        state.record_artifact("research_evidence_kinds", ",".join(research_runtime["evidence_kinds"]))
        state.record_artifact("research_backend_trace", json.dumps(research_runtime["backend_trace"], ensure_ascii=False, sort_keys=True))
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
            state.record_artifact("evidence_count", str(len(evidence_refs)))
            state.record_artifact("evidence_validation_summary", json.dumps(evidence_summary, ensure_ascii=False, sort_keys=True))
        self._emit(state, Stage.EVIDENCE)

        report = ResearchReport(
            brief_id=brief.id,
            title=brief.research_question,
            executive_summary=f"Initial report for: {brief.research_question}",
            findings=findings,
            evidence_refs=evidence_refs,
            open_questions=["What evidence should be collected next?"],
            confidence=0.6,
            limitations=_report_limitations(require_live=self.require_live),
        )
        state.record_artifact("report_id", report.id)

        agents = DebateAgentGenerator().from_report(report)
        state.record_artifact("agents", ",".join(agent.name for agent in agents))
        personas, persona_telemetry = _generate_council_personas(
            report=report,
            agents=agents,
            gateway=self.gateway_v2,
            consensus_plan=consensus_plan,
            targeting_map=targeting_map,
            depth_profile=self.depth_profile,
            require_live=self.require_live,
        )

        state.advance(Stage.COUNCIL)
        for key, value in persona_telemetry.items():
            state.record_artifact(key, str(value))
        council = KarpathySession(
            gateway=self.gateway_v2,
            layers=list(DEFAULT_LAYERS[: self.depth_profile.council_round_budget]),
            personas=personas,
            active_persona_count=self.depth_profile.active_persona_count,
        )
        council.run_all()
        state.record_artifact("council_id", report.id)
        state.record_artifact("council_turn_count", str(len(council.turn_transcript)))
        self._emit(state, Stage.COUNCIL)

        reference_runtime_artifacts = build_reference_runtime_artifacts(
            report=report,
            council=council,
            evidence_summary=evidence_summary,
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
            "gbrain_content_hash",
            str(reference_runtime_artifacts["gbrain"]["content_hash"]),
        )

        state.advance(Stage.REPORT)
        report_md = _compose_six_chapter_report(
            brief,
            report,
            council,
            targeting_map,
            evidence_summary=evidence_summary,
            reference_runtime_artifacts=reference_runtime_artifacts,
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
        answer_bank = {
            "research_question": design_doc.pain_root or raw_text,
            "purpose": design_doc.demand_reality or "decide next action",
            "context": design_doc.contrary_framing or design_doc.status_quo,
            "known": "; ".join(design_doc.implicit_capabilities) or "no prior facts provided",
            "deliverable_type": "research report",
            "quality_bar": "source-backed, council-ready, and scoped by OfficeHours forcing questions",
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
                }
            )
        brief = interview.to_brief()
        setattr(brief, "interview_trace", trace)
        brief.known_facts = list(design_doc.implicit_capabilities)
        brief.constraints = list(design_doc.challenged_premises)
        brief.success_criteria = [
            design_doc.narrowest_wedge,
            design_doc.future_fit,
        ]
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
        self.progress_events.append(event)
        if self.progress_callback is not None:
            self.progress_callback(event)

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
    require_live: bool = False,
) -> str:
    digests = _round_digests(council, report.evidence_refs, require_live=require_live)
    chapters = PyramidFormatter().reorder_all(ChapterMapper().map(digests))
    chapter_evidence = _chapter_evidence_map(digests, report.evidence_refs)
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
        lead_claim = _claim_with_evidence(chapter.lead_claim, evidence_ids)
        grounding_rows.append((chapter.chapter_no, chapter.lead_claim, evidence_ids))
        lines.extend([
            f"## Chapter {chapter.chapter_no}: {chapter.title}",
            "",
            lead_claim,
            "",
        ])
        for claim in chapter.body_claims:
            lines.append(f"- {_claim_with_evidence(claim, evidence_ids)}")
            grounding_rows.append((chapter.chapter_no, claim, evidence_ids))
        lines.append("")
    _append_claim_grounding_matrix(lines, grounding_rows)
    if reference_runtime_artifacts:
        _append_react_plan(lines, reference_runtime_artifacts.get("react", {}))
        _append_gbrain_snapshot(lines, reference_runtime_artifacts.get("gbrain", {}))
    return "\n".join(lines).strip() + "\n"


def _chapter_evidence_map(
    digests: list[RoundDigest],
    evidence_refs: list[EvidenceRef],
) -> dict[int, list[str]]:
    mapper = ChapterMapper()
    fallback_ids = [ref.id for ref in evidence_refs]
    out: dict[int, list[str]] = {}
    for digest in digests:
        chapter = mapper.layer_to_chapter.get(digest.layer_id.split("_", 1)[0])
        if chapter is None:
            continue
        ids = [evidence_id for evidence_id in digest.evidence_ref_ids if evidence_id]
        out.setdefault(chapter, [])
        out[chapter].extend(ids or fallback_ids)
    for chapter, ids in list(out.items()):
        out[chapter] = _dedupe_strings(ids)
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


def _claim_with_evidence(claim: str, evidence_ids: list[str]) -> str:
    cleaned = claim.strip()
    if not cleaned:
        cleaned = "추가 검증이 필요한 빈 주장"
    if not evidence_ids:
        return f"{cleaned} (Evidence: none)"
    refs = ", ".join(f"`{evidence_id}`" for evidence_id in evidence_ids)
    return f"{cleaned} (Evidence: {refs})"


def _append_claim_grounding_matrix(
    lines: list[str],
    grounding_rows: list[tuple[int, str, list[str]]],
) -> None:
    lines.extend([
        "## Claim Grounding Matrix",
        "",
        "| Chapter | Claim | Evidence |",
        "| --- | --- | --- |",
    ])
    for chapter_no, claim, evidence_ids in grounding_rows:
        evidence = ", ".join(f"`{evidence_id}`" for evidence_id in evidence_ids) if evidence_ids else "none"
        lines.append(f"| {chapter_no} | {_table_cell(claim)} | {evidence} |")
    lines.append("")


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


def _round_digests(
    council: KarpathySession,
    evidence_refs: list[EvidenceRef],
    *,
    require_live: bool = False,
) -> list[RoundDigest]:
    evidence_ids = [ref.id for ref in evidence_refs]
    digests: list[RoundDigest] = []
    for idx in range(1, 11):
        round_record = council.rounds[idx - 1] if idx <= len(council.rounds) else None
        if isinstance(round_record, RoundResult):
            digests.append(
                RoundDigest(
                    layer_id=round_record.layer_id,
                    chapter_title=round_record.chapter_title,
                    key_claim=round_record.key_claim,
                    body_claims=list(round_record.body_claims) or [round_record.key_claim],
                    evidence_ref_ids=list(round_record.evidence_ref_ids) or evidence_ids,
                    confidence=round_record.confidence_score,
                    framework=round_record.framework,
                )
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
        analysis = analysis or f"Round {idx} synthesis"
        key_points = [str(point) for point in first.get("key_points", []) if point]
        digests.append(
            RoundDigest(
                layer_id=f"L{idx}_fallback",
                chapter_title=f"Layer {idx}",
                key_claim=analysis,
                body_claims=key_points or [analysis],
                evidence_ref_ids=evidence_ids,
                confidence=float(first.get("confidence") or round_mapping.get("confidence") or 0.6),
            )
        )
    return digests


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


def _use_real_research_from_env() -> bool:
    return live_requested_from_env()


def _interview_answer_key(label: str) -> str:
    return {
        "deliverable": "deliverable_type",
        "quality": "quality_bar",
    }.get(label, label)


def _targeting_academic_sources(targeting_map: TargetingMap) -> list[str]:
    sources: list[str] = []
    for entries in (targeting_map.provenance or {}).values():
        if not isinstance(entries, list):
            continue
        for item in entries:
            if isinstance(item, dict) and item.get("source"):
                sources.append(str(item["source"]))
    return _dedupe_strings(sources) or ["none"]


def _report_limitations(*, require_live: bool) -> list[str]:
    if require_live:
        return ["live run; source coverage, recency, and rate-limit gaps must be reviewed before external use"]
    return ["offline demonstration run; not suitable as source-backed product research"]


def _safe_filename(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value).strip("-")


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
    ):
        if os.environ.get(key):
            return False
    return True


def _generate_council_personas(
    *,
    report: ResearchReport,
    agents: list[DebateAgentSpec],
    gateway: GatewayV2,
    consensus_plan: ConsensusPlan,
    targeting_map: TargetingMap,
    depth_profile: ResearchDepthProfile,
    require_live: bool = False,
) -> tuple[list[Any], dict[str, Any]]:
    consensus_ontology = consensus_plan.to_ontology()
    ontology_entities = _build_mirofish_ontology_entities(
        report=report,
        agents=agents,
        consensus_plan=consensus_plan,
        targeting_map=targeting_map,
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
    generator = PersonaGenerator(gateway=gateway)
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
        revision_notes=[
            "mirofish_ontology_entity_profile",
            "schema_grounded",
        ],
    )
    remaining_target = max(depth_profile.persona_pool_size - len(mirofish_personas), 0)
    seed_personas = _korean_agtech_seed_personas(
        ontology=ontology,
        report=report,
        count=remaining_target,
    )
    generated_personas, generated_telemetry = generator.generate(
        ontology,
        target_count=remaining_target,
        seed_personas=seed_personas,
        diversity_map=diversity_map,
        topic=report.title,
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
    agtech_signals = ("agtech", "농가", "농업", "딸기", "사과", "진단키트", "farmer", "orchard")
    if not any(signal.lower() in text for signal in agtech_signals):
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
