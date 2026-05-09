"""Xiaomi MiMo provider — API-first OpenAI-compatible chat completions.

MiMo keys can be used through Xiaomi's OpenAI-compatible endpoints. The Python
provider defaults to Xiaomi's official API URL, while the Tauri desktop settings
may explicitly pass a Token Plan regional URL via ``MIMO_BASE_URL`` or
``XIAOMI_MIMO_BASE_URL``.
Muchanipo treats MiMo as an API provider, not a CLI provider: credentials come
only from explicit env vars or constructor injection and are never read from local
tool auth files.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable

from src.execution.models import ModelResult

_DEFAULT_MODEL = os.environ.get("MUCHANIPO_MIMO_MODEL") or os.environ.get("MIMO_MODEL") or "mimo-v2.5-pro"
_DEFAULT_OFFICIAL_BASE_URL = "https://api.xiaomimimo.com/v1"
_HTTP_TIMEOUT_SEC = int(os.environ.get("MUCHANIPO_MIMO_TIMEOUT_SEC", "60") or "60")
_MIMO_USER_AGENT = os.environ.get(
    "MUCHANIPO_MIMO_USER_AGENT",
    "Muchanipo/1.0 MiMo-Client/1.0",
)


def _resolve_api_key() -> str | None:
    """Resolve explicit MiMo API key env vars only."""

    for name in ("XIAOMI_MIMO_API_KEY", "MIMO_API_KEY"):
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    return None


def _resolve_base_url(api_key: str | None = None) -> str:
    explicit = os.environ.get("XIAOMI_MIMO_BASE_URL") or os.environ.get("MIMO_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    return _DEFAULT_OFFICIAL_BASE_URL


def _normalize_model_name(model: str | None) -> str:
    raw = (model or _DEFAULT_MODEL).strip()
    if "/" in raw:
        raw = raw.rsplit("/", 1)[-1]
    return raw.lower()


class MiMoProvider:
    name = "mimo"

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        base_url: str | None = None,
        offline: bool | None = None,
        prefer_cli: bool | None = None,  # accepted for factory parity; ignored.
    ) -> None:
        self.model = _normalize_model_name(model)
        self.api_key = (api_key or _resolve_api_key() or "").strip() or None
        self.base_url = (base_url or _resolve_base_url(self.api_key)).rstrip("/")
        self.use_cli = False
        if offline is None:
            offline = bool(os.environ.get("MIMO_OFFLINE") or os.environ.get("XIAOMI_MIMO_OFFLINE")) or self.api_key is None
        self.offline = offline

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        if self.offline:
            return _mock_result(stage, prompt, model=self.model, provider=self.name)
        return self._call_real(stage=stage, prompt=prompt, **kwargs)

    def _call_real(self, *, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        import urllib.error
        import urllib.request

        model = _normalize_model_name(kwargs.pop("model", self.model))
        stream_callback: Callable[[str], None] | None = kwargs.pop("stream_callback", None)
        max_tokens = int(kwargs.pop("max_completion_tokens", kwargs.pop("max_tokens", 1024)))
        temperature = float(kwargs.pop("temperature", 0.7))
        top_p = float(kwargs.pop("top_p", 0.95))
        timeout = int(kwargs.pop("timeout", _HTTP_TIMEOUT_SEC))

        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_completion_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "stream": False,
            "stop": kwargs.pop("stop", None),
            "frequency_penalty": float(kwargs.pop("frequency_penalty", 0)),
            "presence_penalty": float(kwargs.pop("presence_penalty", 0)),
            "thinking": kwargs.pop("thinking", {"disabled": True}),
        }
        system = kwargs.pop("system", None)
        if system:
            body["messages"].insert(0, {"role": "system", "content": str(system)})
        # Preserve forward compatibility for MiMo/OpenAI-compatible options without
        # leaking secrets; caller-owned extra fields go into JSON only.
        body.update(kwargs)

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                # The dedicated Token Plan endpoint is documented as
                # OpenAI-compatible, so authenticate like OpenAI clients do.
                # Keep Api-Key as a compatibility alias for older/internal
                # MiMo endpoints that accepted it.
                "Authorization": f"Bearer {self.api_key or ''}",
                "api-key": self.api_key or "",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": _MIMO_USER_AGENT,
            },
            method="POST",
        )
        print(
            f"muchanipo provider_call_start provider=mimo stage={stage} model={model} base_url={self.base_url}",
            file=sys.stderr,
            flush=True,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - live/network path
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                detail = ""
            raise RuntimeError(f"MiMo API HTTP {exc.code}: {detail}") from exc

        text = _response_text(payload)
        if stream_callback and text:
            stream_callback(text)
        return ModelResult(
            text=text,
            provider=self.name,
            model=str(payload.get("model") or model),
            cost_usd=0.0,
            raw=payload,
        )


def _response_text(payload: dict[str, Any]) -> str:
    try:
        return str(payload["choices"][0]["message"].get("content") or "")
    except (KeyError, IndexError, TypeError, AttributeError):
        return json.dumps(payload, ensure_ascii=False)


def _mock_result(stage: str, prompt: str, *, model: str, provider: str) -> ModelResult:
    excerpt = " ".join(prompt.split())[:120]
    return ModelResult(
        text=f"[mock-{provider}/{stage}] {excerpt}",
        provider=provider,
        model=model,
        cost_usd=0.0,
        raw={"mode": "offline"},
    )
