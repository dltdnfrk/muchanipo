"""Google Gemini provider — offline-safe stub.

REST API form. Returns deterministic mock when GEMINI_API_KEY missing or
GEMINI_OFFLINE=1.
"""

from __future__ import annotations

import json
import os
from typing import Any

from src.execution.models import ModelResult


_DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        endpoint_template: str = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        offline: bool | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.endpoint_template = endpoint_template
        if offline is None:
            offline = bool(os.environ.get("GEMINI_OFFLINE")) or self.api_key is None
        self.offline = offline

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        if self.offline:
            return _mock_result(stage, prompt, model=self.model, provider=self.name)
        return self._call_real(stage, prompt, **kwargs)

    def _call_real(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:  # pragma: no cover
        import urllib.request

        url = self.endpoint_template.format(model=self.model) + f"?key={self.api_key}"
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": int(kwargs.pop("max_tokens", 1024)),
                "temperature": float(kwargs.pop("temperature", 0.6)),
            },
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        text = ""
        try:
            parts = payload["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError):
            text = json.dumps(payload)
        return ModelResult(text=text, provider=self.name, model=self.model, raw=payload)


def _mock_result(stage: str, prompt: str, *, model: str, provider: str) -> ModelResult:
    snippet = prompt[:60].replace("\n", " ")
    text = f"[mock-{provider}/{stage}] {snippet}"
    return ModelResult(text=text, provider=provider, model=model, cost_usd=0.0)
