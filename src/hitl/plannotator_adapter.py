"""HITL gate adapter with markdown fallback and Plannotator HTTP support."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


SIGNOFF_QUEUE = Path("src/hitl/signoff-queue")
VALID_STATUSES = {"approved", "changes_requested", "pending"}


@dataclass
class HITLResult:
    status: str
    annotations: list[dict[str, Any]] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    gate_id: str | None = None
    path: str | None = None
    synthetic: bool = False

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(f"invalid HITL status: {self.status}")


class HITLAdapter:
    """Human-in-the-loop gates for brief, evidence, and report review.

    ``markdown`` mode writes a queue item and returns pending unless the file
    is approved within the configured timeout. ``auto_approve`` is for tests
    and local mock-first pipelines. ``plannotator`` delegates to the HTTP
    client, which falls back to an offline mock when no API key is configured.
    """

    def __init__(
        self,
        mode: str = "markdown",
        queue_dir: Path = SIGNOFF_QUEUE,
        timeout_seconds: float = 0.0,
        poll_interval_seconds: float = 0.25,
        client: Any | None = None,
    ) -> None:
        if mode not in {"markdown", "auto_approve", "plannotator"}:
            raise ValueError(f"unsupported HITL mode: {mode}")
        self.mode = mode
        self.queue_dir = Path(queue_dir)
        self.timeout_seconds = max(0.0, float(timeout_seconds))
        self.poll_interval_seconds = max(0.01, float(poll_interval_seconds))
        self.client = client
        if self.mode == "plannotator" and self.client is None:
            from src.hitl.plannotator_http import PlannotatorClient

            self.client = PlannotatorClient()

    def gate(self, gate_name: str, payload: dict) -> HITLResult:
        if not gate_name.strip():
            raise ValueError("gate_name must not be empty")

        if self.mode == "auto_approve":
            return HITLResult(
                status="approved",
                comments=[f"auto-approved gate: {gate_name}"],
                gate_id=f"{gate_name}-auto",
                synthetic=True,
            )
        if self.mode == "plannotator":
            return self._plannotator_gate(gate_name, payload)
        return self._markdown_gate(gate_name, payload)

    def _plannotator_gate(self, gate_name: str, payload: dict) -> HITLResult:
        if self.client is None:
            raise RuntimeError("plannotator mode requires a client")

        session_id = self.client.create_session(
            {
                "gate": gate_name,
                "payload": payload,
            }
        )
        status = self.client.poll_until_decision(
            session_id,
            timeout_sec=self.timeout_seconds or 86400,
        )
        annotations = self.client.fetch_annotations(session_id)
        result = self.client.to_hitl_result(annotations, status)
        result.gate_id = session_id
        result.path = f"plannotator://sessions/{session_id}"
        return result

    def gate_brief(self, brief: Any) -> HITLResult:
        return self.gate("brief", {"brief": _jsonable(brief)})

    def gate_evidence(self, evidence_refs: Any) -> HITLResult:
        return self.gate("evidence", {"evidence_refs": _jsonable(evidence_refs)})

    def gate_report(self, report_md: str) -> HITLResult:
        return self.gate("report", {"report_md": str(report_md)})

    def _markdown_gate(self, gate_name: str, payload: dict) -> HITLResult:
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        gate_id = f"hitl-{gate_name}-{uuid4().hex[:10]}"
        path = self.queue_dir / f"{gate_id}.md"
        path.write_text(_render_markdown_gate(gate_id, gate_name, payload), encoding="utf-8")

        deadline = time.monotonic() + self.timeout_seconds
        result = _read_markdown_result(path)
        while result.status == "pending" and time.monotonic() < deadline:
            time.sleep(self.poll_interval_seconds)
            result = _read_markdown_result(path)
        result.gate_id = gate_id
        result.path = str(path)
        return result


def _render_markdown_gate(gate_id: str, gate_name: str, payload: dict) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    now = datetime.now(timezone.utc).isoformat()
    return (
        "---\n"
        f"id: {gate_id}\n"
        f"gate: {gate_name}\n"
        "status: pending\n"
        "annotations: []\n"
        "comments: []\n"
        f"created_at: {now}\n"
        "---\n\n"
        f"# HITL Gate: {gate_name}\n\n"
        "Set `status` in frontmatter to `approved` or `changes_requested`.\n\n"
        "```json\n"
        f"{payload_json}\n"
        "```\n"
    )


def _read_markdown_result(path: Path) -> HITLResult:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    frontmatter = _parse_frontmatter(text)
    status = str(frontmatter.get("status") or "pending").strip()
    if status not in VALID_STATUSES:
        status = "pending"
    return HITLResult(
        status=status,
        annotations=_coerce_list(frontmatter.get("annotations")),
        comments=[str(item) for item in _coerce_list(frontmatter.get("comments"))],
        gate_id=str(frontmatter.get("id") or ""),
        path=str(path),
    )


def _parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    try:
        raw = text.split("---", 2)[1]
    except IndexError:
        return {}
    data: dict[str, Any] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = _parse_scalar(value.strip())
    return data


def _parse_scalar(value: str) -> Any:
    if value in {"[]", ""}:
        return []
    if value.startswith("[") and value.endswith("]"):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else value
        except json.JSONDecodeError:
            return value
    return value.strip("\"'")


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return {
            key: _jsonable(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value
