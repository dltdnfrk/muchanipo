from src.agents.generator import DebateAgentSpec
from src.council.session import CouncilSession
from src.execution.models import ModelGateway
from src.execution.providers.mock import MockProvider
from src.governance.budget import RunBudget


def test_model_gateway_uses_mock_provider_without_router_package():
    gateway = ModelGateway(provider=MockProvider(response="ok"))
    result = gateway.call(stage="council", prompt="hello")
    assert result.text == "ok"
    assert result.provider == "mock"


def test_run_budget_reserve_reconcile_log():
    budget = RunBudget(limit_usd=1.0)
    rid = budget.reserve(stage="report", estimated_usd=0.25)
    budget.reconcile(rid, actual_usd=0.10)
    assert budget.total_actual_usd == 0.10
    assert budget.records[0].stage == "report"


def test_council_session_runs_one_mock_round():
    agents = [DebateAgentSpec(name="mirofish", role="critic", perspective="skeptical", expertise=["evidence"], challenge_targets=["claims"], source_report_id="r1", system_prompt="find gaps")]
    session = CouncilSession(report_id="r1", agents=agents)
    session.run_round(model_gateway=ModelGateway(provider=MockProvider(response="critique")))
    assert session.rounds[0]["responses"][0]["text"] == "critique"
    assert session.next_actions
