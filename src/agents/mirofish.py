"""Mirofish debate agent profile, persona adapters, and runtime records."""
from __future__ import annotations

from typing import Any, Mapping

MIROFISH_PROMPT = """You are mirofish, a rigorous critique agent.
Read the research report and identify weak assumptions, missing evidence,
counter-hypotheses, citation gaps, and concrete next experiments.
Do not merely disagree; produce actionable pressure tests.
"""

MIROFISH_WORKFLOW_PHASES = (
    "graph_building",
    "environment_setup",
    "simulation",
    "report_generation",
    "deep_interaction",
)


def debate_agent_to_council_persona(agent: Any) -> dict[str, Any]:
    """Convert a DebateAgentSpec-like object to council-runner persona schema."""
    name = str(getattr(agent, "name", "") or "debate-agent")
    role = str(getattr(agent, "role", "") or "council reviewer")
    perspective = str(getattr(agent, "perspective", "") or "balanced")
    expertise = list(getattr(agent, "expertise", None) or [role, "research review"])
    challenge_targets = list(getattr(agent, "challenge_targets", None) or [])

    return {
        "name": name,
        "role": role,
        "expertise": [str(item) for item in expertise],
        "perspective_bias": perspective,
        "argument_style": _argument_style(role, challenge_targets),
        "source_report_id": str(getattr(agent, "source_report_id", "") or ""),
        "agent_manifest": {
            "intent": str(getattr(agent, "system_prompt", "") or perspective),
            "allowed_tools": ["model_gateway"],
            "required_outputs": ["council_round_response"],
            "challenge_targets": [str(item) for item in challenge_targets],
        },
    }


def council_persona_to_agent_fields(persona: Mapping[str, Any]) -> dict[str, Any]:
    """Map a council persona dict back to DebateAgentSpec constructor fields."""
    return {
        "name": str(persona.get("name", "debate-agent")),
        "role": str(persona.get("role", "council reviewer")),
        "perspective": str(persona.get("perspective_bias", "balanced")),
        "expertise": [str(item) for item in persona.get("expertise", [])],
        "challenge_targets": [str(item) for item in persona.get("challenge_targets", [])],
        "system_prompt": str(persona.get("system_prompt", "")),
    }


def build_mirofish_runtime_record(*, report: Any, council: Any) -> dict[str, Any]:
    """Build the local MiroFish-style runtime record for a council run.

    MiroFish upstream is an AGPL swarm-simulation app. Muchanipo keeps a local
    runtime adaptation instead of vendoring more AGPL code: evidence and report
    state become the seed graph, personas become world agents, council turns are
    the simulation event stream, and the report/council transcript is the
    report-agent/deep-interaction surface.
    """
    topic = str(getattr(report, "title", "") or "")
    evidence_refs = list(getattr(report, "evidence_refs", []) or [])
    personas = list(getattr(council, "personas", []) or [])
    turns = list(getattr(council, "turn_transcript", []) or [])
    rounds = list(getattr(council, "rounds", []) or [])
    world_nodes = _world_nodes(topic=topic, evidence_refs=evidence_refs, personas=personas)
    world_edges = _world_edges(world_nodes=world_nodes, turns=turns)
    simulation_events = _simulation_events(turns)
    record = {
        "runtime": "local MiroFish-style swarm simulation runtime",
        "upstream": {
            "source_url": "https://github.com/666ghj/MiroFish",
            "license": "AGPL-3.0",
            "port_type": "local clean-room workflow adaptation; do not copy more upstream code without AGPL review",
        },
        "workflow_phases": list(MIROFISH_WORKFLOW_PHASES),
        "graph_building": {
            "seed_topic": topic,
            "seed_material_count": len(evidence_refs),
            "world_node_count": len(world_nodes),
            "world_edge_count": len(world_edges),
            "nodes": world_nodes,
            "edges": world_edges,
        },
        "environment_setup": {
            "agent_count": len(personas),
            "agents": [_agent_state(persona, idx) for idx, persona in enumerate(personas, start=1)],
            "memory_injection_count": len(evidence_refs) * max(1, len(personas)),
        },
        "simulation": {
            "round_count": len(rounds),
            "turn_count": len(turns),
            "events": simulation_events,
            "temporal_memory_updates": _temporal_memory_updates(simulation_events),
        },
        "report_generation": {
            "report_id": str(getattr(report, "id", "") or ""),
            "title": topic,
            "confidence": float(getattr(report, "confidence", 0.0) or 0.0),
            "round_synthesis_count": len(rounds),
            "report_agent_ready": bool(rounds and evidence_refs),
        },
        "deep_interaction": {
            "available_agent_count": len(personas),
            "transcript_turn_count": len(turns),
            "surfaces": ["agent_transcript", "report_agent_context", "persona_memory"],
            "ready": bool(personas and turns),
        },
    }
    record["valid"] = validate_mirofish_runtime_record(record)
    return record


