"""OpenAI provider wrapper."""

from __future__ import annotations

import os
from typing import Any

from src.execution.models import ModelResult

try:  # pragma: no cover - availability depends on local environment.
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]


class OpenAIProvider:
    name = "openai"

    def __init__(
        self,
        model: str = os.environ.get("MUCHANIPO_OPENAI_MODEL", "gpt-5.5"),
        api_key: str | None = None,
        client: Any = None,
    ) -> None:
        self.model = model
        self.client = client
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        client = self.client
        if client is None:
            if OpenAI is None:
                raise RuntimeError("openai package is not installed")
            client = OpenAI(api_key=self.api_key)
        model = kwargs.pop("model", self.model)
        response = client.responses.create(
            model=model,
            input=prompt,
            **kwargs,
        )
        text = getattr(response, "output_text", "") or str(response)
        return ModelResult(text=text, provider=self.name, model=model, raw=response)
