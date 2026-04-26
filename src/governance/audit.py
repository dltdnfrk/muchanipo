"""Append-only audit logging for model calls."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class AuditRecord:
    stage: str
    provider: str
    model: str
    cost_usd: float
    fallback_reason: str | None = None
    created_at: str = ""


class AuditLog:
    def __init__(self, path: str | Path = "vault/audit-log.jsonl") -> None:
        self.path = Path(path)

    def record_call(
        self,
        *,
        stage: str,
        provider: str,
        model: str,
        cost_usd: float,
        fallback_reason: str | None = None,
    ) -> AuditRecord:
        record = AuditRecord(
            stage=stage,
            provider=provider,
            model=model,
            cost_usd=float(cost_usd),
            fallback_reason=fallback_reason,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")
        return record
