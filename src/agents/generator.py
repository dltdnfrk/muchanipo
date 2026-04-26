"""Generate debate agents from ResearchReport artifacts."""
from __future__ import annotations

from dataclasses import dataclass, field

from src.report.schema import ResearchReport

from .mirofish import MIROFISH_PROMPT
from .personas import DEFAULT_AGENT_ROLES
from .prompts import generic_agent_prompt


@dataclass
class DebateAgentSpec:
    name: str
    role: str
    perspective: str
    expertise: list[str] = field(default_factory=list)
    challenge_targets: list[str] = field(default_factory=list)
    source_report_id: str = ""
    system_prompt: str = ""


class DebateAgentGenerator:
    def from_report(self, report: ResearchReport) -> list[DebateAgentSpec]:
        agents: list[DebateAgentSpec] = []
        for name, role, perspective in DEFAULT_AGENT_ROLES:
            prompt = MIROFISH_PROMPT if name == "mirofish" else generic_agent_prompt(name, role)
            agents.append(
                DebateAgentSpec(
                    name=name,
                    role=role,
                    perspective=perspective,
                    expertise=[role, "research report review"],
                    challenge_targets=["findings", "evidence", "limitations"],
                    source_report_id=report.id,
                    system_prompt=prompt,
                )
            )
        return agents
