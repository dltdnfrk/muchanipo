"""Per-Finding citation grounding via `src.eval.citation_grounder`.

`Finding` already lives in `artifact.py`; this module computes
`verified_claim_ratio` for a finding without mutating its dataclass schema —
so existing C31 tests (`tests/test_c31_research_evidence.py`) keep passing.
"""
from __future__ import annotations

from typing import Any

from .artifact import EvidenceRef, Finding


def _evidence_payload(refs: list[EvidenceRef]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ref in refs:
        prov = ref.provenance or {}
        out.append(
            {
                "id": ref.id,
                "quote": ref.quote or "",
                "source": ref.source_url or prov.get("source") or "",
                "source_text": prov.get("source_text", ""),
            }
        )
    return out


def grounding_for_finding(finding: Finding) -> dict[str, Any]:
    """Run citation_grounder against a single finding's claim + support."""
    from src.eval.citation_grounder import ground_claims

    return ground_claims(
        consensus=finding.claim,
        recommendations=[],
        evidence=_evidence_payload(finding.support),
        dissent="",
    )


def verified_claim_ratio(finding: Finding) -> float:
    """0.0–1.0 ratio of supported claims for this finding.

    Vacuously 1.0 for findings with no extractable atomic claim — matches
    `citation_grounder.ground_claims` behavior on empty input.
    """
    grounding = grounding_for_finding(finding)
    return float(grounding.get("verified_claim_ratio", 1.0))


def annotate_findings(findings: list[Finding]) -> list[dict[str, Any]]:
    """Return a per-finding grounding report list, in input order."""
    return [
        {
            "claim": f.claim,
            "verified_claim_ratio": verified_claim_ratio(f),
            "evidence_ids": [ev.id for ev in f.support],
        }
        for f in findings
    ]
