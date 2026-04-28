"""HTTP client for Plannotator-backed HITL reviews."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from uuid import uuid4

from src.hitl.plannotator_adapter import HITLResult, VALID_STATUSES


DEFAULT_ENDPOINT = "https://plannotator.ai/api"
DEFAULT_TIMEOUT_SEC = 30.0
DEFAULT_POLL_INTERVAL_SEC = 2.0


class PlannotatorError(RuntimeError):
    """Raised when the Plannotator API returns an unusable response."""


class PlannotatorClient:
    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        api_key: str | None = None,
        offline: bool | None = None,
    ) -> None:
        self.endpoint = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("PLANNOTATOR_API_KEY")
        self.offline = _offline_enabled(offline, self.api_key)
        self._offline_sessions: set[str] = set()

    def create_session(self, payload: dict) -> str:
        """POST /sessions -> session_id."""
        if self.offline:
            session_id = f"offline-{uuid4().hex[:12]}"
            self._offline_sessions.add(session_id)
            return session_id
        self._ensure_api_key()

        data = self._request("POST", "/sessions", payload)
        session_id = data.get("session_id") or data.get("id")
        if not session_id:
            raise PlannotatorError("Plannotator session response did not include session_id")
        return str(session_id)

    def fetch_annotations(self, session_id: str) -> list[dict]:
        """GET /sessions/{id}/annotations -> [{type, target, instruction, ...}]."""
        if self.offline:
            return []
        self._ensure_api_key()

        data = self._request("GET", f"/sessions/{_quote(session_id)}/annotations")
        annotations = data.get("annotations") if isinstance(data, dict) else data
        if annotations is None:
            return []
        if not isinstance(annotations, list):
            raise PlannotatorError("Plannotator annotations response was not a list")
        return [item for item in annotations if isinstance(item, dict)]

    def get_status(self, session_id: str) -> str:
        """GET /sessions/{id}/status -> 'pending'|'approved'|'changes_requested'."""
        if self.offline:
            return "approved"
        self._ensure_api_key()

        data = self._request("GET", f"/sessions/{_quote(session_id)}/status")
        status = data.get("status") if isinstance(data, dict) else data
        status = str(status or "").strip()
        if status not in VALID_STATUSES:
            raise PlannotatorError(f"invalid Plannotator status: {status}")
        return status

    def poll_until_decision(
        self,
        session_id: str,
        timeout_sec: float = 86400,
        poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
    ) -> str:
        """Poll until status is no longer pending."""
        if self.offline:
            time.sleep(0.5)
            return "approved"
        self._ensure_api_key()

        deadline = time.monotonic() + max(0.0, float(timeout_sec))
        interval = max(0.01, float(poll_interval_sec))
        while True:
            status = self.get_status(session_id)
            if status != "pending":
                return status
            if time.monotonic() >= deadline:
                return "pending"
            time.sleep(min(interval, max(0.0, deadline - time.monotonic())))

    def to_hitl_result(self, annotations: list[dict], status: str) -> HITLResult:
        """Convert Plannotator annotations into agent-consumable HITL JSON."""
        normalized_annotations = [_normalize_annotation(item) for item in annotations]
        comments = [
            str(item["instruction"])
            for item in normalized_annotations
            if item.get("instruction")
        ]
        return HITLResult(
            status=status,
            annotations=normalized_annotations,
            comments=comments,
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = urllib.request.Request(
            url=f"{self.endpoint}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SEC) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PlannotatorError(f"Plannotator HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise PlannotatorError(f"Plannotator request failed: {exc.reason}") from exc

        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise PlannotatorError("Plannotator response was not valid JSON") from exc

    def _ensure_api_key(self) -> None:
        if not self.api_key:
            raise PlannotatorError("no api key")


def _offline_enabled(offline: bool | None, api_key: str | None) -> bool:
    if offline is not None:
        return bool(offline)
    flag = os.getenv("PLANNOTATOR_OFFLINE", "")
    if flag.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return False


def _quote(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


def _normalize_annotation(annotation: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(annotation)
    normalized["type"] = str(normalized.get("type") or "comment")
    normalized["target"] = normalized.get("target") or ""
    normalized["instruction"] = str(normalized.get("instruction") or "")
    return normalized
