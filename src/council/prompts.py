"""Prompt builders for structured LLM-backed council sessions."""

from __future__ import annotations

from typing import Any, Sequence

from src.council.round_layers import RoundLayer, layer_prompt_block
from src.frameworks.registry import framework_prompt_block, frameworks_for_layer


_FRAMEWORK_GUIDANCE: dict[str, str] = {
    "Porter 5 Forces": (
        "Use Porter to separate supplier power, buyer power, rivalry, substitutes, "
        "and new entrants. Rate each force and explain the strategic implication."
    ),
    "JTBD": (
        "Use JTBD to separate functional, emotional, and social jobs. Name the "
        "current solution, the underperformance gap, and hire/fire candidates."
    ),
    "MECE Tree": (
        "Use a MECE issue tree. Keep branches mutually exclusive and collectively "
        "exhaustive, then identify the leaf hypotheses that most change the answer."
    ),
    "North Star Tree": (
        "Use a North Star metric tree. Name one north-star metric and 5-7 drivers "
        "with baseline, target, cadence, and owner where possible."
    ),
    "SWOT": (
        "Use SWOT/TOWS. Separate internal strengths and weaknesses from external "
        "opportunities and threats, then include at least one defensive action."
    ),
}


def build_round_prompt(
    layer: RoundLayer,
    personas: Sequence[Any],
    prev_rounds_summaries: Sequence[Any],
) -> str:
    """Build one structured council prompt for a layer.

    The prompt follows the PRD 6.1 three-stage pattern:
    individual assessment, peer review, then chairman synthesis.
    """

    framework_names = [name for name, _hint in frameworks_for_layer(layer.layer_id)]
    framework_guidance = _framework_guidance(framework_names)
    previous = _format_previous_rounds(prev_rounds_summaries)
    persona_block = _format_personas(personas)
    framework_block = framework_prompt_block(layer.layer_id)

    parts = [
        "# Council Deliberation Round",
        "",
        layer_prompt_block(layer),
        "",
        "## Personas",
        persona_block,
        "",
        "## Framework Guidance",
        framework_guidance,
    ]
    if framework_block:
        parts.extend(["", framework_block])
    parts.extend(
        [
            "",
            "## Previous Round Summaries",
            previous,
            "",
            "## PRD 6.1 Three-Stage Deliberation Pattern",
            "1. Individual: each persona gives a concise independent judgment.",
            "2. Peer review: personas challenge the strongest unsupported claims.",
            "3. Chairman: synthesize the council's final position for this layer.",
            "",
            "## Required Output",
            "Return JSON only when possible. Markdown is acceptable if JSON is impossible.",
            "Use this schema:",
            "```json",
            "{",
            f'  "layer_id": "{layer.layer_id}",',
            f'  "chapter_title": "{layer.chapter_title}",',
            '  "framework": "MECE Tree | Porter 5 Forces | JTBD | North Star Tree | SWOT | none",',
            '  "key_claim": "one or two sentence chairman synthesis",',
            '  "body_claims": ["supporting claim 1", "supporting claim 2"],',
            '  "evidence_ref_ids": ["optional evidence id"],',
            '  "confidence_score": 0.0,',
            '  "disagreements": ["remaining disagreement"],',
            '  "next_actions": ["next verification or execution action"],',
            '  "framework_output": {}',
            "}",
            "```",
            "",
            "Confidence must be a 0.0-1.0 self-report based on evidence quality, "
            "persona agreement, and unresolved assumptions.",
        ]
    )
    return "\n".join(parts).strip() + "\n"


def _framework_guidance(framework_names: Sequence[str]) -> str:
    if not framework_names:
        return "- No mandatory framework for this layer; use structured executive reasoning."
    return "\n".join(
        f"- {name}: {_FRAMEWORK_GUIDANCE.get(name, 'Apply this framework explicitly.')}"
        for name in framework_names
    )


def _format_personas(personas: Sequence[Any]) -> str:
    if not personas:
        return "- No personas supplied; act as a balanced council."

    lines: list[str] = []
    for persona in personas:
        name = _get_attr_or_key(persona, "name", "unknown")
        role = _get_attr_or_key(persona, "role", "council_member")
        persona_id = _get_attr_or_key(persona, "persona_id", name)
        manifest = _get_attr_or_key(persona, "manifest", {})
        manifest_bits = ""
        if isinstance(manifest, dict) and manifest:
            intent = manifest.get("intent") or manifest.get("perspective") or ""
            outputs = manifest.get("required_outputs") or []
            if intent:
                manifest_bits += f"; intent={intent}"
            if outputs:
                manifest_bits += f"; outputs={', '.join(map(str, outputs))}"
        lines.append(f"- {name} ({role}, id={persona_id}{manifest_bits})")
    return "\n".join(lines)


def _format_previous_rounds(prev_rounds_summaries: Sequence[Any]) -> str:
    if not prev_rounds_summaries:
        return "- None. This is the first council layer."

    lines: list[str] = []
    for idx, item in enumerate(prev_rounds_summaries, start=1):
        if isinstance(item, str):
            lines.append(f"- Round {idx}: {item}")
            continue
        layer_id = _get_attr_or_key(item, "layer_id", f"round-{idx}")
        key_claim = _get_attr_or_key(item, "key_claim", "")
        confidence = _get_attr_or_key(item, "confidence_score", None)
        suffix = f" confidence={confidence:.2f}" if isinstance(confidence, (int, float)) else ""
        lines.append(f"- {layer_id}: {key_claim}{suffix}")
    return "\n".join(lines)


def _get_attr_or_key(obj: Any, key: str, default: Any) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)
