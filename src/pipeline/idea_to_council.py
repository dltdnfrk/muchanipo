"""End-to-end mock-first Idea-to-Council pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict
from uuid import uuid4

from src.agents.generator import DebateAgentGenerator, DebateAgentSpec
from src.council.session import CouncilSession
from src.evidence.artifact import EvidenceRef, Finding
from src.evidence.store import EvidenceStore
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
    council: CouncilSession


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
        self.model_gateway = model_gateway or ModelGateway(provider=MockProvider(response="mock council critique"))
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

        state.advance(Stage.COUNCIL)
        self._emit(state, Stage.COUNCIL)
        council = CouncilSession(
            report_id=report.id,
            agents=agents,
            topic=brief.research_question,
            council_dir=self.council_log_dir / f"council-{report.id}",
            max_rounds=10,
        )
        for _round in range(10):
            council.run_round(model_gateway=self.model_gateway)
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
    council: CouncilSession,
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


def _round_digests(council: CouncilSession, evidence_refs: list[EvidenceRef]) -> list[RoundDigest]:
    evidence_ids = [ref.id for ref in evidence_refs]
    digests: list[RoundDigest] = []
    for idx in range(1, 11):
        round_record = council.rounds[idx - 1] if idx <= len(council.rounds) else {}
        results = list(round_record.get("results", []))
        first = results[0] if results else {}
        analysis = str(first.get("analysis") or round_record.get("consensus") or f"Round {idx} synthesis")
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
