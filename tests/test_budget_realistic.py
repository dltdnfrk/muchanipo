import pytest

from src.eval.budget_simulator import render_markdown_report
from src.execution.gateway_v2 import GatewayV2
from src.execution.models import ModelResult
from src.governance.budget import RunBudget
from src.governance.cost_simulator import simulate_research_cost


def test_run_budget_estimates_model_prices_by_stage():
    budget = RunBudget(max_usd=1.0)
    prompt = "x" * 4000

    council = budget.estimate(stage="council", prompt=prompt, provider="anthropic")
    research = budget.estimate(stage="research", prompt=prompt, provider="gemini")

    assert council == pytest.approx(0.135)
    assert research == pytest.approx(0.000525)


@pytest.mark.parametrize(
    "brief",
    [
        "Korean smart-farm distribution plan for paprika growers",
        "US FDA go-to-market research for microbiome diagnostics",
        "Japan senior care robotics willingness-to-pay analysis",
        "EU carbon farming software buyer discovery",
    ],
)
def test_research_cost_scenarios_fit_half_dollar_goal(brief):
    result = simulate_research_cost(brief)

    assert result["budget_ok"] is True
    assert result["total_usd"] < 0.5
    assert set(result["breakdown"]) >= {"council", "research", "evidence", "report"}


def test_budget_limit_triggers_gateway_fallback_chain(tmp_path):
    budget = RunBudget(max_usd=0.001, cost_log_path=tmp_path / "cost-log.jsonl")
    gateway = GatewayV2(
        providers={
            "anthropic": _SuccessProvider("anthropic", "claude-opus-4-7"),
            "gemini": _SuccessProvider("gemini", "gemini-2.5-flash"),
        },
        stage_routes={"council": "anthropic"},
        fallback_chain={"council": ["anthropic", "gemini"]},
        budget=budget,
    )

    result = gateway.call("council", "x" * 1000)

    assert result.provider == "gemini"
    assert result.is_fallback is True
    assert "budget exceeded" in (result.fallback_reason or "")
    assert gateway.fallback_events[0]["provider"] == "anthropic"


def test_reserve_reconcile_status_uses_actual_cost_for_remaining_budget(tmp_path):
    budget = RunBudget(max_usd=0.5, cost_log_path=tmp_path / "cost-log.jsonl")
    first = budget.reserve(stage="council", estimated_usd=0.4)
    assert first is not False

    budget.reconcile(str(first), actual_usd=0.1)
    second = budget.reserve(stage="research", estimated_usd=0.35)

    assert second is not False
    status = budget.status()
    assert status["reserved_usd"] == pytest.approx(0.45)
    assert status["remaining_usd"] == pytest.approx(0.05)
    assert status["breakdown"]["council"]["actual_usd"] == pytest.approx(0.1)


def test_budget_simulator_renders_markdown_report():
    report = render_markdown_report("Korea agtech market entry", num_rounds=2, num_personas=2)

    assert "# Budget Simulation" in report
    assert "Council routing" in report
    assert "Single Opus" in report


class _SuccessProvider:
    def __init__(self, name: str, model: str):
        self.name = name
        self.model = model

    def call(self, stage: str, prompt: str, **kwargs):
        return ModelResult(text=f"ok-{self.name}", provider=self.name, model=self.model)
