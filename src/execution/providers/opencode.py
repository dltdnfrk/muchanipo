"""OpenCode provider — CLI-first, OpenCode Go API fallback, offline-safe.

OpenCode owns its auth state. Muchanipo calls the installed CLI for the local
agent-app path and never reads ``~/.local/share/opencode/auth.json`` directly.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from src.execution.models import ModelResult
from src.execution.providers.cli_policy import cli_requested, prefer_cli_default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_DEFAULT_MODEL = os.environ.get("MUCHANIPO_OPENCODE_MODEL", "opencode-go/kimi-k2.6")
_HTTP_TIMEOUT_SEC = _env_int("MUCHANIPO_OPENCODE_TIMEOUT_SEC", 30)
_CLI_TIMEOUT_SEC = _env_int("MUCHANIPO_OPENCODE_CLI_TIMEOUT_SEC", 600)


def _cli_enabled() -> bool:
    return cli_requested("OPENCODE_USE_CLI")


def _resolve_opencode_bin() -> str | None:
    explicit = os.environ.get("OPENCODE_BIN")
    if explicit and os.path.exists(explicit):
        return explicit
    return shutil.which("opencode")


def _resolve_api_key() -> str | None:
    return os.environ.get("OPENCODE_API_KEY") or os.environ.get("OPENCODE_GO_API_KEY")


class OpenCodeProvider:
    name = "opencode"

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        endpoint: str = "",
        offline: bool | None = None,
        use_cli: bool | None = None,
        prefer_cli: bool | None = None,
        opencode_bin: str | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key or _resolve_api_key()
        self.endpoint = endpoint or os.environ.get(
            "OPENCODE_ENDPOINT",
            "https://opencode.ai/zen/go/v1/chat/completions",
        )
        self.opencode_bin = opencode_bin or _resolve_opencode_bin()
        if prefer_cli is None:
            prefer_cli = prefer_cli_default()
        if use_cli is None:
            use_cli = bool(self.opencode_bin) and (_cli_enabled() or prefer_cli or not self.api_key)
        self.use_cli = use_cli
        if offline is None:
            offline = bool(os.environ.get("OPENCODE_OFFLINE")) or (
                self.api_key is None and not self.use_cli
            )
        self.offline = offline

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        if self.offline:
            return _mock_result(stage, prompt, model=self.model, provider=self.name)
        model = kwargs.pop("model", self.model)
        if self.use_cli and self.opencode_bin:
            try:
                return self._call_cli(stage, prompt, model=model, **kwargs)
            except Exception:
                if not self.api_key:
                    raise
        return self._call_api(stage, prompt, model=model, **kwargs)

    def _call_cli(self, stage: str, prompt: str, *, model: str, **kwargs: Any) -> ModelResult:
        timeout = int(kwargs.pop("timeout", _CLI_TIMEOUT_SEC))
        with tempfile.TemporaryDirectory(prefix="muchanipo-opencode-") as tmp:
            prompt_path = Path(tmp) / "prompt.txt"
            prompt_path.write_text(prompt, encoding="utf-8")
            args = [
                self.opencode_bin,
                "run",
                "--pure",
                "--model",
                model,
                "--format",
                "json",
                "Follow the attached prompt file. Return only the final answer.",
                "--file",
                str(prompt_path),
            ]
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        if proc.returncode != 0:
            stderr = proc.stderr or ""
            raise RuntimeError(stderr.strip() or f"opencode CLI exited with {proc.returncode}")
        text = _extract_opencode_text(proc.stdout)
        return ModelResult(
            text=text,
            provider=self.name,
            model=model,
            cost_usd=0.0,
            raw={"mode": "cli", "stderr": proc.stderr},
        )

    def _call_api(self, stage: str, prompt: str, *, model: str, **kwargs: Any) -> ModelResult:
        if not self.api_key:
            raise RuntimeError("OpenCode API key is not configured")
        import urllib.request

        api_model = model[len("opencode-go/") :] if model.startswith("opencode-go/") else model
        body = json.dumps({
            "model": api_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": int(kwargs.pop("max_tokens", 1024)),
            "temperature": float(kwargs.pop("temperature", 0.4)),
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
            text = json.dumps(payload, ensure_ascii=False)
        usage = payload.get("usage", {}) or {}
        return ModelResult(
            text=text,
            provider=self.name,
            model=model,
            cost_usd=_estimate_cost(usage),
            raw=payload,
        )


def _extract_opencode_text(raw: str) -> str:
    """Best-effort extraction from ``opencode run --format json`` event output."""
    raw = raw.strip()
    if not raw:
        return ""
    parsed_events: list[Any] = []
    try:
        parsed = json.loads(raw)
        parsed_events = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed_events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    texts: list[str] = []
    for event in parsed_events:
        texts.extend(_candidate_texts(event))
    if texts:
        return "\n".join(text for text in texts if text.strip()).strip()
    return raw


def _candidate_texts(value: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(value, str):
        if value.strip():
            texts.append(value)
        return texts
    if isinstance(value, list):
        for item in value:
            texts.extend(_candidate_texts(item))
        return texts
    if not isinstance(value, dict):
        return texts

    for key in ("text", "content", "message"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            texts.append(item)
        elif isinstance(item, (dict, list)):
            texts.extend(_candidate_texts(item))
    for key in ("part", "parts", "delta", "data", "result", "response"):
        item = value.get(key)
        if isinstance(item, (dict, list)):
            texts.extend(_candidate_texts(item))
        elif isinstance(item, str) and item.strip():
            texts.append(item)
    return texts


def _estimate_cost(usage: dict[str, Any]) -> float:
    total = float(usage.get("total_tokens", 0) or 0)
    # OpenCode Go exposes plan/quota usage through OpenCode; keep API fallback
    # conservative when token-level provider pricing is not returned.
    return round(total * 0.0, 6)


def _mock_result(stage: str, prompt: str, *, model: str, provider: str) -> ModelResult:
    snippet = prompt[:60].replace("\n", " ")
    text = f"[mock-{provider}/{stage}] {snippet}"
    return ModelResult(text=text, provider=provider, model=model, cost_usd=0.0)
