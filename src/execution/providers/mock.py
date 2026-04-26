"""Mock provider for API-key-free tests."""

from __future__ import annotations

from src.execution.models import ModelResult


class MockProvider:
    name = "mock"

    def __init__(self, response: str = "mock response", *, model: str = "mock", cost_usd: float = 0.0) -> None:
        self.response = response
        self.model = model
        self.cost_usd = float(cost_usd)

    def call(self, stage: str, prompt: str, **kwargs: object) -> ModelResult:
        return ModelResult(
            text=self.response,
            provider=self.name,
            model=self.model,
            cost_usd=self.cost_usd,
            raw={"stage": stage, "prompt": prompt, "kwargs": kwargs},
        )
