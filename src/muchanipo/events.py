"""JSON-line event protocol used by `python3 -m muchanipo serve`.

The Swift native shell consumes one JSON object per stdout line and writes
user actions to stdin in the same format. Event field layout matches
_assignments/ASSIGNMENT_C33_native_app.md.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, IO


KNOWN_EVENTS = frozenset(
    {
        "phase_change",
        "interview_question",
        "council_round_start",
        "council_persona_token",
        "council_round_done",
        "report_chunk",
        "done",
        "error",
    }
)

KNOWN_ACTIONS = frozenset(
    {
        "interview_answer",
        "approve_designdoc",
        "abort",
    }
)


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