def validate_mirofish_runtime_record(record: Mapping[str, Any]) -> bool:
    """Return True when all local MiroFish workflow phases have runtime evidence."""
    if list(record.get("workflow_phases") or []) != list(MIROFISH_WORKFLOW_PHASES):
        return False
    graph = record.get("graph_building")
    environment = record.get("environment_setup")
    simulation = record.get("simulation")
    report_generation = record.get("report_generation")
    interaction = record.get("deep_interaction")
    if not all(isinstance(item, Mapping) for item in [graph, environment, simulation, report_generation, interaction]):
        return False
    if int(graph.get("world_node_count") or 0) < 2 or int(graph.get("world_edge_count") or 0) < 1:
        return False
    if int(environment.get("agent_count") or 0) < 1:
        return False
    if int(simulation.get("turn_count") or 0) < 1:
        return False
    if not bool(report_generation.get("report_agent_ready")):
        return False
    return bool(interaction.get("ready"))


def _argument_style(role: str, challenge_targets: list[Any]) -> str:
    targets = ", ".join(str(item) for item in challenge_targets[:3])
    if "critic" in role or "skeptic" in role:
        base = "skeptical, evidence-first, pressure-tests weak assumptions"
    elif "auditor" in role:
        base = "source-grounded, traceability-first, flags unsupported claims"
    elif "implementation" in role or "builder" in role:
        base = "pragmatic, execution-focused, converts gaps into next actions"
    else:
        base = "balanced, domain-aware, compares claims against available evidence"
    return f"{base}; targets: {targets}" if targets else base


def _world_nodes(*, topic: str, evidence_refs: list[Any], personas: list[Any]) -> list[dict[str, Any]]:
    nodes = [
        {
            "id": "seed:topic",
            "type": "seed_material",
            "label": topic,
        }
    ]
    for ref in evidence_refs:
        ref_id = str(getattr(ref, "id", "") or getattr(ref, "source_url", "") or len(nodes))
        nodes.append(
            {
                "id": f"evidence:{ref_id}",
                "type": "evidence",
                "label": str(getattr(ref, "source_title", "") or getattr(ref, "source_url", "") or ref_id),
                "grade": str(getattr(ref, "source_grade", "") or ""),
            }
        )
    for idx, persona in enumerate(personas, start=1):
        state = _agent_state(persona, idx)
        nodes.append(
            {
                "id": f"agent:{state['id']}",
                "type": "agent",
                "label": state["name"],
                "role": state["role"],
            }
        )
    return nodes


def _world_edges(*, world_nodes: list[dict[str, Any]], turns: list[Any]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    evidence_ids = [node["id"] for node in world_nodes if node["type"] == "evidence"]
    agent_ids = [node["id"] for node in world_nodes if node["type"] == "agent"]
    for evidence_id in evidence_ids:
        edges.append({"from": "seed:topic", "to": evidence_id, "type": "grounded_by"})
    for agent_id in agent_ids:
        edges.append({"from": "seed:topic", "to": agent_id, "type": "observed_by"})
    for turn in turns[:200]:
        if not isinstance(turn, Mapping):
            continue
        speaker = str(turn.get("persona_id") or turn.get("speaker") or "").strip()
        if speaker:
            edges.append({"from": f"agent:{speaker}", "to": "seed:topic", "type": "interacted_with"})
    return edges


def _agent_state(persona: Any, idx: int) -> dict[str, Any]:
    if isinstance(persona, Mapping):
        name = str(persona.get("name") or f"agent-{idx}")
        role = str(persona.get("role") or "participant")
        manifest = persona.get("manifest") or persona.get("agent_manifest") or {}
        persona_id = str(persona.get("persona_id") or persona.get("id") or name)
    else:
        name = str(getattr(persona, "name", "") or f"agent-{idx}")
        role = str(getattr(persona, "role", "") or "participant")
        manifest = getattr(persona, "manifest", {}) or {}
        persona_id = str(getattr(persona, "persona_id", "") or name)
    memory = manifest.get("memory") if isinstance(manifest, Mapping) else None
    return {
        "id": persona_id,
        "name": name,
        "role": role,
        "memory_count": len(memory) if isinstance(memory, list) else 1,
    }


def _simulation_events(turns: list[Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for idx, turn in enumerate(turns[:500], start=1):
        if not isinstance(turn, Mapping):
            continue
        events.append(
            {
                "id": f"turn-{idx}",
                "round": int(turn.get("round") or 0),
                "stage": str(turn.get("stage") or turn.get("council_stage") or ""),
                "agent_id": str(turn.get("persona_id") or turn.get("speaker") or ""),
                "has_prompt": bool(turn.get("prompt") or int(turn.get("prompt_chars") or 0) > 0),
                "has_response": bool(
                    turn.get("response")
                    or turn.get("raw_response")
                    or int(turn.get("response_chars") or 0) > 0
                ),
            }
        )
    return events


def _temporal_memory_updates(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "event_id": event["id"],
            "agent_id": event["agent_id"],
            "memory_kind": "simulation_turn",
            "round": event["round"],
        }
        for event in events
        if event.get("agent_id")
    ]
