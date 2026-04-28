"""Anthropic provider wrapper — OAuth-aware, streaming, cost-tracking, fallback.

Supports three execution modes:
  1. CLI subprocess (`claude -p`) — uses local Claude Code OAuth, no API key.
  2. Anthropic SDK direct (ANTHROPIC_API_KEY).
  3. Offline mock.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Callable

from src.execution.models import ModelResult

try:  # pragma: no cover - availability depends on local environment.
    from anthropic import Anthropic
except ImportError:  # pragma: no cover
    Anthropic = None  # type: ignore[assignment, misc]

# Approximate pricing per 1M tokens (input / output) in USD.
# Updated periodically; used for cost_usd estimation.
_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-7": (15.0, 75.0),
    "claude-opus-4-6": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (0.25, 1.25),
    "claude-haiku-4-4": (0.25, 1.25),
}

FALLBACK_CHAIN = ("claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_DEFAULT_MODEL = os.environ.get("MUCHANIPO_ANTHROPIC_MODEL", "claude-sonnet-4-6")
_CLI_TIMEOUT_SEC = _env_int("MUCHANIPO_ANTHROPIC_CLI_TIMEOUT_SEC", 300)


def _resolve_api_key() -> str | None:
    """Check env vars and Claude Code OAuth token paths."""
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        val = os.environ.get(key)
        if val:
            return val
    # Claude Code OAuth token (best-effort)
    for path in (
        os.path.expanduser("~/.config/claude/settings.json"),
        os.path.expanduser("~/.claude/settings.json"),
    ):
        if os.path.exists(path):
            try:
                import json
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                token = data.get("oauthToken") or data.get("token")
                if token:
                    return str(token)
            except Exception:
                pass
    return None


def _cli_enabled() -> bool:
    if os.environ.get("ANTHROPIC_USE_CLI", "").strip() in ("1", "true", "yes"):
        return True
    if os.environ.get("MUCHANIPO_USE_CLI", "").strip() in ("1", "true", "yes"):
        return True
    return False


def _resolve_claude_bin() -> str | None:
    explicit = os.environ.get("CLAUDE_BIN")
    if explicit and os.path.exists(explicit):
        return explicit
    return shutil.which("claude")


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        client: Any = None,
        offline: bool | None = None,
        use_cli: bool | None = None,
        claude_bin: str | None = None,
    ) -> None:
        self.model = model
        self.client = client
        self.api_key = api_key or _resolve_api_key()
        self.claude_bin = claude_bin or _resolve_claude_bin()
        if use_cli is None:
            use_cli = _cli_enabled() and bool(self.claude_bin)
        self.use_cli = use_cli
        if offline is None:
            # CLI mode bypasses the offline-by-no-key check.
            offline = bool(os.environ.get("ANTHROPIC_OFFLINE")) or (
                self.api_key is None and not self.use_cli
            )
        # Injected client trumps offline default — caller wants real call path.
        if client is not None and offline:
            offline = False
        self.offline = offline

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        if self.offline:
            return _mock_result(stage, prompt, model=self.model, provider=self.name)

        stream_callback = kwargs.pop("stream_callback", None)
        allow_fallback = kwargs.pop("allow_fallback", True)

        if self.use_cli and self.claude_bin:
            try:
                return self._call_cli(stage, prompt, stream_callback=stream_callback, **kwargs)
            except Exception as exc:
                if allow_fallback:
                    return _fallback_result(exc, self.model)
                raise

        try:
            return self._call_with_fallback(stage, prompt, stream_callback=stream_callback, **kwargs)
        except Exception as exc:
            if allow_fallback:
                return _fallback_result(exc, self.model)
            raise

    def _call_cli(
        self,
        stage: str,
        prompt: str,
        *,
        stream_callback: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> ModelResult:  # pragma: no cover - subprocess path
        model = kwargs.pop("model", self.model)
        timeout = int(kwargs.pop("timeout", _CLI_TIMEOUT_SEC))
        args = [self.claude_bin, "-p", "--output-format", "text", "--model", model]
        proc = subprocess.run(
            args,
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(stderr or f"claude CLI exited with {proc.returncode}")
        text = proc.stdout.decode("utf-8", errors="replace").strip()
        if stream_callback:
            stream_callback(text)
        return ModelResult(
            text=text,
            provider=self.name,
            model=model,
            cost_usd=0.0,
            raw={"mode": "cli"},
        )

    def _call_with_fallback(
        self,
        stage: str,
        prompt: str,
        *,
        stream_callback: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> ModelResult:
        models = _fallback_models(kwargs.pop("model", self.model))
        last_exc: Exception | None = None
        for m in models:
            try:
                return self._call_one(
                    stage=stage,
                    prompt=prompt,
                    model=m,
                    stream_callback=stream_callback,
                    **kwargs,
                )
            except Exception as exc:
                last_exc = exc
        raise last_exc or RuntimeError("all fallback models failed")

    def _call_one(
        self,
        *,
        stage: str,
        prompt: str,
        model: str,
        stream_callback: Callable[[str], None] | None,
        **kwargs: Any,
    ) -> ModelResult:
        client = self.client
        if client is None:
            if Anthropic is None:
                raise RuntimeError("anthropic package is not installed")
            client = Anthropic(api_key=self.api_key)

        if stream_callback:
            return self._stream_call(client, model, prompt, stream_callback, **kwargs)

        message = client.messages.create(
            model=model,
            max_tokens=int(kwargs.pop("max_tokens", 1024)),
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        text = _content_text(message)
        cost = _estimate_cost(model, message)
        return ModelResult(
            text=text,
            provider=self.name,
            model=model,
            cost_usd=cost,
            raw=message,
        )

    def _stream_call(
        self,
        client: Any,
        model: str,
        prompt: str,
        callback: Callable[[str], None],
        **kwargs: Any,
    ) -> ModelResult:
        with client.messages.stream(
            model=model,
            max_tokens=int(kwargs.pop("max_tokens", 1024)),
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        ) as stream:
            chunks: list[str] = []
            for text in stream.text_stream:
                if text:
                    chunks.append(text)
                    callback(text)
            full_text = "".join(chunks)
            # Best-effort cost extraction after stream ends
            usage = getattr(stream, "current_message_snapshot", None)
            cost = _estimate_cost(model, usage)
            return ModelResult(
                text=full_text,
                provider=self.name,
                model=model,
                cost_usd=cost,
                raw=None,
            )


def _fallback_models(preferred: str) -> tuple[str, ...]:
    """Return fallback chain starting from the preferred model."""
    try:
        idx = FALLBACK_CHAIN.index(preferred)
        return FALLBACK_CHAIN[idx:]
    except ValueError:
        return (preferred,) + FALLBACK_CHAIN


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


def _estimate_cost(model: str, message: Any) -> float:
    usage = getattr(message, "usage", None) or {}
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    pricing = _PRICING.get(model, (3.0, 15.0))
    # pricing is per 1M tokens
    return round(
        (input_tokens * pricing[0] + output_tokens * pricing[1]) / 1_000_000, 6
    )


def _fallback_result(exc: Exception, model: str) -> ModelResult:
    return ModelResult(
        text=f"[anthropic fallback] {exc}",
        provider="anthropic",
        model=model,
        cost_usd=0.0,
        is_fallback=True,
        fallback_reason=str(exc),
    )


def _mock_result(stage: str, prompt: str, *, model: str, provider: str) -> ModelResult:
    snippet = prompt[:60].replace("\n", " ")
    text = f"[mock-{provider}/{stage}] {snippet}"
    return ModelResult(text=text, provider=provider, model=model, cost_usd=0.0)
