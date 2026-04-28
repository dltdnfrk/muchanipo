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


PRICE_PER_M_INPUT = {
    "claude-opus-4-7": 15.00,
    "claude-sonnet-4-6": 3.00,
    "claude-sonnet-4-5": 3.00,
    "claude-haiku-4-5": 0.25,
    "gemini-2.5-pro": 2.50,
    "gemini-2.5-flash": 0.075,
    "kimi-k2-0711-preview": 0.55,
    "gpt-5.5": 2.00,
    "mock": 0.0,
}

PRICE_PER_M_OUTPUT = {
    model: price * 4.0 for model, price in PRICE_PER_M_INPUT.items()
}

STAGE_OUTPUT_MULTIPLIER = {
    "intake": 0.6,
    "interview": 1.2,
    "targeting": 0.8,
    "research": 1.5,
    "evidence": 1.0,
    "council": 2.0,
    "consensus": 1.6,
    "report": 2.4,
    "eval": 1.0,
    "ingest": 0.5,
}

STAGE_PROVIDER_MODELS = {
    ("intake", "gemini"): "gemini-2.5-flash",
    ("interview", "anthropic"): "claude-sonnet-4-6",
    ("targeting", "gemini"): "gemini-2.5-flash",
    ("research", "gemini"): "gemini-2.5-flash",
    ("research", "kimi"): "kimi-k2-0711-preview",
    ("evidence", "kimi"): "kimi-k2-0711-preview",
    ("council", "anthropic"): "claude-opus-4-7",
    ("consensus", "anthropic"): "claude-opus-4-7",
    ("report", "anthropic"): "claude-sonnet-4-6",
    ("eval", "codex"): "gpt-5.5",
    ("mock", "mock"): "mock",
}

PROVIDER_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "gemini": "gemini-2.5-flash",
    "kimi": "kimi-k2-0711-preview",
    "codex": "gpt-5.5",
    "openai": "gpt-5.5",
    "mock": "mock",
}


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


@dataclass(init=False)
class RunBudget:
    limit_usd: float
    cost_log_path: Path
    records: list[BudgetRecord]
    raise_on_exceeded: bool

    def __init__(
        self,
        limit_usd: float | None = None,
        *,
        max_usd: float | None = None,
        cost_log_path: str | Path = "vault/cost-log.jsonl",
        records: list[BudgetRecord] | None = None,
        raise_on_exceeded: bool = False,
    ) -> None:
        if limit_usd is None and max_usd is None:
            raise TypeError("RunBudget requires limit_usd or max_usd")
        if limit_usd is not None and max_usd is not None and float(limit_usd) != float(max_usd):
            raise ValueError("limit_usd and max_usd must match when both are provided")
        self.limit_usd = float(max_usd if max_usd is not None else limit_usd)
        self.cost_log_path = Path(cost_log_path)
        self.records = list(records or [])
        self.raise_on_exceeded = bool(raise_on_exceeded)
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
        resolved_model = resolve_model(stage=stage, provider=provider, model=model)
        if resolved_model in PRICE_PER_M_INPUT:
            input_tokens = estimate_input_tokens(prompt)
            output_tokens = estimate_output_tokens(input_tokens, stage)
            return estimate_cost_usd(resolved_model, input_tokens, output_tokens)

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
        raise_on_exceeded: bool | None = None,
    ) -> str | bool:
        estimated = float(estimated_usd)
        with self._lock:
            if self.reserved_usd + estimated > self.limit_usd:
                record = BudgetRecord(
                    reservation_id=str(uuid4()),
                    stage=stage,
                    estimated_usd=estimated,
                    provider=provider,
                    model=model,
                    status="rejected",
                )
                self._append_log(record, event="reserve_rejected")
                should_raise = self.raise_on_exceeded if raise_on_exceeded is None else raise_on_exceeded
                if should_raise:
                    raise BudgetExceeded("budget exceeded")
                return False
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

    @property
    def reserved_usd(self) -> float:
        return sum(r.actual_usd if r.actual_usd is not None else r.estimated_usd for r in self.records)

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.limit_usd - self.reserved_usd)

    def status(self) -> dict[str, Any]:
        breakdown: dict[str, dict[str, Any]] = {}
        for record in self.records:
            stage = breakdown.setdefault(
                record.stage,
                {
                    "estimated_usd": 0.0,
                    "actual_usd": 0.0,
                    "reserved_usd": 0.0,
                    "count": 0,
                    "reconciled": 0,
                },
            )
            stage["estimated_usd"] += record.estimated_usd
            stage["actual_usd"] += record.actual_usd or 0.0
            stage["reserved_usd"] += record.actual_usd if record.actual_usd is not None else record.estimated_usd
            stage["count"] += 1
            if record.status == "reconciled":
                stage["reconciled"] += 1
        for stage in breakdown.values():
            for key in ("estimated_usd", "actual_usd", "reserved_usd"):
                stage[key] = round(stage[key], 8)
        return {
            "max_usd": self.limit_usd,
            "limit_usd": self.limit_usd,
            "reserved_usd": round(self.reserved_usd, 8),
            "remaining_usd": round(self.remaining_usd, 8),
            "total_estimated_usd": round(self.total_estimated_usd, 8),
            "total_actual_usd": round(self.total_actual_usd, 8),
            "breakdown": breakdown,
        }

    def _append_log(self, record: BudgetRecord, *, event: str) -> None:
        self.cost_log_path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(record)
        payload["event"] = event
        payload["logged_at"] = datetime.now(timezone.utc).isoformat()
        with self.cost_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def estimate_input_tokens(prompt: str) -> int:
    return max(len(prompt) // 4, 1)


def estimate_output_tokens(input_tokens: int, stage: str) -> int:
    multiplier = STAGE_OUTPUT_MULTIPLIER.get(stage, 1.0)
    return max(int(round(input_tokens * multiplier)), 1)


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    input_price = PRICE_PER_M_INPUT.get(model, 0.0)
    output_price = PRICE_PER_M_OUTPUT.get(model, input_price * 4.0)
    cost = (input_tokens / 1_000_000.0) * input_price
    cost += (output_tokens / 1_000_000.0) * output_price
    return round(cost, 8)


def provider_name(provider: Any) -> str | None:
    if provider is None:
        return None
    if isinstance(provider, str):
        return provider
    return getattr(provider, "name", None)


def resolve_model(*, stage: str, provider: Any = None, model: str | None = None) -> str | None:
    if model:
        return model
    name = provider_name(provider)
    if name:
        stage_model = STAGE_PROVIDER_MODELS.get((stage, name))
        if stage_model:
            return stage_model
    provider_model = getattr(provider, "model", None)
    if provider_model:
        return str(provider_model)
    if name:
        return PROVIDER_DEFAULT_MODELS.get(name)
    return None
