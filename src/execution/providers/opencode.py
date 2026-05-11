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


_DEFAULT_OPENCODE_GO_MODEL = "opencode/kimi-k2.6"
_DEFAULT_MODEL = os.environ.get("MUCHANIPO_OPENCODE_MODEL", _DEFAULT_OPENCODE_GO_MODEL)
_HTTP_TIMEOUT_SEC = _env_int("MUCHANIPO_OPENCODE_TIMEOUT_SEC", 30)
_CLI_TIMEOUT_SEC = _env_int("MUCHANIPO_OPENCODE_CLI_TIMEOUT_SEC", 600)
_OPENCODE_API_USER_AGENT = os.environ.get(
    "MUCHANIPO_OPENCODE_USER_AGENT",
    "OpenCode/1.2.26 Muchanipo/1.0",
)



def _cli_enabled() -> bool:
    return cli_requested("OPENCODE_USE_CLI")


def _resolve_opencode_bin() -> str | None:
    explicit = os.environ.get("OPENCODE_BIN")
    if explicit and os.path.exists(explicit):
        return explicit
    return shutil.which("opencode")


def _resolve_api_key() -> str | None:
    for name in ("OPENCODE_API_KEY", "OPENCODE_GO_API_KEY"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return None


def _mimo_opencode_only_requested() -> bool:
    raw = (
        os.environ.get("MUCHANIPO_VERIFICATION_ROUTING")
        or os.environ.get("MUCHANIPO_LIVE_VERIFICATION_ROUTING")
        or os.environ.get("MUCHANIPO_MODEL_ROUTING")
        or os.environ.get("MUCHANIPO_API_ROUTING")
        or os.environ.get("MUCHANIPO_EXTERNAL_MODEL_ROUTING")
        or os.environ.get("MUCHANIPO_PROVIDER_ROUTING")
        or ""
    )
    normalized = raw.strip().casefold().replace("-", "_").replace(",", "_")
    return normalized in {
        "mimo_opencode_only",
        "mimo_opencode_go_only",
        "mimo_opencode",
        "mimo_opencodego",
    }


def _opencode_go_model(model: str) -> str:
    return model if model.startswith(("opencode/", "opencode-go/")) else _DEFAULT_OPENCODE_GO_MODEL


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
        self.model = _opencode_go_model(model) if _mimo_opencode_only_requested() else model
        self.api_key = api_key or _resolve_api_key()
        self.endpoint = endpoint or os.environ.get(
            "OPENCODE_ENDPOINT",
            "https://opencode.ai/zen/go/v1/chat/completions",
        )
        self.opencode_bin = opencode_bin or _resolve_opencode_bin()
        policy_requires_opencode_go = _mimo_opencode_only_requested()
        if prefer_cli is None:
            prefer_cli = prefer_cli_default()
        if use_cli is None:
            if policy_requires_opencode_go:
                # Verification policy means the network path must be OpenCode Go API,
                # not the local opencode/Bun CLI.  If no Go API key is configured,
                # mark the provider offline so live routing fails closed instead of
                # silently invoking a non-API local CLI.
                use_cli = False
            else:
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
                stdin=subprocess.DEVNULL,
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

        api_model = model.split("/", 1)[1] if model.startswith(("opencode-go/", "opencode/")) else model
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
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": _OPENCODE_API_USER_AGENT,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        text = ""
        try:
            text = payload["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError, AttributeError):
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
