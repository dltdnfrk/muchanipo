"""End-to-end mock-first Idea-to-Council pipeline."""
from __future__ import annotations

from dataclasses import dataclass
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
from src.evidence.store import EvidenceStore
from src.execution.gateway_v2 import GatewayV2, default_gateway
from src.execution.models import ModelGateway
from src.execution.providers.mock import MockProvider
from src.hitl.plannotator_adapter import HITLAdapter, HITLResult
from src.intake.normalizer import capture_idea
from src.interview.brief import ResearchBrief
from src.interview.session import InterviewSession
from src.research.planner import ResearchPlanner
from src.research.runner import MockResearchRunner
from src.report.chapter_mapper import ChapterMapper, RoundDigest
from src.report.pyramid_formatter import PyramidFormatter
from src.report.schema import ResearchReport
from src.targeting import TargetingMap
from src.targeting.builder import build_targeting_map

from .stages import Stage
from .state import PipelineState

ProgressCallback = Callable[[Dict[str, Any]], None]


@dataclass
class IdeaToCouncilResult:
    state: PipelineState
    brief: ResearchBrief
    targeting_map: TargetingMap
    evidence_refs: list[EvidenceRef]
    report: ResearchReport
    report_md: str
    vault_path: Path
    hitl_results: dict[str, HITLResult]
    progress_events: list[dict[str, Any]]
    agents: list[DebateAgentSpec]
    council: KarpathySession


class IdeaToCouncilPipeline:
    def __init__(
        self,
        *,
        hitl_adapter: HITLAdapter | None = None,
        research_runner: Any | None = None,
        model_gateway: ModelGateway | None = None,
        vault_dir: Path | str = Path("vault/insights"),
        council_log_dir: Path | str = Path("src/council/council-logs"),
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.hitl_adapter = hitl_adapter or HITLAdapter(timeout_seconds=0)
        self.research_runner = research_runner or MockResearchRunner()
        self.gateway_v2 = _coerce_gateway_v2(model_gateway)
        self.vault_dir = Path(vault_dir)
        self.council_log_dir = Path(council_log_dir)
        self.progress_callback = progress_callback
        self.progress_events: list[dict[str, Any]] = []

    def run(self, raw_idea: str) -> IdeaToCouncilResult:
        state = PipelineState(run_id=f"run-{uuid4()}")

        idea = capture_idea(raw_idea)
        self._emit(state, Stage.IDEA_DUMP)
        state.advance(Stage.INTERVIEW)
        self._emit(state, Stage.INTERVIEW)

        interview = InterviewSession.from_idea(idea)
        brief = self._brief_from_interview(interview, idea.raw_text)
        state.record_artifact("brief_id", brief.id)

        state.advance(Stage.TARGETING)
        targeting_map = build_targeting_map(brief)
        setattr(brief, "targeting_map", targeting_map)
        state.record_artifact("targeting_domains", ",".join(targeting_map.domains))
        self._emit(state, Stage.TARGETING)

        hitl_results: dict[str, HITLResult] = {}
        hitl_results["brief"] = self.hitl_adapter.gate_brief(brief)
        if hitl_results["brief"].status == "changes_requested":
            state.warnings.append("brief gate requested changes; re-interviewed once")
            interview = InterviewSession.from_idea(idea)
            brief = self._brief_from_interview(interview, idea.raw_text)
            targeting_map = build_targeting_map(brief)
            setattr(brief, "targeting_map", targeting_map)

        state.advance(Stage.RESEARCH)
        self._emit(state, Stage.RESEARCH)
        plan = ResearchPlanner().plan(brief)
        findings = list(self.research_runner.run(plan))

        state.advance(Stage.EVIDENCE)
        evidence_store = EvidenceStore()
        evidence_refs = [ev for finding in findings for ev in finding.support]
        for ref in evidence_refs:
            evidence_store.add(ref)
        state.record_artifact("evidence_count", str(len(evidence_refs)))
        self._emit(state, Stage.EVIDENCE)

        hitl_results["evidence"] = self.hitl_adapter.gate_evidence(evidence_refs)
        if hitl_results["evidence"].status == "changes_requested":
            state.warnings.append("evidence gate requested changes; augmented research once")
            findings = list(self.research_runner.run(plan))
            evidence_refs = [ev for finding in findings for ev in finding.support]

        report = ResearchReport(
            brief_id=brief.id,
            title=brief.research_question,
            executive_summary=f"Initial report for: {brief.research_question}",
            findings=findings,
            evidence_refs=evidence_refs,
            open_questions=["What evidence should be collected next?"],
            confidence=0.6,
            limitations=["mock-first skeleton; not a real autoresearch run yet"],
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
        self._emit(state, Stage.REPORT)

        hitl_results["report"] = self.hitl_adapter.gate_report(report_md)

        state.advance(Stage.VAULT)
        vault_path = self._save_to_vault(brief.id, report_md)
        state.record_artifact("vault_path", str(vault_path))
        self._emit(state, Stage.VAULT)

        state.advance(Stage.DONE)
        self._emit(state, Stage.DONE)

        return IdeaToCouncilResult(
            state=state,
            brief=brief,
            targeting_map=targeting_map,
            evidence_refs=evidence_refs,
            report=report,
            report_md=report_md,
            vault_path=vault_path,
            hitl_results=hitl_results,
            progress_events=list(self.progress_events),
            agents=agents,
            council=council,
        )

    def _brief_from_interview(self, interview: InterviewSession, raw_text: str) -> ResearchBrief:
        interview.answer("research_question", raw_text)
        interview.answer("purpose", "decide next action")
        interview.answer("context", "muchanipo")
        interview.answer("deliverable_type", "research report")
        interview.answer("quality_bar", "evidence-backed and council-ready")
        return interview.to_brief()

    def _emit(self, state: PipelineState, stage: Stage) -> None:
        event = {
            "run_id": state.run_id,
            "stage": stage.value,
            "artifacts": dict(state.artifacts),
        }
        self.progress_events.append(event)
        if self.progress_callback is not None:
            self.progress_callback(event)

    def _save_to_vault(self, brief_id: str, report_md: str) -> Path:
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        path = self.vault_dir / f"{brief_id}.md"
        path.write_text(report_md, encoding="utf-8")
        return path


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
        "## Evidence Index",
        "",
    ]
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


def _coerce_gateway_v2(model_gateway: ModelGateway | None) -> GatewayV2:
    if model_gateway is None:
        return default_gateway(force_offline=_detect_offline_mode())
    if isinstance(model_gateway, GatewayV2):
        return model_gateway

    provider = model_gateway.provider
    if provider is None and model_gateway.providers:
        provider = next(iter(model_gateway.providers.values()))
    if provider is None:
        provider = MockProvider(response="mock council critique")
    provider_name = getattr(provider, "name", provider.__class__.__name__)
    return GatewayV2(
        providers={provider_name: provider},
        stage_routes={"council": provider_name},
        fallback_chain={"council": [provider_name]},
        budget=model_gateway.budget,
        audit=model_gateway.audit,
    )


def _detect_offline_mode() -> bool:
    import os
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
