"""Guards for product/live runs.

Offline and mock flows are still valid for tests and demos. When
``MUCHANIPO_REQUIRE_LIVE=1`` is set, the pipeline must fail loudly instead of
silently publishing mock model output or empty evidence as a product result.
"""
from __future__ import annotations

import os
import re
from typing import Any


class LiveModeViolation(RuntimeError):
    """Raised when product/live mode would degrade into a demo path."""


_TRUE_VALUES = {"1", "true", "yes", "on"}
_MOCK_TEXT_MARKERS = (
    "[mock-",
    "mock response",
    "mock council critique",
    "not a real autoresearch run",
    "mock-first skeleton",
    "No live evidence",
)


def require_live_mode() -> bool:
    return os.environ.get("MUCHANIPO_REQUIRE_LIVE", "").strip().lower() in _TRUE_VALUES


def live_requested_from_env() -> bool:
    return any(
        os.environ.get(name, "").strip().lower() in _TRUE_VALUES
        for name in ("MUCHANIPO_REQUIRE_LIVE", "MUCHANIPO_ONLINE", "MUCHANIPO_REAL_RESEARCH")
    )


def assert_live_model_result(stage: str, result: Any) -> None:
    """Reject model results that are clearly mock/demo placeholders."""
    provider = str(getattr(result, "provider", "") or "").lower()
    model = str(getattr(result, "model", "") or "").lower()
    text = str(getattr(result, "text", "") or "")
    if len(text.strip()) < 8:
        raise LiveModeViolation(f"live mode rejected empty or too-short model output at stage {stage!r}")
    lowered = text.lower()

    if provider == "mock" or model == "mock":
        raise LiveModeViolation(f"live mode rejected mock model result at stage {stage!r}")
    for marker in _MOCK_TEXT_MARKERS:
        if marker.lower() in lowered:
            raise LiveModeViolation(
                f"live mode rejected placeholder model output at stage {stage!r}: {marker}"
            )


def assert_live_evidence(evidence_summary: dict[str, Any], refs: list[Any]) -> None:
    """Require at least one trusted non-mock evidence record."""
    if not refs:
        raise LiveModeViolation("live mode requires at least one evidence record")

    rejected_kinds = {"mock", "empty", "placeholder", "stub"}
    for ref in refs:
        provenance = getattr(ref, "provenance", {}) or {}
        kind = str(provenance.get("kind", "") or "").lower()
        title = str(getattr(ref, "source_title", "") or "")
        grade = str(getattr(ref, "source_grade", "") or "").upper()
        source_url = str(getattr(ref, "source_url", "") or "").strip()
        provenance_source = str(provenance.get("source", "") or "").strip()
        if kind in rejected_kinds or grade == "D" or "No live evidence" in title:
            raise LiveModeViolation(
                f"live mode rejected non-live evidence record {getattr(ref, 'id', '<unknown>')}"
            )
        if not source_url and not provenance_source:
            raise LiveModeViolation(
                f"live mode requires source_url or provenance source for evidence record {getattr(ref, 'id', '<unknown>')}"
            )

    trusted_count = int(evidence_summary.get("trusted", 0) or 0)
    if trusted_count < 1:
        raise LiveModeViolation("live mode requires at least one trusted evidence record")


def assert_live_hitl(gate_name: str, result: Any) -> None:
    status = str(getattr(result, "status", "") or "")
    if status != "approved":
        raise LiveModeViolation(f"live mode requires approved HITL gate {gate_name!r}; got {status!r}")


def assert_live_report(report_md: str) -> None:
    lowered = report_md.lower()
    for marker in _MOCK_TEXT_MARKERS:
        if marker.lower() in lowered:
            raise LiveModeViolation(f"live mode rejected report marker: {marker}")
    if "## evidence index" not in lowered:
        raise LiveModeViolation("live mode requires an Evidence Index section in the report")
    if "## claim grounding matrix" not in lowered:
        raise LiveModeViolation("live mode requires a Claim Grounding Matrix section in the report")
    if not re.search(r"Evidence:\s*`[^`]+`", report_md):
        raise LiveModeViolation("live mode requires chapter claims with explicit evidence citations")
