"""Karpathy-style 3-stage council prompts."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.council.round_layers import RoundLayer, layer_prompt_block


def build_individual_prompt(persona: Any, layer: RoundLayer, prev_summary: str = "") -> str:
    """Prompt one persona for independent analysis without seeing peers."""
    identity = _persona_label(persona)
    return "\n".join(
        [
            "# Council Stage 1: Individual Analysis",
            "",
            "You must reason independently. Do not infer, quote, or reference other personas.",
            "",
            f"Persona: {identity}",
            "",
            layer_prompt_block(layer),
            "",
            "Previous round summary:",
            prev_summary or "(none)",
            "",
            "Return JSON with: key_claim, body_claims, evidence_ref_ids, confidence_score, disagreements, next_actions.",
        ]
    )


def build_peer_review_prompt(
    persona: Any,
    blinded_opinions: Sequence[Mapping[str, Any]],
    layer: RoundLayer,
) -> str:
    """Prompt one persona to review anonymous peer opinions."""
    identity = _persona_label(persona)
    lines = [
        "# Council Stage 2: Anonymous Peer Review",
        "",
        "Review the following opinions. They are intentionally anonymized.",
        "Do not guess author identity. Refer only to Opinion A/B/C labels.",
        "",
        f"Reviewer persona: {identity}",
        "",
        layer_prompt_block(layer),
        "",
        "Anonymous opinions:",
    ]
    for idx, opinion in enumerate(blinded_opinions):
        label = chr(ord("A") + idx)
        lines.extend(
            [
                f"## Opinion {label}",
                f"Claim: {opinion.get('key_claim', '')}",
                "Support:",
            ]
        )
        for claim in opinion.get("body_claims", []) or []:
            lines.append(f"- {claim}")
        lines.append("")
    lines.extend(
        [
            "Return JSON with: stance, critiques, agreements, suggested_revision, confidence_score.",
        ]
    )
    return "\n".join(lines)


def build_chairman_prompt(
    individuals: Mapping[str, Any],
    peer_reviews: Mapping[str, Sequence[Any]],
    layer: RoundLayer,
) -> str:
    """Prompt the chairman to synthesize consensus and disagreements."""
    lines = [
        "# Council Stage 3: Chairman Synthesis",
        "",
        "Synthesize the independent opinions and anonymous peer reviews.",
        "Explicitly state consensus and disagreements. Do not hide unresolved assumptions.",
        "",
        layer_prompt_block(layer),
        "",
        "Independent opinions:",
    ]
    for idx, opinion in enumerate(individuals.values(), start=1):
        lines.extend(
            [
                f"## Individual Opinion {idx}",
                f"Claim: {getattr(opinion, 'key_claim', '')}",
                "Support:",
            ]
        )
        for claim in getattr(opinion, "body_claims", []) or []:
            lines.append(f"- {claim}")
        lines.append("")

    lines.append("Peer review themes:")
    for idx, comments in enumerate(peer_reviews.values(), start=1):
        lines.append(f"## Reviewer {idx}")
        for comment in comments:
            text = getattr(comment, "text", "")
            if text:
                lines.append(f"- {text}")
        lines.append("")

    lines.extend(
        [
            "Return JSON with:",
            "- key_claim: one chairman conclusion",
            "- body_claims: support bullets",
            "- evidence_ref_ids: cited evidence ids",
            "- confidence_score: 0..1",
            "- disagreements: explicit unresolved disagreements",
            "- next_actions: verification actions",
            "- framework_output: optional structured framework output",
        ]
    )
    return "\n".join(lines)


def _persona_label(persona: Any) -> str:
    if isinstance(persona, Mapping):
        return " / ".join(str(persona.get(key, "")) for key in ("persona_id", "name", "role") if persona.get(key))
    return " / ".join(
        str(getattr(persona, key, ""))
        for key in ("persona_id", "name", "role")
        if getattr(persona, key, "")
    )
