"""Audit records for pipeline operations."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class AuditRecord:
    stage: str
    action: str
    provider: str | None = None
    model: str | None = None
    estimated_usd: float | None = None
    actual_usd: float | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
