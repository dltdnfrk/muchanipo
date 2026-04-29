"""Runtime bridges for reference implementations that live outside packages.

Some older reference ports are command-line scripts with hyphenated filenames.
The main pipeline imports them through this small bridge so the 1-6 flow uses
their actual planning/formatting logic instead of only linking to docs.
"""
from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.evidence.artifact import EvidenceRef
from src.report.schema import ResearchReport


@lru_cache(maxsize=None)
def _load_module(name: str, path: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load reference module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _src_path(*parts: str) -> Path:
    return Path(__file__).resolve().parents[1].joinpath(*parts)


def build_reference_runtime_artifacts(
    *,
    report: ResearchReport,
    council: Any,
    evidence_summary: dict[str, Any],
) -> dict[str, Any]:
    """Build ReACT and GBrain artifacts from the actual reference ports."""
    council_payload = _council_payload(report, council)
    react_artifacts = _build_react_artifacts(council_payload)
    gbrain_artifacts = _build_gbrain_artifacts(
        council_payload=council_payload,
        report=report,
        evidence_summary=evidence_summary,
    )
    return {
        "react": react_artifacts,
        "gbrain": gbrain_artifacts,
    }


def _build_react_artifacts(council_payload: dict[str, Any]) -> dict[str, Any]:
    react_mod = _load_module(
        "muchanipo_react_report",
        str(_src_path("search", "react-report.py")),
    )
    sections = react_mod.plan_sections(council_payload, max_sections=3)
    plans = [
        react_mod.run_react_loop_plan(
            section=section,
            report_title=str(council_payload.get("topic") or ""),
            report_summary=str(council_payload.get("consensus") or ""),
            topic=str(council_payload.get("topic") or ""),
            previous_sections=[],
        )
        for section in sections
    ]
    return {
        "section_count": len(sections),
        "sections": [
            {
                "title": str(section.get("title") or ""),
                "type": str(section.get("type") or ""),
                "think": str((section.get("react") or {}).get("think") or ""),
                "act": str((section.get("react") or {}).get("act") or ""),
                "observe": str((section.get("react") or {}).get("observe") or ""),
                "write": str((section.get("react") or {}).get("write") or ""),
            }
            for section in sections
        ],
        "min_tool_calls": int(plans[0]["react_config"]["min_tool_calls"]) if plans else 0,
        "available_tools": list(plans[0]["react_config"]["available_tools"]) if plans else [],
    }


def _build_gbrain_artifacts(
    *,
    council_payload: dict[str, Any],
    report: ResearchReport,
    evidence_summary: dict[str, Any],
) -> dict[str, Any]:
    vault_mod = _load_module(
        "muchanipo_vault_router",
        str(_src_path("hitl", "vault-router.py")),
    )
    eval_result = {
        "verdict": "PASS" if evidence_summary.get("unsupported_finding_count", 0) == 0 else "UNCERTAIN",
        "total": int(round(float(report.confidence or 0.0) * 100)),
        "rubric_max": 100,
        "scores": {
            "grounding": int(round(float(evidence_summary.get("verified_claim_ratio", 0.0)) * 10)),
            "trusted_evidence": int(evidence_summary.get("trusted", 0) or 0),
        },
    }
    compiled_truth = vault_mod.build_compiled_truth(council_payload, eval_result)
    content_hash = vault_mod.compute_content_hash(compiled_truth)
    return {
        "slug": vault_mod.topic_to_slug(str(council_payload.get("topic") or report.title)),
        "content_hash": content_hash,
        "compiled_truth": compiled_truth,
        "timeline_entry": vault_mod.build_timeline_entry(eval_result, report.id).strip(),
    }


def _council_payload(report: ResearchReport, council: Any) -> dict[str, Any]:
    round_claims = _round_claims(council)
    evidence_lines = _evidence_lines(report.evidence_refs)
    return {
        "topic": report.title,
        "query": report.title,
        "council_id": report.id,
        "consensus": "\n".join(f"- {claim}" for claim in round_claims) if round_claims else report.executive_summary,
        "dissent": "\n".join(report.open_questions),
        "recommendations": _recommendations(report),
        "evidence": evidence_lines,
        "personas": [
            {"name": str(getattr(persona, "name", "")), "role": str(getattr(persona, "role", ""))}
            for persona in getattr(council, "personas", [])
        ],
        "confidence": float(report.confidence or 0.0),
        "tags": ["muchanipo", "autoresearch", "source-backed"],
    }


def _round_claims(council: Any) -> list[str]:
    claims: list[str] = []
    for item in getattr(council, "rounds", []) or []:
        claim = getattr(item, "key_claim", None)
        if claim:
            claims.append(str(claim))
            continue
        if isinstance(item, dict):
            consensus = item.get("consensus")
            if consensus:
                claims.append(str(consensus))
                continue
            results = item.get("results") or []
            if results and isinstance(results[0], dict):
                text = results[0].get("analysis") or results[0].get("updated_analysis")
                if text:
                    claims.append(str(text))
    return claims


def _evidence_lines(refs: list[EvidenceRef]) -> list[str]:
    lines: list[str] = []
    for ref in refs:
        source = ref.source_title or ref.source_url or ref.id
        quote = ref.quote or ""
        lines.append(f"{ref.id}: {source} — {quote[:180]}")
    return lines


def _recommendations(report: ResearchReport) -> list[str]:
    if report.open_questions:
        return [f"Resolve open question: {item}" for item in report.open_questions]
    return ["Preserve source-backed evidence trail before external use."]
