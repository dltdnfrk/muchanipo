"""Run-level budget ledger for the entire pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class BudgetRecord:
    reservation_id: str
    stage: str
    estimated_usd: float
    actual_usd: float | None = None


@dataclass
class RunBudget:
    limit_usd: float
    records: list[BudgetRecord] = field(default_factory=list)

    def reserve(self, *, stage: str, estimated_usd: float) -> str:
        if self.total_estimated_usd + estimated_usd > self.limit_usd:
            raise ValueError("budget exceeded")
        rid = str(uuid4())
        self.records.append(BudgetRecord(reservation_id=rid, stage=stage, estimated_usd=estimated_usd))
        return rid

    def reconcile(self, reservation_id: str, *, actual_usd: float) -> None:
        for record in self.records:
            if record.reservation_id == reservation_id:
                record.actual_usd = actual_usd
                return
        raise KeyError(reservation_id)

    @property
    def total_estimated_usd(self) -> float:
        return sum(r.estimated_usd for r in self.records)

    @property
    def total_actual_usd(self) -> float:
        return sum(r.actual_usd or 0.0 for r in self.records)
