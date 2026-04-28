"""LLM prompt and response helpers for HACHIMI persona generation."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence


def build_persona_propose_prompt(
    ontology: Mapping[str, Any],
    target_count: int,
    topic: str,
) -> str:
    """Build the Stage 1 HACHIMI persona proposal prompt."""

    roles = _json_block(ontology.get("roles") or [])
    allowed_tools = _json_block(ontology.get("allowed_tools") or [])
    required_outputs = _json_block(ontology.get("required_outputs") or [])
    value_axes = _json_block(ontology.get("value_axes") or {})
    return f"""# HACHIMI Stage 1 PROPOSE

다음 토픽 '{topic}'에 대한 {target_count}개 페르소나를 생성하세요.
각 페르소나는 theory-anchored schema로 role, intent, value_axes 4축을 포함해야 합니다.

## Ontology
- allowed roles: {roles}
- allowed tools: {allowed_tools}
- required outputs: {required_outputs}
- default value_axes: {value_axes}

## Requirements
- 페르소나마다 topic과 직접 관련된 관점, 의사결정 기준, 실패 모드를 분해하세요.
- value_axes에는 time_horizon, risk_tolerance, stakeholder_priority,
  innovation_orientation 4축을 모두 포함하세요.
- allowed_tools와 required_outputs는 ontology 안의 값을 사용하세요.
- 안전하지 않은 개인 타겟팅, credential, PII, 침투/우회 목적 페르소나는 만들지 마세요.

## JSON Output
JSON만 반환하세요.
```json
{{
  "personas": [
    {{
      "persona_id": "persona-001",
      "name": "Evidence Reviewer 1",
      "role": "evidence_reviewer",
      "intent": "Evaluate topic-specific claims against cited evidence.",
      "allowed_tools": ["read_file"],
      "required_outputs": ["report"],
      "value_axes": {{
        "time_horizon": "mid",
        "risk_tolerance": 0.35,
        "stakeholder_priority": ["primary", "secondary", "tertiary"],
        "innovation_orientation": 0.55
      }},
      "manifest": {{
        "topic_fit": "why this persona matters for the topic"
      }}
    }}
  ]
}}
```
"""


def build_persona_deep_validate_prompt(
    draft: Any,
    ontology: Mapping[str, Any],
    topic: str,
) -> str:
    """Build the Stage 2 LLM judge prompt for one persona."""

    manifest = draft.to_manifest() if hasattr(draft, "to_manifest") else {}
    payload = {
        "persona_id": getattr(draft, "persona_id", ""),
        "name": getattr(draft, "name", ""),
        "role": getattr(draft, "role", ""),
        "intent": getattr(draft, "intent", ""),
        "manifest": manifest,
    }
    return f"""# HACHIMI Stage 2 DEEP VALIDATE

이 페르소나가 토픽 '{topic}'와 관련성 있는가?
0-10 점수와 이유를 JSON으로 반환하세요. 0은 무관, 10은 매우 관련 있음입니다.

## Ontology
{_json_block(ontology)}

## Persona
{_json_block(payload)}

## JSON Output
```json
{{
  "score": 8,
  "reason": "topic-specific evidence reviewer",
  "issues": []
}}
```
"""


def parse_persona_proposal_response(text: str) -> list[dict[str, Any]]:
    """Parse LLM persona proposal JSON into raw persona mappings."""

    payload = _parse_json_payload(text)
    if isinstance(payload, dict):
        candidates = payload.get("personas") or payload.get("drafts") or payload.get("items")
    else:
        candidates = payload
    if not isinstance(candidates, list):
        raise ValueError("persona proposal response did not contain a list")

    personas: list[dict[str, Any]] = []
    for item in candidates:
        if isinstance(item, Mapping):
            personas.append(dict(item))
    if not personas:
        raise ValueError("persona proposal response contained no persona objects")
    return personas


def parse_persona_validation_response(text: str) -> tuple[float, str, list[str]]:
    """Parse LLM validation JSON into normalized score, reason, issues."""

    payload = _parse_json_payload(text)
    if not isinstance(payload, Mapping):
        raise ValueError("persona validation response did not contain an object")
    raw_score = payload.get("score", payload.get("relevance_score", 0))
    score = _coerce_score(raw_score)
    reason = str(payload.get("reason") or payload.get("rationale") or "").strip()
    issues = _string_list(payload.get("issues"))
    return score, reason, issues


def _parse_json_payload(text: str) -> Any:
    stripped = text.strip()
    candidates = [stripped]
    candidates.extend(match.group(1).strip() for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, re.S | re.I))
    brace_match = re.search(r"\{.*\}", text, re.S)
    if brace_match:
        candidates.append(brace_match.group(0))
    bracket_match = re.search(r"\[.*\]", text, re.S)
    if bracket_match:
        candidates.append(bracket_match.group(0))

    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError("no valid JSON payload found")


def _coerce_score(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        match = re.search(r"\d+(?:\.\d+)?", str(value))
        number = float(match.group(0)) if match else 0.0
    if number > 1.0:
        number = number / 10.0
    return max(0.0, min(1.0, number))


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Sequence):
        return [str(item) for item in value if str(item)]
    return [str(value)] if str(value) else []


def _json_block(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
