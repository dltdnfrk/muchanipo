"""JSON-line event protocol used by `python3 -m muchanipo serve`.

The Swift native shell consumes one JSON object per stdout line and writes
user actions to stdin in the same format. Event field layout matches
_assignments/ASSIGNMENT_C33_native_app.md.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, IO, Mapping

from src.pipeline.goals_stages import (
    PUBLIC_GOALS_STAGE_IDS,
    normalize_public_stage,
)


KNOWN_EVENTS = frozenset(
    {
        "phase_change",
        "run_started",
        "pipeline_heartbeat",
        "stage_started",
        "stage_progress",
        "stage_blocked",
        "stage_completed",
        "stage_failed",
        "deep_interview_progress",
        "deep_interview_artifacts",
        "interview_ontology_delta",
        "interview_question",
        "hitl_gate",
        "research_progress",
        "council_round_start",
        "council_turn",
        "council_persona_token",
        "council_round_done",
        "report_chunk",
        "done",
        "warning",
        "error",
    }
)

KNOWN_ACTIONS = frozenset(
    {
        "interview_answer",
        "approve_designdoc",
        "hitl_decision",
        "abort",
    }
)

NORMALIZED_STAGE_EVENTS = frozenset(
    {
        "stage_started",
        "stage_progress",
        "stage_blocked",
        "stage_completed",
        "stage_failed",
    }
)

LEGACY_SUBEVENT_STAGE_HINTS: dict[str, str] = {
    "deep_interview_progress": "deep_interview",
    "deep_interview_artifacts": "deep_interview",
    "interview_ontology_delta": "ontology_extraction",
    "interview_question": "deep_interview",
    "hitl_gate": "plannotator_review",
    "research_progress": "deep_research_max",
    "council_round_start": "llm_council",
    "council_turn": "llm_council",
    "council_persona_token": "llm_council",
    "council_round_done": "llm_council",
    "report_chunk": "final_report_html_yaml",
}

_EVENT_STATUS_MAP: dict[str, str] = {
    "stage_started": "in_progress",
    "stage_progress": "in_progress",
    "stage_blocked": "blocked",
    "stage_completed": "completed",
    "stage_failed": "failed",
}


@dataclass(frozen=True)
class Event:
    """One outbound stdout event."""

    event: str
    fields: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        payload = {"event": self.event, **self.fields}
        return json.dumps(payload, ensure_ascii=False)


@dataclass(frozen=True)
class Action:
    """One inbound stdin action from the Swift shell."""

    action: str
    fields: dict[str, Any] = field(default_factory=dict)


def emit(event: str, *, stream: IO[str] | None = None, **fields: Any) -> None:
    """Write a single JSON-line event and flush so Swift sees it immediately."""
    out = stream if stream is not None else sys.stdout
    payload = {"event": event, **fields}
    out.write(json.dumps(payload, ensure_ascii=False))
    out.write("\n")
    out.flush()


def _event_metadata(payload: Mapping[str, Any], *, exclude: set[str]) -> dict[str, Any]:
    metadata = dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), Mapping) else {}
    for key, value in payload.items():
        if key not in exclude and key != "metadata":
            metadata[key] = value
    return metadata


def normalize_goals_event(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize runtime events into the public GOALS stage event contract.

    Canonical events keep their stage event name and accept canonical ids. Legacy
    runtime stages are mapped to canonical public ids and retained in metadata.
    Legacy subevents become ``stage_progress`` with the old event name in
    ``metadata.subactivity``.
    """
    if not isinstance(payload, Mapping):
        raise TypeError("event payload must be a mapping")
    event_name = str(payload.get("event") or "")
    if not event_name:
        raise KeyError("event payload requires event")

    stage_hint = payload.get("stage_id") or payload.get("stage") or LEGACY_SUBEVENT_STAGE_HINTS.get(event_name)
    if stage_hint is None:
        raise KeyError("GOALS event requires stage, stage_id, or known legacy subevent")
    stage_key = str(stage_hint)
    stage_id = normalize_public_stage(stage_key)

    if event_name in NORMALIZED_STAGE_EVENTS:
        normalized_event = event_name
        exclude = {"event", "stage", "stage_id"}
        metadata = _event_metadata(payload, exclude=exclude)
        if stage_key != stage_id:
            metadata.setdefault("legacy_stage", stage_key)
    else:
        normalized_event = "stage_progress"
        exclude = {"event", "stage", "stage_id"}
        metadata = _event_metadata(payload, exclude=exclude)
        metadata.setdefault("subactivity", event_name)
        if stage_key != stage_id and stage_key not in PUBLIC_GOALS_STAGE_IDS:
            metadata.setdefault("legacy_stage", stage_key)

    return {
        "event": normalized_event,
        "stage": stage_id,
        "stage_id": stage_id,
        "status": _EVENT_STATUS_MAP.get(normalized_event, "in_progress"),
        "metadata": metadata,
    }


def goals_event_contract_report() -> dict[str, Any]:
    """Return the stable normalized GOALS event contract for JSON consumers."""
    return {
        "schema_version": 1,
        "contract": "goals_normalized_events",
        "stage_ids": list(PUBLIC_GOALS_STAGE_IDS),
        "events": list(sorted(NORMALIZED_STAGE_EVENTS)),
        "event_status_map": dict(_EVENT_STATUS_MAP),
        "required_fields": ["event", "stage", "stage_id", "status", "metadata"],
        "legacy_subevent_stage_hints": dict(LEGACY_SUBEVENT_STAGE_HINTS),
        "compatibility": (
            "stage_started/stage_progress/stage_blocked/stage_completed/"
            "stage_failed carry canonical public GOALS stage ids. Legacy runtime "
            "subevents are projected as stage_progress and preserved in "
            "metadata.subactivity."
        ),
    }


def parse_action(line: str) -> Action | None:
    """Parse one stdin line into an Action, or None on blank/invalid input."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "action" not in obj:
        return None
    name = obj.pop("action")
    if not isinstance(name, str):
        return None
    return Action(action=name, fields=obj)
