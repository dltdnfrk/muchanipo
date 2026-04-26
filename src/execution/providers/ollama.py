"""Ollama local provider wrapper."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from src.execution.models import ModelResult


class OllamaProvider:
    name = "ollama"

    def __init__(self, model: str = "llama3.1", host: str | None = None, timeout: float = 120.0) -> None:
        self.model = model
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
        self.timeout = timeout

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        payload = {
            "model": kwargs.pop("model", self.model),
            "prompt": prompt,
            "stream": False,
        }
        payload.update(kwargs)
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.host}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
        return ModelResult(
            text=str(raw.get("response", "")),
            provider=self.name,
            model=str(payload["model"]),
            raw=raw,
        )
