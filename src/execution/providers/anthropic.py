"""Anthropic provider wrapper."""

from __future__ import annotations

import os
from typing import Any

from src.execution.models import ModelResult

try:  # pragma: no cover - availability depends on local environment.
    from anthropic import Anthropic
except ImportError:  # pragma: no cover
    Anthropic = None  # type: ignore[assignment]


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-5", api_key: str | None = None, client: Any = None) -> None:
        self.model = model
        self.client = client
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        client = self.client
        if client is None:
            if Anthropic is None:
                raise RuntimeError("anthropic package is not installed")
            client = Anthropic(api_key=self.api_key)
        message = client.messages.create(
            model=kwargs.pop("model", self.model),
            max_tokens=int(kwargs.pop("max_tokens", 1024)),
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        text = _content_text(message)
        return ModelResult(text=text, provider=self.name, model=self.model, raw=message)


def _content_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for item in content or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(str(text))
    return "\n".join(parts)
