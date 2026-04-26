"""End-to-end mock-first Idea-to-Council pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from src.agents.generator import DebateAgentGenerator, DebateAgentSpec
from src.council.session import CouncilSession
from src.execution.models import ModelGateway
from src.execution.providers.mock import MockProvider
from src.intake.normalizer import capture_idea
from src.interview.brief import ResearchBrief
from src.interview.session import InterviewSession
from src.research.planner import ResearchPlanner
from src.research.runner import MockResearchRunner
from src.report.schema import ResearchReport

from .stages import Stage
from .state import PipelineState


@dataclass
class IdeaToCouncilResult:
    state: PipelineState
    brief: ResearchBrief
    report: ResearchReport
    agents: list[DebateAgentSpec]
    council: CouncilSession


class IdeaToCouncilPipeline:
    def run(self, raw_idea: str) -> IdeaToCouncilResult:
        state = PipelineState(run_id=f"run-{uuid4()}")

        idea = capture_idea(raw_idea)
        state.advance(Stage.INTERVIEW)

        interview = InterviewSession.from_idea(idea)
        # Mock-first autopopulation: real UI can replace this with interactive Q/A.
        interview.answer("research_question", idea.raw_text)
        interview.answer("purpose", "decide next action")
        interview.answer("context", "muchanipo")
        interview.answer("deliverable_type", "research report")
        interview.answer("quality_bar", "evidence-backed and council-ready")
        brief = interview.to_brief()
        state.record_artifact("brief_id", brief.id)

        state.advance(Stage.RESEARCH)
        plan = ResearchPlanner().plan(brief)
        findings = MockResearchRunner().run(plan)

        state.advance(Stage.REPORT)
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

        state.advance(Stage.AGENTS)
        agents = DebateAgentGenerator().from_report(report)
        state.record_artifact("agents", ",".join(agent.name for agent in agents))

        state.advance(Stage.COUNCIL)
        council = CouncilSession(report_id=report.id, agents=agents)
        council.run_round(model_gateway=ModelGateway(provider=MockProvider(response="mock council critique")))
        state.record_artifact("council_id", report.id)
        state.advance(Stage.DONE)

        return IdeaToCouncilResult(state=state, brief=brief, report=report, agents=agents, council=council)
