"""Product-planning projection for idea intake interviews.

The interview remains the source of truth. This module only reshapes the
answers into local planning artifacts that downstream gates can inspect:
PRD sections, a Requirement -> Feature -> Specification hierarchy, and a
small user-flow graph.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from src.intent.planning_contract import planning_question_contract


def build_product_planning_projection(
    raw_idea: str,
    answers: Mapping[str, str] | None = None,
    *,
    design_doc: Any | None = None,
) -> dict[str, Any]:
    """Build structured planning artifacts from interview answers.

    The projection intentionally preserves uncertainty. Missing interview
    answers are recorded in ``pending_fields`` instead of being invented.
    """
    answers = answers or {}
    raw = _clean(raw_idea) or "untitled idea"
    research_question = _answer(
        answers,
        "research_question",
        default=_clean(getattr(design_doc, "pain_root", "")) or raw,
    )
    purpose = _answer(
        answers,
        "purpose",
        default=_clean(getattr(design_doc, "demand_reality", "")) or "clarify next decision",
    )
    context = _answer(
        answers,
        "context",
        default=_clean(getattr(design_doc, "contrary_framing", ""))
        or _clean(getattr(design_doc, "status_quo", "")),
    )
    known_text = _answer(
        answers,
        "known",
        default="; ".join(str(item) for item in getattr(design_doc, "implicit_capabilities", []) or []),
    )
    deliverable = _answer(answers, "deliverable_type", default="research report")
    quality = _answer(answers, "quality_bar", default="evidence-backed")

    known_facts = _split_items(known_text)
    constraints = [
        _clean(item)
        for item in (getattr(design_doc, "challenged_premises", []) or [])
        if _clean(item)
    ]
    target_scenarios = _target_scenarios(context=context, raw_idea=raw)
    success_metrics = _success_metrics(
        purpose=purpose,
        quality=quality,
        design_doc=design_doc,
    )
    roles = _roles_from_text(" ".join([context, raw, purpose]))
    environments = _environments_from_text(" ".join([context, raw, deliverable]))
    pending_fields = _pending_fields(
        {
            "prd.overview": research_question,
            "prd.core_value": purpose,
            "prd.target_scenarios": context,
            "features.requirement_tree": deliverable,
            "success_metrics": quality,
        }
    )

    prd = {
        "overview": {
            "one_line": research_question,
            "goal": purpose,
            "background": context,
        },
        "core_value": {
            "problem": research_question,
            "resolution": purpose,
            "differentiator": _differentiator(known_facts, design_doc=design_doc),
        },
        "target_scenarios": target_scenarios,
        "success_metrics": success_metrics,
        "properties": {
            "category": _category_from_text(" ".join([raw, context, deliverable])),
            "roles": roles,
            "environments": environments,
        },
        "pending_fields": pending_fields,
    }
    feature_hierarchy = [
        {
            "level": "requirement",
            "name": purpose,
            "description": research_question,
            "acceptance_criteria": success_metrics,
            "features": [
                {
                    "level": "feature",
                    "name": deliverable,
                    "user_role": roles[0] if roles else "primary user",
                    "specifications": _specifications(
                        quality=quality,
                        known_facts=known_facts,
                        constraints=constraints,
                    ),
                }
            ],
        }
    ]
    user_flow = _user_flow(
        raw_idea=raw,
        purpose=purpose,
        context=context,
        deliverable=deliverable,
    )
    review_policy = {
        "mode": "proposal_first",
        "review_gate": "brief",
        "approval_required_before": "targeting",
        "change_surface": ["planning_prd", "feature_hierarchy", "user_flow"],
    }
    return {
        "planning_prd": prd,
        "feature_hierarchy": feature_hierarchy,
        "user_flow": user_flow,
        "planning_review_policy": review_policy,
    }


def _answer(answers: Mapping[str, str], key: str, *, default: str) -> str:
    value = _clean(answers.get(key, ""))
    return value or default


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def split_planning_items(value: str) -> list[str]:
    """Split user-provided planning lists the same way across callers."""
    items = [
        part.strip(" -•\t\r\n")
        for part in re.split(r"[;\n]+|,\s*(?=[가-힣A-Za-z0-9])", value or "")
    ]
    return [item for item in items if item]


def _split_items(value: str) -> list[str]:
    return split_planning_items(value)


def _target_scenarios(*, context: str, raw_idea: str) -> list[dict[str, str]]:
    parts = _split_items(context)
    if not parts:
        return [
            {
                "user_group": "primary user",
                "scenario": raw_idea,
                "source": "raw_idea",
            }
        ]
    return [
        {
            "user_group": part,
            "scenario": f"{part} context에서 {raw_idea} 검증",
            "source": "interview.context",
        }
        for part in parts[:4]
    ]


def _success_metrics(*, purpose: str, quality: str, design_doc: Any | None) -> list[str]:
    metrics = []
    if purpose:
        metrics.append(f"목적 충족: {purpose}")
    if quality:
        metrics.append(f"근거 기준 충족: {quality}")
    for value in (
        getattr(design_doc, "narrowest_wedge", ""),
        getattr(design_doc, "future_fit", ""),
    ):
        cleaned = _clean(value)
        if cleaned and cleaned not in metrics:
            metrics.append(cleaned)
    return metrics or ["success criteria pending interview answer"]


def _differentiator(known_facts: list[str], *, design_doc: Any | None) -> str:
    if known_facts:
        return "; ".join(known_facts[:3])
    for value in (
        getattr(design_doc, "narrowest_wedge", ""),
        getattr(design_doc, "future_fit", ""),
    ):
        cleaned = _clean(value)
        if cleaned:
            return cleaned
    return "pending differentiation input"


def _specifications(
    *,
    quality: str,
    known_facts: list[str],
    constraints: list[str],
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = [
        {
            "level": "specification",
            "name": "Evidence policy",
            "description": quality,
        }
    ]
    if known_facts:
        specs.append(
            {
                "level": "specification",
                "name": "Known baseline",
                "description": "; ".join(known_facts[:6]),
            }
        )
    if constraints:
        specs.append(
            {
                "level": "specification",
                "name": "Constraint handling",
                "description": "; ".join(constraints[:6]),
            }
        )
    return specs


def _user_flow(
    *,
    raw_idea: str,
    purpose: str,
    context: str,
    deliverable: str,
) -> dict[str, Any]:
    nodes = [
        {"id": "start", "type": "start", "label": "아이디어 입력"},
        {"id": "questionnaire", "type": "action", "label": "기획 질문지 답변"},
        {"id": "prd", "type": "section", "label": "PRD 초안"},
        {"id": "features", "type": "section", "label": "기능명세 seed"},
        {"id": "output", "type": "page", "label": deliverable},
    ]
    edges = [
        {"from": "start", "to": "questionnaire", "label": raw_idea},
        {"from": "questionnaire", "to": "prd", "label": purpose},
        {"from": "prd", "to": "features", "label": context or "target scenario pending"},
        {"from": "features", "to": "output", "label": "reviewed planning payload"},
    ]
    return {
        "version": "interview-derived",
        "sections": [
            {"id": "planning", "title": "질문지에서 PRD로"},
            {"id": "execution", "title": "기능명세에서 산출물로"},
        ],
        "nodes": nodes,
        "edges": edges,
    }


def _roles_from_text(text: str) -> list[str]:
    lowered = text.lower()
    roles: list[str] = []
    if any(token in lowered for token in ("농가", "farmer", "agtech")):
        roles.extend(["farmer", "operator"])
    if any(token in lowered for token in ("관리자", "admin")):
        roles.append("admin")
    if any(token in lowered for token in ("고객", "사용자", "customer", "user")):
        roles.append("end user")
    if not roles:
        roles.append("primary user")
    return _dedupe(roles)


def _environments_from_text(text: str) -> list[str]:
    lowered = text.lower()
    envs: list[str] = []
    if any(token in lowered for token in ("ios", "android", "모바일", "mobile")):
        envs.append("mobile")
    if any(token in lowered for token in ("web", "웹", "saas", "dashboard")):
        envs.append("web")
    if any(token in lowered for token in ("현장", "농가", "field")):
        envs.append("field")
    if not envs:
        envs.append("unspecified")
    return _dedupe(envs)


def _category_from_text(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("농가", "농업", "agtech", "작물")):
        return "AgTech"
    if any(token in lowered for token in ("saas", "web", "dashboard", "플랫폼")):
        return "SaaS"
    if any(token in lowered for token in ("진단", "biotech", "분자", "probe")):
        return "Biotech"
    if any(token in lowered for token in ("agent", "에이전트", "ai")):
        return "AI"
    return "unspecified"


def _pending_fields(fields: Mapping[str, str]) -> list[str]:
    return [key for key, value in fields.items() if not _clean(value)]


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out
