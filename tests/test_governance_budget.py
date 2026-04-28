from concurrent.futures import ThreadPoolExecutor

import pytest

from src.governance.audit import AuditLog
from src.governance.budget import BudgetExceeded, RunBudget
from src.governance.profiles import resolve_profile


def test_run_budget_reserve_reconcile_log(tmp_path):
    budget = RunBudget(limit_usd=1.0, cost_log_path=tmp_path / "cost-log.jsonl")
    rid = budget.reserve(stage="report", estimated_usd=0.25)

    budget.reconcile(rid, actual_usd=0.10)

    assert budget.total_actual_usd == 0.10
    assert budget.records[0].stage == "report"
    assert "reconciled" in (tmp_path / "cost-log.jsonl").read_text(encoding="utf-8")


def test_budget_exceeded_returns_false_and_logs(tmp_path):
    budget = RunBudget(limit_usd=0.1, cost_log_path=tmp_path / "cost-log.jsonl")

    assert budget.reserve(stage="council", estimated_usd=0.2) is False

    assert "reserve_rejected" in (tmp_path / "cost-log.jsonl").read_text(encoding="utf-8")


def test_budget_exceeded_can_still_raise_for_legacy_callers(tmp_path):
    budget = RunBudget(
        limit_usd=0.1,
        cost_log_path=tmp_path / "cost-log.jsonl",
        raise_on_exceeded=True,
    )

    with pytest.raises(BudgetExceeded):
        budget.reserve(stage="council", estimated_usd=0.2)


def test_budget_reserve_is_atomic_under_race(tmp_path):
    budget = RunBudget(limit_usd=0.5, cost_log_path=tmp_path / "cost-log.jsonl")

    def reserve_one():
        return budget.reserve(stage="race", estimated_usd=0.1) is not False

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(lambda _: reserve_one(), range(12)))

    assert results.count(True) == 5
    assert budget.total_estimated_usd == pytest.approx(0.5)


def test_estimate_uses_provider_rate():
    provider = type("Provider", (), {"rate_per_1k_chars": 0.2})()
    budget = RunBudget(limit_usd=1.0)

    assert budget.estimate(stage="x", prompt="x" * 500, provider=provider) == 0.1


def test_reconcile_unknown_reservation_raises():
    budget = RunBudget(limit_usd=1.0)

    with pytest.raises(KeyError):
        budget.reconcile("missing", actual_usd=0.1)


def test_audit_log_records_call_fields(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")

    record = log.record_call(
        stage="council",
        provider="mock",
        model="mock",
        cost_usd=0.0,
        fallback_reason="primary failed",
    )

    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert record.stage == "council"
    assert "primary failed" in text


def test_default_profile_is_dev(monkeypatch):
    monkeypatch.delenv("MUCHANIPO_PROFILE", raising=False)

    assert resolve_profile().name == "dev"


def test_unknown_profile_raises(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_PROFILE", "nope")

    with pytest.raises(ValueError):
        resolve_profile()
