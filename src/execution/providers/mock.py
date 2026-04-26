"""Mock provider for API-key-free tests."""
from __future__ import annotations

from src.execution.models import ModelResult


class MockProvider:
    name = "mock"

    def __init__(self, response: str = "mock response") -> None:
        self.response = response

    def call(self, *, stage: str, prompt: str, **kwargs) -> ModelResult:
        return ModelResult(text=self.response, provider=self.name, model="mock")
