"""End-to-end Idea-to-Council pipeline with offline and live-product modes."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict
from uuid import uuid4

from src.agents.generator import DebateAgentGenerator, DebateAgentSpec
from src.agents.mirofish import debate_agent_to_council_persona
from src.council.parsers import RoundResult
from src.council.persona_generator import PersonaGenerator
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
    ) -> None:
        self.require_live = live_requested_from_env() if require_live is None else require_live
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

        idea = capture_idea(raw_idea)
        self._emit(state, Stage.IDEA_DUMP)
        state.advance(Stage.INTERVIEW)
        self._emit(state, Stage.INTERVIEW)

        interview = InterviewSession.from_idea(idea)
        design_doc = OfficeHours().reframe(idea.raw_text)
        brief = self._brief_from_interview(interview, idea.raw_text, design_doc)
        state.record_artifact("brief_id", brief.id)

        consensus_plan = PlanReview().autoplan(design_doc)
        state.record_artifact("plan_review_gate", "passed" if consensus_plan.gate_passed else "blocked")
        state.record_artifact("plan_review_consensus", f"{consensus_plan.consensus_score:.2f}")
        if self.require_live and (not consensus_plan.gate_passed or design_doc.aup_risk_score >= 0.7):
            raise LiveModeViolation(f"live mode blocked by plan review gate: {consensus_plan.gate_reason}")
        if not consensus_plan.gate_passed:
            state.warnings.append(f"plan review gate did not pass: {consensus_plan.gate_reason}")

        state.advance(Stage.TARGETING)
        targeting_map = build_targeting_map(brief)
        setattr(brief, "targeting_map", targeting_map)
        state.record_artifact("targeting_domains", ",".join(targeting_map.domains))
        self._emit(state, Stage.TARGETING)

        hitl_results: dict[str, HITLResult] = {}
        hitl_results["brief"] = self.hitl_adapter.gate_brief(brief)
        self._require_approved_gate("brief", hitl_results["brief"])
        if hitl_results["brief"].status == "changes_requested":
            state.warnings.append("brief gate requested changes; re-interviewed once")
            interview = InterviewSession.from_idea(idea)
            brief = self._brief_from_interview(interview, idea.raw_text, design_doc)
            targeting_map = build_targeting_map(brief)
            setattr(brief, "targeting_map", targeting_map)

        state.advance(Stage.RESEARCH)
        self._emit(state, Stage.RESEARCH)
        plan = ResearchPlanner().plan(brief)
        state.record_artifact("research_query_count", str(len(plan.queries)))
        findings = list(self.research_runner.run(plan))

        state.advance(Stage.EVIDENCE)
        evidence_store = EvidenceStore(require_live=self.require_live)
        evidence_refs = _dedupe_evidence_refs([ev for finding in findings for ev in finding.support])
        for ref in evidence_refs:
            evidence_store.add(ref)
        grounding_reports = annotate_findings(findings)
        evidence_summary = _evidence_validation_summary(evidence_store, grounding_reports)
        state.record_artifact("evidence_count", str(len(evidence_refs)))
        state.record_artifact("evidence_validation_summary", json.dumps(evidence_summary, ensure_ascii=False, sort_keys=True))
        self._emit(state, Stage.EVIDENCE)
        self._require_live_evidence(evidence_summary, evidence_refs)

        hitl_results["evidence"] = self.hitl_adapter.gate_evidence(evidence_refs)
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
        personas = _generate_council_personas(
            report=report,
            agents=agents,
            gateway=self.gateway_v2,
        )

        state.advance(Stage.COUNCIL)
        self._emit(state, Stage.COUNCIL)
        council = KarpathySession(
            gateway=self.gateway_v2,
            layers=list(DEFAULT_LAYERS),
            personas=personas,
        )
        council.run_all()
        state.record_artifact("council_id", report.id)

        state.advance(Stage.REPORT)
        report_md = _compose_six_chapter_report(brief, report, council, targeting_map)
        self._require_live_report(report_md)
        self._emit(state, Stage.REPORT)

        hitl_results["report"] = self.hitl_adapter.gate_report(report_md)
        self._require_approved_gate("report", hitl_results["report"])

        state.advance(Stage.VAULT)
        vault_path = self._save_to_vault(brief.id, report_md, run_id=state.run_id)
        state.record_artifact("vault_path", str(vault_path))
        retrospective = self._maybe_record_learning(report, council, evidence_summary)
        if retrospective is not None:
            state.record_artifact("learning_count", str(len(retrospective.learnings)))
        self._emit(state, Stage.VAULT)

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
            retrospective=retrospective,
        )

    def _require_approved_gate(self, gate_name: str, result: HITLResult) -> None:
        if self.require_live:
            assert_live_hitl(gate_name, result)

    def _require_live_evidence(self, evidence_summary: dict[str, Any], refs: list[EvidenceRef]) -> None:
        if self.require_live:
            assert_live_evidence(evidence_summary, refs)

    def _require_live_report(self, report_md: str) -> None:
        if self.require_live:
            assert_live_report(report_md)

    def _brief_from_interview(
        self,
        interview: InterviewSession,
        raw_text: str,
        design_doc: DesignDoc,
    ) -> ResearchBrief:
        interview.answer("research_question", design_doc.pain_root or raw_text)
        interview.answer("purpose", design_doc.demand_reality or "decide next action")
        interview.answer("context", design_doc.contrary_framing or design_doc.status_quo)
        interview.answer("deliverable_type", "research report")
        interview.answer(
            "quality_bar",
            "source-backed, council-ready, and scoped by OfficeHours forcing questions",
        )
        brief = interview.to_brief()
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
) -> str:
    digests = _round_digests(council, report.evidence_refs)
    chapters = PyramidFormatter().reorder_all(ChapterMapper().map(digests))
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
    for ref in report.evidence_refs:
        lines.append(f"- `{ref.id}` {ref.source_title or ref.source_url or ref.quote or ''}")
    lines.append("")

    for chapter in chapters:
        lines.extend([
            f"## Chapter {chapter.chapter_no}: {chapter.title}",
            "",
            chapter.lead_claim,
            "",
        ])
        for claim in chapter.body_claims:
            lines.append(f"- {claim}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _round_digests(council: KarpathySession, evidence_refs: list[EvidenceRef]) -> list[RoundDigest]:
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
        analysis = str(first.get("analysis") or round_mapping.get("consensus") or f"Round {idx} synthesis")
        key_points = [str(point) for point in first.get("key_points", []) if point]
        digests.append(
            RoundDigest(
                layer_id=f"L{idx}_mock",
                chapter_title=f"Layer {idx}",
                key_claim=analysis,
                body_claims=key_points or [analysis],
                evidence_ref_ids=evidence_ids,
                confidence=float(first.get("confidence") or round_record.get("confidence") or 0.6),
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


def _dedupe_evidence_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    out: list[EvidenceRef] = []
    seen: set[str] = set()
    for ref in refs:
        if ref.id in seen:
            continue
        seen.add(ref.id)
        out.append(ref)
    return out


def _detect_offline_mode() -> bool:
    import shutil

    if os.environ.get("MUCHANIPO_OFFLINE", "").strip().lower() in ("1", "true", "yes"):
        return True
    if os.environ.get("MUCHANIPO_ONLINE", "").strip().lower() in ("1", "true", "yes"):
        return False

    cli_global = os.environ.get("MUCHANIPO_USE_CLI", "").strip().lower() in ("1", "true", "yes")
    cli_pairs = [
        ("ANTHROPIC_USE_CLI", "CLAUDE_BIN", "claude"),
        ("GEMINI_USE_CLI", "GEMINI_BIN", "gemini"),
        ("CODEX_USE_CLI", "CODEX_BIN", "codex"),
    ]
    for use_flag, bin_var, bin_name in cli_pairs:
        local_flag = os.environ.get(use_flag, "").strip().lower() in ("1", "true", "yes")
        if not (cli_global or local_flag):
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
) -> list[Any]:
    ontology = {
        "topic": report.title,
        "roles": [agent.role for agent in agents] or ["evidence_reviewer"],
        "intents": [
            agent.system_prompt or agent.perspective or "Evaluate topic-specific evidence."
            for agent in agents
        ] or ["Evaluate topic-specific evidence."],
        "allowed_tools": ["model_gateway"],
        "required_outputs": ["council_round_response"],
        "value_axes": {
            "time_horizon": "mid",
            "risk_tolerance": 0.35,
            "stakeholder_priority": ["primary", "secondary", "tertiary"],
            "innovation_orientation": 0.55,
        },
    }
    finals, _telemetry = PersonaGenerator(gateway=gateway).generate(
        ontology,
        target_count=max(1, len(agents)),
        topic=report.title,
    )
    if finals:
        return finals
    return [debate_agent_to_council_persona(agent) for agent in agents]
