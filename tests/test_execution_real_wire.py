from src.execution.models import ModelGateway, ModelResult
from src.execution.providers.anthropic import AnthropicProvider
from src.execution.providers.mock import MockProvider
from src.execution.providers.ollama import OllamaProvider
from src.execution.providers.openai import OpenAIProvider
from src.governance.audit import AuditLog
from src.governance.budget import RunBudget
from src.governance.profiles import resolve_profile


def test_stage_routes_select_named_provider():
    gateway = ModelGateway(
        providers={
            "fast": MockProvider(response="fast"),
            "deep": MockProvider(response="deep"),
        },
        stage_routes={"council": "deep"},
    )

    result = gateway.call(stage="council", prompt="debate")

    assert result.text == "deep"


def test_gateway_keeps_single_provider_compatibility():
    gateway = ModelGateway(provider=MockProvider(response="ok"))

    assert gateway.call(stage="report", prompt="hello").provider == "mock"


def test_gateway_falls_back_and_records_reason():
    class BrokenProvider:
        name = "broken"

        def call(self, stage, prompt, **kwargs):
            raise RuntimeError("primary failed")

    gateway = ModelGateway(
        provider=BrokenProvider(),
        fallback_provider=MockProvider(response="fallback"),
    )

    result = gateway.call(stage="council", prompt="hello")

    assert result.text == "fallback"
    assert result.is_fallback is True
    assert result.fallback_reason == "primary failed"


def test_gateway_budget_and_audit_hooks(tmp_path):
    budget = RunBudget(limit_usd=1.0, cost_log_path=tmp_path / "cost-log.jsonl")
    audit = AuditLog(tmp_path / "audit-log.jsonl")
    gateway = ModelGateway(provider=MockProvider(response="ok", cost_usd=0.02), budget=budget, audit=audit)

    result = gateway.call(stage="report", prompt="hello")

    assert result.cost_usd == 0.02
    assert budget.total_actual_usd == 0.02
    assert "report" in (tmp_path / "audit-log.jsonl").read_text(encoding="utf-8")
    cost_log = (tmp_path / "cost-log.jsonl").read_text(encoding="utf-8")
    assert '"provider": "mock"' in cost_log
    assert '"model": "mock"' in cost_log


def test_gateway_fallback_budget_records_actual_provider_metadata(tmp_path):
    class BrokenProvider:
        name = "broken"

        def call(self, stage, prompt, **kwargs):
            raise RuntimeError("primary failed")

    budget = RunBudget(limit_usd=1.0, cost_log_path=tmp_path / "cost-log.jsonl")
    gateway = ModelGateway(
        provider=BrokenProvider(),
        fallback_provider=MockProvider(response="fallback", cost_usd=0.01),
        budget=budget,
    )

    result = gateway.call(stage="report", prompt="hello")

    assert result.provider == "mock"
    records = budget.records
    assert records[0].provider == "broken"
    assert records[0].status == "reconciled"
    assert records[1].provider == "mock"
    assert records[1].model == "mock"


def test_openai_provider_uses_injected_client():
    class Responses:
        def create(self, **kwargs):
            self.kwargs = kwargs
            return type("Response", (), {"output_text": "openai text"})()

    responses = Responses()
    client = type("Client", (), {"responses": responses})()

    result = OpenAIProvider(client=client).call(stage="research", prompt="question", model="gpt-custom")

    assert result.text == "openai text"
    assert result.provider == "openai"
    assert result.model == "gpt-custom"
    assert responses.kwargs["model"] == "gpt-custom"


def test_anthropic_provider_uses_injected_client():
    class Messages:
        def create(self, **kwargs):
            item = type("Content", (), {"text": "anthropic text"})()
            return type("Message", (), {"content": [item]})()

    client = type("Client", (), {"messages": Messages()})()

    result = AnthropicProvider(client=client).call(stage="council", prompt="question")

    assert result.text == "anthropic text"
    assert result.provider == "anthropic"


def test_ollama_provider_parses_generate_response(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"response": "ollama text"}'

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout: Response())

    result = OllamaProvider(model="local").call(stage="draft", prompt="hello")

    assert result.text == "ollama text"
    assert result.model == "local"


def test_profile_env_takes_precedence(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_PROFILE", "staging")

    assert resolve_profile("dev").name == "staging"
