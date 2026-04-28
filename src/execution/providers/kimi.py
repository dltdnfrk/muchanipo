"""Moonshot Kimi K2.6 provider — offline-safe stub.

Real Moonshot API (api.moonshot.cn) compatible — when KIMI_API_KEY is unset
or KIMI_OFFLINE=1, returns deterministic mock responses for tests.
"""

from __future__ import annotations

import json
import os
from typing import Any

from src.execution.models import ModelResult

try:  # pragma: no cover - 외부 의존성 optional.
    import urllib.request
    import urllib.error
    _HAVE_URLLIB = True
except Exception:  # pragma: no cover
    _HAVE_URLLIB = False


_DEFAULT_MODEL = "kimi-k2-0711-preview"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_HTTP_TIMEOUT_SEC = _env_int("MUCHANIPO_KIMI_TIMEOUT_SEC", 30)


class KimiProvider:
    name = "kimi"

    def __init__(
        self,
        model: str = os.environ.get("MUCHANIPO_KIMI_MODEL", _DEFAULT_MODEL),
        api_key: str | None = None,
        endpoint: str = "",
        offline: bool | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("KIMI_API_KEY") or os.environ.get("MOONSHOT_API_KEY")
        self.endpoint = endpoint or os.environ.get("KIMI_ENDPOINT", "https://api.moonshot.cn/v1/chat/completions")
        if offline is None:
            offline = bool(os.environ.get("KIMI_OFFLINE")) or self.api_key is None
        self.offline = offline

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        if self.offline:
            return _mock_result(stage, prompt, model=self.model, provider=self.name)
        return self._call_real(stage, prompt, **kwargs)

    def _call_real(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:  # pragma: no cover - 네트워크
        if not _HAVE_URLLIB:
            raise RuntimeError("urllib not available for kimi provider")
        body = json.dumps({
            "model": kwargs.pop("model", self.model),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": int(kwargs.pop("max_tokens", 1024)),
            "temperature": float(kwargs.pop("temperature", 0.6)),
        }).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        text = ""
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            text = json.dumps(payload)
        usage = payload.get("usage", {}) or {}
        cost = _estimate_cost(usage)
        return ModelResult(
            text=text,
            provider=self.name,
            model=self.model,
            cost_usd=cost,
            raw=payload,
        )


def _estimate_cost(usage: dict) -> float:
    """K2 pricing approx: $0.55 / 1M input, $2.20 / 1M output."""
    inp = float(usage.get("prompt_tokens", 0) or 0)
    out = float(usage.get("completion_tokens", 0) or 0)
    return (inp / 1_000_000) * 0.55 + (out / 1_000_000) * 2.20


def _mock_result(stage: str, prompt: str, *, model: str, provider: str) -> ModelResult:
    snippet = prompt[:60].replace("\n", " ")
    text = f"[mock-{provider}/{stage}] {snippet}"
    return ModelResult(text=text, provider=provider, model=model, cost_usd=0.0)
