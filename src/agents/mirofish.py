"""Mirofish debate agent profile and council persona adapters."""
from __future__ import annotations

from typing import Any, Mapping

MIROFISH_PROMPT = """You are mirofish, a rigorous critique agent.
Read the research report and identify weak assumptions, missing evidence,
counter-hypotheses, citation gaps, and concrete next experiments.
Do not merely disagree; produce actionable pressure tests.
"""


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
