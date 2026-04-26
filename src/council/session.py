"""Council session for report-derived debate agents."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.agents.generator import DebateAgentSpec
from src.agents.mirofish import debate_agent_to_council_persona
from src.execution.models import ModelGateway


@dataclass
class CouncilSession:
    report_id: str
    agents: list[DebateAgentSpec]
    topic: str = ""
    council_id: str | None = None
    council_dir: Path | None = None
    max_rounds: int = 5
    research_type: str = "exploratory"
    rounds: list[dict] = field(default_factory=list)
    consensus: str | None = None
    disagreements: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    stopped: bool = False
    stop_reason: str | None = None

    def run_round(self, *, model_gateway: ModelGateway) -> dict:
        runner = _load_council_runner()
        personas = [debate_agent_to_council_persona(agent) for agent in self.agents]
        round_num = len(self.rounds) + 1
        council_dir = self._ensure_council_dir()

        if round_num == 1:
            prompt_paths = runner._generate_round1_prompts(
                self._topic(),
                personas,
                self._council_id(),
                council_dir,
                total_rounds=self.max_rounds,
                research_type=self.research_type,
            )
        else:
            prompt_paths = runner._generate_roundN_prompts(
                self._topic(),
                personas,
                self._council_id(),
                council_dir,
                round_num,
                self._previous_results(),
                total_rounds=self.max_rounds,
                research_type=self.research_type,
            )

        responses = []
        result_records = []
        for agent, persona, prompt_path in zip(self.agents, personas, prompt_paths):
            prompt = prompt_path.read_text(encoding="utf-8")
            result = model_gateway.call(stage="council", prompt=prompt)
            result_record = _model_result_to_round_record(
                self._council_id(), round_num, persona, result.text
            )
            _write_round_result(council_dir, round_num, persona, result_record)
            result_records.append(result_record)
            responses.append(
                {
                    "agent": agent.name,
                    "text": result.text,
                    "provider": result.provider,
                    "prompt_path": str(prompt_path),
                }
            )

        avg_confidence, consensus = runner._measure_consensus(result_records)
        round_record = {
            "round": round_num,
            "responses": responses,
            "results": result_records,
            "prompt_files": [str(path) for path in prompt_paths],
            "confidence": avg_confidence,
            "consensus": consensus,
        }
        self.rounds.append(round_record)
        self.consensus = consensus
        self.disagreements = self.disagreements or ["requires further evidence review"]
        self.next_actions = self.next_actions or ["convert council critique into next research iteration"]
        self._update_plateau_state(runner)
        return round_record

    def _topic(self) -> str:
        return self.topic or f"Research report {self.report_id}"

    def _council_id(self) -> str:
        if self.council_id is None:
            self.council_id = f"council-{self.report_id}"
        return self.council_id

    def _ensure_council_dir(self) -> Path:
        if self.council_dir is None:
            self.council_dir = Path("src/council/council-logs") / self._council_id()
        self.council_dir.mkdir(parents=True, exist_ok=True)
        meta_path = self.council_dir / "meta.json"
        if not meta_path.exists():
            import json

            meta = {
                "council_id": self._council_id(),
                "topic": self._topic(),
                "personas": [debate_agent_to_council_persona(agent) for agent in self.agents],
                "max_rounds": self.max_rounds,
                "research_type": self.research_type,
            }
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.council_dir

    def _previous_results(self) -> list[dict[str, Any]]:
        if not self.rounds:
            return []
        return list(self.rounds[-1].get("results", []))

    def _update_plateau_state(self, runner: Any) -> None:
        all_rounds = {
            int(round_record["round"]): list(round_record.get("results", []))
            for round_record in self.rounds
        }
        plateau, reason = runner._detect_plateau(all_rounds, window=3, tolerance=0.05)
        if plateau:
            self.stopped = True
            self.stop_reason = reason
            self.next_actions = ["finalize council report because confidence plateaued"]


def _load_council_runner() -> Any:
    import importlib.util

    path = Path(__file__).resolve().parent / "council-runner.py"
    spec = importlib.util.spec_from_file_location("src.council.council_runner_runtime", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load council runner from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _model_result_to_round_record(
    council_id: str,
    round_num: int,
    persona: dict[str, Any],
    text: str,
) -> dict[str, Any]:
    return {
        "council_id": council_id,
        "round": round_num,
        "persona": persona["name"],
        "role": persona["role"],
        "position": "조건부찬성",
        "analysis": text,
        "updated_analysis": text,
        "key_points": [text] if text else [],
        "concerns": [],
        "remaining_concerns": [],
        "evidence": [],
        "confidence": 0.6,
        "position_changed": False,
    }


def _write_round_result(
    council_dir: Path,
    round_num: int,
    persona: dict[str, Any],
    result: dict[str, Any],
) -> None:
    import json

    persona_slug = persona["name"].replace(" ", "_")
    path = council_dir / f"round-{round_num}-{persona_slug}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
