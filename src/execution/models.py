"""Model gateway support layer. This is intentionally not a top-level router."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ModelResult:
    text: str
    provider: str
    model: str = "mock"
    cost_usd: float = 0.0
    is_fallback: bool = False


class Provider(Protocol):
    name: str

    def call(self, *, stage: str, prompt: str, **kwargs) -> ModelResult:
        ...


class ModelGateway:
    def __init__(self, provider: Provider):
        self.provider = provider

    def call(self, *, stage: str, prompt: str, **kwargs) -> ModelResult:
        return self.provider.call(stage=stage, prompt=prompt, **kwargs)
