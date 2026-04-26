"""Generate debate agents from ResearchReport artifacts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from src.report.schema import ResearchReport

from .mirofish import MIROFISH_PROMPT, council_persona_to_agent_fields
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
    def from_report(
        self,
        report: ResearchReport,
        *,
        target_count: int | None = None,
        research_type: str = "exploratory",
    ) -> list[DebateAgentSpec]:
        personas = _council_personas_from_report(
            report,
            target_count=target_count,
            research_type=research_type,
        )
        if personas:
            agents = [
                DebateAgentSpec(
                    **{
                        **council_persona_to_agent_fields(persona),
                        "source_report_id": report.id,
                        "system_prompt": _prompt_for_persona(persona),
                    }
                )
                for persona in personas
            ]
            if not any(agent.name == "mirofish" for agent in agents):
                agents.insert(0, _mirofish_agent(report))
            return agents

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


def _mirofish_agent(report: ResearchReport) -> DebateAgentSpec:
    return DebateAgentSpec(
        name="mirofish",
        role="critic",
        perspective="skeptical",
        expertise=["evidence", "research report review"],
        challenge_targets=["findings", "evidence", "limitations"],
        source_report_id=report.id,
        system_prompt=MIROFISH_PROMPT,
    )


def _council_personas_from_report(
    report: ResearchReport,
    *,
    target_count: int | None,
    research_type: str,
) -> list[dict[str, Any]]:
    try:
        runner = _load_council_runner()
        select_default = getattr(runner, "_select_personas_default")
    except Exception:
        return []

    count = target_count or max(4, min(7, len(_emphasis_roles(research_type)) or 4))
    personas = [dict(persona) for persona in select_default(count)]
    topic_text = _report_topic_text(report)
    emphasis = _emphasis_roles(research_type)

    if emphasis:
        prioritized = _prioritize_by_emphasis(personas, emphasis)
    else:
        prioritized = personas

    for persona in prioritized:
        persona["challenge_targets"] = _challenge_targets(report)
        persona["system_prompt"] = _persona_prompt(persona, topic_text)
    return prioritized[:count]


def _load_council_runner() -> Any:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "council" / "council-runner.py"
    spec = importlib.util.spec_from_file_location("src.council.council_runner_runtime", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load council runner from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _emphasis_roles(research_type: str) -> list[str]:
    try:
        from src.council.round_layers import select_layer_for_round
    except Exception:
        return []

    layer = select_layer_for_round(1, total_rounds=5, research_type=research_type)
    return list(layer.emphasis_roles)


def _prioritize_by_emphasis(
    personas: list[dict[str, Any]],
    emphasis_roles: Iterable[str],
) -> list[dict[str, Any]]:
    emphasis = [role.casefold().replace("_", " ") for role in emphasis_roles]

    def score(persona: dict[str, Any]) -> int:
        role_text = str(persona.get("role", "")).casefold().replace("_", " ")
        expertise_text = " ".join(str(item) for item in persona.get("expertise", [])).casefold()
        return sum(1 for role in emphasis if role in role_text or role in expertise_text)

    return sorted(personas, key=score, reverse=True)


def _challenge_targets(report: ResearchReport) -> list[str]:
    targets = ["findings", "evidence", "limitations"]
    if report.open_questions:
        targets.append("open_questions")
    if report.confidence < 0.75:
        targets.append("confidence")
    return targets


def _report_topic_text(report: ResearchReport) -> str:
    claims = [getattr(finding, "claim", "") for finding in report.findings[:3]]
    return " ".join([report.title, report.executive_summary] + [c for c in claims if c])


def _persona_prompt(persona: dict[str, Any], topic_text: str) -> str:
    role = str(persona.get("role", "council reviewer"))
    name = str(persona.get("name", "debate-agent"))
    prompt = MIROFISH_PROMPT if name == "mirofish" else generic_agent_prompt(name, role)
    return (
        f"{prompt}\n"
        f"Council role: {role}\n"
        f"Perspective: {persona.get('perspective_bias', '')}\n"
        f"Topic evidence summary: {topic_text[:600]}"
    )


def _prompt_for_persona(persona: dict[str, Any]) -> str:
    return str(persona.get("system_prompt") or generic_agent_prompt(
        str(persona.get("name", "debate-agent")),
        str(persona.get("role", "council reviewer")),
    ))
