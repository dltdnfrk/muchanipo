"""Council session skeleton for report-derived debate agents."""
from __future__ import annotations

from dataclasses import dataclass, field

from src.agents.generator import DebateAgentSpec
from src.execution.models import ModelGateway


@dataclass
class CouncilSession:
    report_id: str
    agents: list[DebateAgentSpec]
    rounds: list[dict] = field(default_factory=list)
    consensus: str | None = None
    disagreements: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)

    def run_round(self, *, model_gateway: ModelGateway) -> dict:
        responses = []
        for agent in self.agents:
            result = model_gateway.call(stage="council", prompt=agent.system_prompt)
            responses.append({"agent": agent.name, "text": result.text, "provider": result.provider})
        round_record = {"round": len(self.rounds) + 1, "responses": responses}
        self.rounds.append(round_record)
        self.consensus = self.consensus or "initial council round complete"
        self.disagreements = self.disagreements or ["requires further evidence review"]
        self.next_actions = self.next_actions or ["convert council critique into next research iteration"]
        return round_record
