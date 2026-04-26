"""Run-level budget ledger for the entire pipeline."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class BudgetExceeded(ValueError):
    """Raised when a reservation would exceed the run budget."""


@dataclass
class BudgetRecord:
    reservation_id: str
    stage: str
    estimated_usd: float
    actual_usd: float | None = None
    provider: str | None = None
    model: str | None = None
    status: str = "reserved"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reconciled_at: str | None = None


@dataclass
class RunBudget:
    limit_usd: float
    cost_log_path: str | Path = "vault/cost-log.jsonl"
    records: list[BudgetRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.limit_usd = float(self.limit_usd)
        self.cost_log_path = Path(self.cost_log_path)
        self._lock = threading.Lock()

    def estimate(
        self,
        *,
        stage: str,
        prompt: str,
        provider: Any = None,
        model: str | None = None,
        rate_per_1k_chars: float | None = None,
    ) -> float:
        if rate_per_1k_chars is None:
            rate_per_1k_chars = float(getattr(provider, "rate_per_1k_chars", 0.0) or 0.0)
        return round((max(len(prompt), 1) / 1000.0) * float(rate_per_1k_chars), 8)

    def reserve(
        self,
        stage: str,
        estimated_usd: float,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> str:
        estimated = float(estimated_usd)
        with self._lock:
            if self.total_estimated_usd + estimated > self.limit_usd:
                record = BudgetRecord(
                    reservation_id=str(uuid4()),
                    stage=stage,
                    estimated_usd=estimated,
                    provider=provider,
                    model=model,
                    status="rejected",
                )
                self._append_log(record, event="reserve_rejected")
                raise BudgetExceeded("budget exceeded")
            rid = str(uuid4())
            self.records.append(
                BudgetRecord(
                    reservation_id=rid,
                    stage=stage,
                    estimated_usd=estimated,
                    provider=provider,
                    model=model,
                )
            )
            self._append_log(self.records[-1], event="reserved")
            return rid

    def dispatch(self, provider: Any, *, stage: str, prompt: str, **kwargs: Any) -> Any:
        return provider.call(stage=stage, prompt=prompt, **kwargs)

    def reconcile(self, reservation_id: str, actual_usd: float) -> None:
        with self._lock:
            for record in self.records:
                if record.reservation_id == reservation_id:
                    record.actual_usd = float(actual_usd)
                    record.status = "reconciled"
                    record.reconciled_at = datetime.now(timezone.utc).isoformat()
                    self._append_log(record, event="reconciled")
                    return
        raise KeyError(reservation_id)

    @property
    def total_estimated_usd(self) -> float:
        return sum(r.estimated_usd for r in self.records)

    @property
    def total_actual_usd(self) -> float:
        return sum(r.actual_usd or 0.0 for r in self.records)

    def _append_log(self, record: BudgetRecord, *, event: str) -> None:
        self.cost_log_path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(record)
        payload["event"] = event
        payload["logged_at"] = datetime.now(timezone.utc).isoformat()
        with self.cost_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
