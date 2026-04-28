"""Best-effort parsers for structured council LLM responses."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from src.council.round_layers import RoundLayer
from src.frameworks.registry import frameworks_for_layer


@dataclass(frozen=True)
class RoundResult:
    """Structured output from one LLM-backed council layer."""

    layer_id: str
    chapter_title: str
    key_claim: str
    body_claims: list[str] = field(default_factory=list)
    evidence_ref_ids: list[str] = field(default_factory=list)
    confidence_score: float = 0.0
    framework: str | None = None
    disagreements: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    raw_response: str = ""
    framework_output: Any = None


def parse_council_response(text: str, layer: RoundLayer) -> RoundResult:
    """Parse JSON or markdown council output into a RoundResult."""

    payload = _parse_json_payload(text)
    if isinstance(payload, dict):
        return _result_from_mapping(payload, layer, text)
    return _result_from_markdown(text, layer)


def _result_from_mapping(data: dict[str, Any], layer: RoundLayer, raw: str) -> RoundResult:
    framework_output = data.get("framework_output")
    framework = _as_text(data.get("framework")) or _framework_from_output(framework_output) or _default_framework(layer)
    key_claim = (
        _as_text(data.get("key_claim"))
        or _as_text(data.get("lead_claim"))
        or _as_text(data.get("summary"))
        or _as_text(data.get("chairman_synthesis"))
        or _as_text(data.get("conclusion"))
        or _first_nonempty(_as_list(data.get("body_claims")))
        or _fallback_key_claim(raw)
    )
    body_claims = _as_list(data.get("body_claims") or data.get("claims") or data.get("key_points"))
    if not body_claims:
        analysis = _as_text(data.get("analysis") or data.get("body") or data.get("rationale"))
        body_claims = _sentences_or_lines(analysis)
    if key_claim and key_claim in body_claims and len(body_claims) > 1:
        body_claims = [claim for claim in body_claims if claim != key_claim]

    return RoundResult(
        layer_id=_as_text(data.get("layer_id")) or layer.layer_id,
        chapter_title=_as_text(data.get("chapter_title")) or layer.chapter_title,
        key_claim=key_claim,
        body_claims=body_claims or ([key_claim] if key_claim else []),
        evidence_ref_ids=_as_list(data.get("evidence_ref_ids") or data.get("evidence_ids") or data.get("evidence")),
        confidence_score=_confidence(data),
        framework=framework,
        disagreements=_as_list(data.get("disagreements") or data.get("remaining_concerns")),
        next_actions=_as_list(data.get("next_actions") or data.get("actions")),
        raw_response=raw,
        framework_output=framework_output,
    )


def _result_from_markdown(text: str, layer: RoundLayer) -> RoundResult:
    values = _markdown_fields(text)
    key_claim = (
        values.get("key_claim")
        or values.get("summary")
        or values.get("chairman")
        or _fallback_key_claim(text)
    )
    body_claims = _markdown_list_after(text, "body_claims") or _markdown_list_after(text, "claims")
    if not body_claims:
        body_claims = _sentences_or_lines(text)
    if key_claim and key_claim in body_claims and len(body_claims) > 1:
        body_claims = [claim for claim in body_claims if claim != key_claim]

    confidence_text = values.get("confidence_score") or values.get("confidence")
    return RoundResult(
        layer_id=layer.layer_id,
        chapter_title=layer.chapter_title,
        key_claim=key_claim,
        body_claims=body_claims or ([key_claim] if key_claim else []),
        evidence_ref_ids=_markdown_list_after(text, "evidence_ref_ids"),
        confidence_score=_coerce_confidence(confidence_text) if confidence_text else _heuristic_confidence(text),
        framework=values.get("framework") or _default_framework(layer),
        disagreements=_markdown_list_after(text, "disagreements"),
        next_actions=_markdown_list_after(text, "next_actions"),
        raw_response=text,
        framework_output=None,
    )


def _parse_json_payload(text: str) -> Any:
    stripped = text.strip()
    candidates = [stripped]
    candidates.extend(match.group(1).strip() for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, re.S | re.I))
    brace_match = re.search(r"\{.*\}", text, re.S)
    if brace_match:
        candidates.append(brace_match.group(0))
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _markdown_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        cleaned = line.strip().strip("-* ")
        match = re.match(r"(?P<key>[A-Za-z_ -]+)\s*:\s*(?P<value>.+)", cleaned)
        if not match:
            continue
        key = match.group("key").strip().lower().replace(" ", "_").replace("-", "_")
        fields[key] = match.group("value").strip()
    return fields


def _markdown_list_after(text: str, field: str) -> list[str]:
    normalized = field.lower().replace("_", "[ _-]?")
    pattern = re.compile(rf"^\s*(?:#+\s*)?{normalized}\s*:?\s*$", re.I)
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if not pattern.match(line.strip()):
            continue
        items: list[str] = []
        for following in lines[idx + 1 :]:
            stripped = following.strip()
            if not stripped:
                if items:
                    break
                continue
            if stripped.startswith("#"):
                break
            bullet = re.match(r"^[-*]\s+(.+)", stripped)
            if bullet:
                items.append(bullet.group(1).strip())
            elif items:
                break
        return items
    return []


def _confidence(data: dict[str, Any]) -> float:
    for key in ("confidence_score", "confidence", "score"):
        if key in data:
            return _coerce_confidence(data.get(key))
    return _heuristic_confidence(json.dumps(data, ensure_ascii=False))


def _coerce_confidence(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        match = re.search(r"\d+(?:\.\d+)?", str(value))
        number = float(match.group(0)) if match else 0.0
    if number > 1.0:
        number = number / 100.0
    return max(0.0, min(1.0, number))


def _heuristic_confidence(text: str) -> float:
    lowered = text.lower()
    score = 0.55
    if any(word in lowered for word in ("uncertain", "불확실", "가정", "assumption")):
        score -= 0.1
    if any(word in lowered for word in ("evidence", "근거", "source", "출처")):
        score += 0.1
    if any(word in lowered for word in ("consensus", "합의", "chairman", "synthesis")):
        score += 0.05
    return max(0.0, min(1.0, score))


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in (_as_text(v) for v in value) if item]
    if isinstance(value, tuple):
        return [item for item in (_as_text(v) for v in value) if item]
    if isinstance(value, dict):
        return [f"{key}: {val}" for key, val in value.items()]
    text = _as_text(value)
    if not text:
        return []
    if "\n" in text:
        return [line.strip("-* ").strip() for line in text.splitlines() if line.strip("-* ").strip()]
    return [part.strip() for part in re.split(r";\s*", text) if part.strip()]


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def _sentences_or_lines(text: str) -> list[str]:
    if not text:
        return []
    lines = [line.strip("-* ").strip() for line in text.splitlines() if line.strip("-* ").strip()]
    useful = [line for line in lines if not line.startswith("```")]
    if len(useful) >= 2:
        return useful[:6]
    parts = [part.strip() for part in re.split(r"(?<=[.!?。])\s+", text.strip()) if part.strip()]
    return parts[:6]


def _fallback_key_claim(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip("-*# `").strip()
        if stripped:
            return stripped[:500]
    return ""


def _first_nonempty(values: list[str]) -> str:
    return next((value for value in values if value), "")


def _framework_from_output(value: Any) -> str:
    if isinstance(value, dict):
        return _as_text(value.get("framework") or value.get("type") or value.get("name"))
    return ""


def _default_framework(layer: RoundLayer) -> str | None:
    frameworks = frameworks_for_layer(layer.layer_id)
    return frameworks[0][0] if frameworks else None
