"""Council session for report-derived debate agents."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.agents.generator import DebateAgentSpec
from src.agents.mirofish import debate_agent_to_council_persona
from src.council.karpathy_prompts import (
    build_chairman_prompt,
    build_individual_prompt,
    build_peer_review_prompt,
)
from src.council.parsers import RoundResult, parse_council_response
from src.council.round_layers import RoundLayer
from src.execution.gateway_v2 import GatewayV2
from src.execution.models import ModelGateway


@dataclass(frozen=True)
class IndividualOpinion:
    persona_id: str
    key_claim: str
    body_claims: list[str] = field(default_factory=list)
    evidence_ref_ids: list[str] = field(default_factory=list)
    confidence_score: float = 0.0
    raw_response: str = ""


@dataclass(frozen=True)
class PeerComment:
    reviewer_id: str
    text: str
    stance: str = ""
    confidence_score: float = 0.0
    raw_response: str = ""


@dataclass
class PlateauDetector:
    """Detect confidence plateaus across structured council rounds."""

    window: int = 3
    tolerance: float = 0.05

    def should_stop(self, rounds: list[RoundResult]) -> tuple[bool, str]:
        if len(rounds) < self.window:
            return False, f"plateau check skipped: only {len(rounds)} rounds"

        recent = rounds[-self.window :]
        round_ids = [round_result.layer_id for round_result in recent]
        if len(set(round_ids)) != 1:
            return False, (
                f"plateau check skipped across mandatory layers {round_ids}: "
                "only repeated deliberation of the same layer can stop early"
            )

        confidences = [round_result.confidence_score for round_result in recent]
        spread = max(confidences) - min(confidences)
        if spread <= self.tolerance:
            return True, (
                f"plateau detected over {round_ids}: confidence spread "
                f"{spread:.3f} <= {self.tolerance:.2f}"
            )
        return False, (
            f"no plateau over {round_ids}: confidence spread "
            f"{spread:.3f} > {self.tolerance:.2f}"
        )


class Session:
    """Run the 10-layer council through GatewayV2 and parse structured results."""

    def __init__(
        self,
        gateway: GatewayV2,
        layers: list[RoundLayer],
        personas: list[Any],
        plateau: PlateauDetector | None = None,
        active_persona_count: int | None = None,
    ) -> None:
        self.gateway = gateway
        self.layers = list(layers)
        self.personas = list(personas)
        self.plateau = plateau or PlateauDetector(window=11, tolerance=0.05)
        if active_persona_count is not None and active_persona_count < 1:
            raise ValueError("active_persona_count must be >= 1")
        self.active_persona_count = active_persona_count
        self.rounds: list[RoundResult] = []
        self.turn_transcript: list[dict[str, Any]] = []
        self.active_persona_ids_by_round: dict[int, list[str]] = {}
        self.stopped = False
        self.stop_reason: str | None = None

    def run_one_round(self, round_no: int) -> RoundResult:
        if round_no < 1:
            raise ValueError("round_no must be >= 1")
        if round_no > len(self.layers):
            raise ValueError(f"round_no {round_no} exceeds configured layers ({len(self.layers)})")

        layer = self.layers[round_no - 1]
        active_personas = self._active_personas_for_round(round_no, layer)
        self.active_persona_ids_by_round[round_no] = [
            _persona_id(persona, idx)
            for idx, persona in enumerate(active_personas, start=1)
        ]
        individuals = self._individual_stage(layer, active_personas, round_no)
        peer_reviews = self._peer_review_stage(individuals, layer, active_personas, round_no)
        round_result = self._chairman_synthesis(individuals, peer_reviews, layer)
        self.rounds.append(round_result)

        plateau, reason = self.plateau.should_stop(self.rounds)
        self.stop_reason = reason
        if plateau:
            self.stopped = True
        return round_result

    def run_all(self, allow_early_stop: bool = False) -> list[RoundResult]:
        max_rounds = min(10, len(self.layers))
        for round_no in range(1, max_rounds + 1):
            if allow_early_stop and self.stopped:
                break
            self.run_one_round(round_no)
        return list(self.rounds)

    def _active_personas_for_round(
        self,
        round_no: int,
        layer: RoundLayer,
    ) -> list[Any]:
        if not self.personas:
            return []
        limit = self.active_persona_count or len(self.personas)
        if limit >= len(self.personas):
            return list(self.personas)

        offset = ((round_no - 1) * limit) % len(self.personas)
        rotated = self.personas[offset:] + self.personas[:offset]
        selected: list[Any] = []
        emphasis_budget = max(1, limit // 3)
        emphasized = sorted(
            [persona for persona in self.personas if _persona_layer_score(persona, layer) > 0],
            key=lambda persona: _persona_layer_score(persona, layer),
            reverse=True,
        )
        for persona in emphasized[:emphasis_budget]:
            if persona not in selected:
                selected.append(persona)
            if len(selected) >= limit:
                return selected

        for persona in rotated:
            if persona in selected:
                continue
            selected.append(persona)
            if len(selected) >= limit:
                return selected
        return selected

    def _individual_stage(
        self,
        layer: RoundLayer,
        personas: list[Any],
        round_no: int,
    ) -> dict[str, IndividualOpinion]:
        prev_summary = _previous_summary(self.rounds)
        opinions: dict[str, IndividualOpinion] = {}
        for idx, persona in enumerate(personas, start=1):
            persona_id = _persona_id(persona, idx)
            prompt = build_individual_prompt(persona, layer, prev_summary)
            result = self.gateway.call("council", prompt, council_stage="individual", layer_id=layer.layer_id)
            self._record_turn(round_no, layer, "individual", persona_id, prompt, result)
            parsed = parse_council_response(getattr(result, "text", str(result)), layer)
            opinions[persona_id] = IndividualOpinion(
                persona_id=persona_id,
                key_claim=parsed.key_claim,
                body_claims=list(parsed.body_claims),
                evidence_ref_ids=list(parsed.evidence_ref_ids),
                confidence_score=parsed.confidence_score,
                raw_response=getattr(result, "text", str(result)),
            )
        return opinions

    def _peer_review_stage(
        self,
        individuals: dict[str, IndividualOpinion],
        layer: RoundLayer,
        personas: list[Any],
        round_no: int,
    ) -> dict[str, list[PeerComment]]:
        reviews: dict[str, list[PeerComment]] = {}
        for idx, persona in enumerate(personas, start=1):
            persona_id = _persona_id(persona, idx)
            blinded = [
                {
                    "key_claim": opinion.key_claim,
                    "body_claims": list(opinion.body_claims),
                    "confidence_score": opinion.confidence_score,
                }
                for other_id, opinion in individuals.items()
                if other_id != persona_id
            ]
            prompt = build_peer_review_prompt(persona, blinded, layer)
            result = self.gateway.call("council", prompt, council_stage="peer_review", layer_id=layer.layer_id)
            self._record_turn(round_no, layer, "peer_review", persona_id, prompt, result)
            text = getattr(result, "text", str(result))
            reviews[persona_id] = [_parse_peer_comment(persona_id, text)]
        return reviews

    def _chairman_synthesis(
        self,
        individuals: dict[str, IndividualOpinion],
        peer_reviews: dict[str, list[PeerComment]],
        layer: RoundLayer,
    ) -> RoundResult:
        prompt = build_chairman_prompt(individuals, peer_reviews, layer)
        result = self.gateway.call("council", prompt, council_stage="chairman", layer_id=layer.layer_id)
        self._record_turn(len(self.rounds) + 1, layer, "chairman", "chairman", prompt, result)
        text = getattr(result, "text", str(result)) if result else _fallback_chairman_json(individuals, peer_reviews)
        parsed = parse_council_response(text, layer)
        if not parsed.disagreements:
            parsed = RoundResult(
                layer_id=parsed.layer_id,
                chapter_title=parsed.chapter_title,
                key_claim=parsed.key_claim,
                body_claims=list(parsed.body_claims),
                evidence_ref_ids=list(parsed.evidence_ref_ids),
                confidence_score=parsed.confidence_score,
                framework=parsed.framework,
                disagreements=_derive_disagreements(peer_reviews),
                next_actions=list(parsed.next_actions),
                raw_response=parsed.raw_response,
                framework_output=parsed.framework_output,
            )
        return parsed

    def _record_turn(
        self,
        round_no: int,
        layer: RoundLayer,
        stage: str,
        persona_id: str,
        prompt: str,
        result: Any,
    ) -> None:
        self.turn_transcript.append(
            {
                "round": round_no,
                "layer_id": layer.layer_id,
                "stage": stage,
                "persona_id": persona_id,
                "provider": str(getattr(result, "provider", "")),
                "prompt_chars": len(prompt),
                "response_chars": len(getattr(result, "text", str(result)) if result else ""),
            }
        )


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


def _persona_id(persona: Any, idx: int) -> str:
    if isinstance(persona, dict):
        return str(persona.get("persona_id") or persona.get("name") or f"persona-{idx}")
    return str(
        getattr(persona, "persona_id", None)
        or getattr(persona, "name", None)
        or f"persona-{idx}"
    )


def _persona_layer_score(persona: Any, layer: RoundLayer) -> int:
    text_parts: list[str] = []
    if isinstance(persona, dict):
        text_parts.extend([
            str(persona.get("name", "")),
            str(persona.get("role", "")),
            " ".join(str(item) for item in persona.get("expertise", []) or []),
        ])
        manifest = persona.get("manifest") or persona.get("agent_manifest") or {}
        if isinstance(manifest, dict):
            text_parts.append(" ".join(str(value) for value in manifest.values()))
    else:
        text_parts.extend([
            str(getattr(persona, "name", "")),
            str(getattr(persona, "role", "")),
        ])
        manifest = getattr(persona, "manifest", {}) or {}
        if isinstance(manifest, dict):
            text_parts.append(" ".join(str(value) for value in manifest.values()))

    haystack = " ".join(text_parts).casefold().replace("_", " ")
    score = 0
    for role in layer.emphasis_roles:
        needle = str(role).casefold().replace("_", " ")
        if needle and needle in haystack:
            score += 1
    return score


def _previous_summary(rounds: list[RoundResult]) -> str:
    if not rounds:
        return ""
    return "\n".join(
        f"- {round_result.layer_id}: {round_result.key_claim}"
        for round_result in rounds[-3:]
    )


def _parse_peer_comment(reviewer_id: str, text: str) -> PeerComment:
    import json

    stripped = text.strip()
    payload: Any = None
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
    if isinstance(payload, dict):
        critiques = payload.get("critiques") or payload.get("critique") or payload.get("suggested_revision")
        if isinstance(critiques, list):
            comment_text = "; ".join(str(item) for item in critiques if item)
        else:
            comment_text = str(critiques or payload.get("stance") or stripped)
        return PeerComment(
            reviewer_id=reviewer_id,
            text=comment_text,
            stance=str(payload.get("stance") or ""),
            confidence_score=_coerce_float(payload.get("confidence_score"), default=0.0),
            raw_response=text,
        )
    return PeerComment(reviewer_id=reviewer_id, text=stripped, raw_response=text)


def _derive_disagreements(peer_reviews: dict[str, list[PeerComment]]) -> list[str]:
    disagreements = [
        comment.text
        for comments in peer_reviews.values()
        for comment in comments
        if any(token in comment.text.lower() for token in ("disagree", "불일치", "risk", "리스크", "critique"))
    ]
    return disagreements or ["chairman synthesis found no explicit disagreement"]


def _fallback_chairman_json(
    individuals: dict[str, IndividualOpinion],
    peer_reviews: dict[str, list[PeerComment]],
) -> str:
    import json

    claims = [opinion.key_claim for opinion in individuals.values() if opinion.key_claim]
    comments = [
        comment.text
        for values in peer_reviews.values()
        for comment in values
        if comment.text
    ]
    return json.dumps(
        {
            "key_claim": claims[0] if claims else "Chairman synthesis unavailable",
            "body_claims": claims[1:] + comments,
            "confidence_score": 0.5,
            "disagreements": comments[:3],
            "next_actions": ["verify chairman synthesis with evidence"],
        },
        ensure_ascii=False,
    )


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
