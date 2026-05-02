"""Clean-room OASIS/CAMEL-style council protocol trace.

Muchanipo does not vendor CAMEL-AI/OASIS runtime code. This module captures the
runtime behavior the stage needs: role-playing agents first reason
independently, then perform blinded peer review, then a chair synthesizes the
round with disagreement and next-action fields.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProtocolPhase:
    name: str
    actor: str
    visibility: str
    output_contract: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "actor": self.actor,
            "visibility": self.visibility,
            "output_contract": list(self.output_contract),
        }


OASIS_CAMEL_PHASES: tuple[ProtocolPhase, ...] = (
    ProtocolPhase(
        name="individual",
        actor="persona",
        visibility="private_to_persona",
        output_contract=("key_claim", "body_claims", "evidence_ref_ids", "confidence_score"),
    ),
    ProtocolPhase(
        name="peer_review",
        actor="persona",
        visibility="blinded_peer_claims",
        output_contract=("reviewer_id", "stance", "critique", "confidence_score"),
    ),
    ProtocolPhase(
        name="chairman",
        actor="chair",
        visibility="all_individual_and_peer_outputs",
        output_contract=("key_claim", "disagreements", "next_actions", "framework_output"),
    ),
)

OASIS_CAMEL_RUNTIME = "clean-room local social simulation protocol"


def build_protocol_trace(
    *,
    round_no: int,
    layer_id: str,
    active_persona_ids: list[str],
) -> dict[str, object]:
    if round_no < 1:
        raise ValueError("round_no must be >= 1")
    agent_states = _agent_states(active_persona_ids, layer_id=layer_id, round_no=round_no)
    interaction_events = _interaction_events(active_persona_ids, layer_id=layer_id, round_no=round_no)
    return {
        "protocol": "OASIS / CAMEL-AI",
        "runtime": OASIS_CAMEL_RUNTIME,
        "round": round_no,
        "layer_id": layer_id,
        "active_persona_ids": list(active_persona_ids),
        "phase_count": len(OASIS_CAMEL_PHASES),
        "phases": [phase.as_dict() for phase in OASIS_CAMEL_PHASES],
        "world_state": {
            "layer_id": layer_id,
            "round": round_no,
            "public_context": f"{layer_id} round {round_no} shared council context",
            "private_memory_enabled": True,
            "peer_review_graph": "round_robin_blinded",
        },
        "agent_states": agent_states,
        "interaction_events": interaction_events,
        "agent_memory_count": sum(len(agent["memory"]) for agent in agent_states),
        "interaction_count": len(interaction_events),
    }


def validate_protocol_trace(trace: dict[str, object]) -> bool:
    phases = trace.get("phases")
    if not isinstance(phases, list):
        return False
    names = [phase.get("name") for phase in phases if isinstance(phase, dict)]
    return (
        names == [phase.name for phase in OASIS_CAMEL_PHASES]
        and isinstance(trace.get("world_state"), dict)
        and isinstance(trace.get("agent_states"), list)
        and isinstance(trace.get("interaction_events"), list)
        and int(trace.get("agent_memory_count") or 0) >= len(trace.get("agent_states") or [])
    )


def _agent_states(
    active_persona_ids: list[str],
    *,
    layer_id: str,
    round_no: int,
) -> list[dict[str, object]]:
    states: list[dict[str, object]] = []
    for index, persona_id in enumerate(active_persona_ids):
        states.append(
            {
                "persona_id": persona_id,
                "profile_slot": index,
                "goals": [
                    f"analyze {layer_id}",
                    "challenge unsupported assumptions",
                    "preserve evidence-linked reasoning",
                ],
                "memory": [
                    f"round:{round_no}",
                    f"layer:{layer_id}",
                    "private_individual_analysis_before_peer_review",
                ],
                "allowed_actions": ["individual_analysis", "peer_review", "chair_signal"],
            }
        )
    return states


def _interaction_events(
    active_persona_ids: list[str],
    *,
    layer_id: str,
    round_no: int,
) -> list[dict[str, object]]:
    if not active_persona_ids:
        return []
    events: list[dict[str, object]] = []
    for index, persona_id in enumerate(active_persona_ids):
        target = (
            active_persona_ids[(index + 1) % len(active_persona_ids)]
            if len(active_persona_ids) > 1
            else "chair"
        )
        events.append(
            {
                "round": round_no,
                "layer_id": layer_id,
                "actor": persona_id,
                "target": target,
                "action": "blinded_peer_review",
                "visibility": "anonymous_to_target_until_chairman",
            }
        )
    events.append(
        {
            "round": round_no,
            "layer_id": layer_id,
            "actor": "chair",
            "target": "all",
            "action": "synthesize_world_state",
            "visibility": "public_to_council",
        }
    )
    return events
