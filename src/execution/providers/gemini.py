"""Google Gemini provider — CLI-first, API fallback, offline-safe.

The local app path can call `gemini -p`; any local auth/session details remain
owned by the Gemini CLI rather than Muchanipo.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
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


_DEFAULT_MODEL = os.environ.get("MUCHANIPO_GEMINI_MODEL", "gemini-2.5-flash")
_RESEARCH_MODEL = os.environ.get("MUCHANIPO_GEMINI_RESEARCH_MODEL", "gemini-2.5-pro")
_HTTP_TIMEOUT_SEC = _env_int("MUCHANIPO_GEMINI_TIMEOUT_SEC", 30)

# Stage → model mapping (PRD-v2 §8.1)
_STAGE_MODELS: dict[str, str] = {
    "intake": _DEFAULT_MODEL,
    "interview": _DEFAULT_MODEL,
    "research": _RESEARCH_MODEL,
    "evidence": _RESEARCH_MODEL,
    "council": _RESEARCH_MODEL,
    "report": _DEFAULT_MODEL,
    "consensus": _RESEARCH_MODEL,
    "eval": _DEFAULT_MODEL,
}


def _resolve_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def _cli_enabled() -> bool:
    return cli_requested("GEMINI_USE_CLI")


def _resolve_gemini_bin() -> str | None:
    explicit = os.environ.get("GEMINI_BIN")
    if explicit and os.path.exists(explicit):
        return explicit
    return shutil.which("gemini")


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        endpoint_template: str = "",
        offline: bool | None = None,
        use_cli: bool | None = None,
        prefer_cli: bool | None = None,
        gemini_bin: str | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key or _resolve_api_key()
        self.endpoint_template = (
            endpoint_template
            or os.environ.get(
                "GEMINI_ENDPOINT_TEMPLATE",
                "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            )
        )
        self.gemini_bin = gemini_bin or _resolve_gemini_bin()
        if prefer_cli is None:
            prefer_cli = prefer_cli_default()
        if use_cli is None:
            use_cli = bool(self.gemini_bin) and (_cli_enabled() or prefer_cli)
        self.use_cli = use_cli
        if offline is None:
            offline = bool(os.environ.get("GEMINI_OFFLINE")) or (
                self.api_key is None and not self.use_cli
            )
        self.offline = offline

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        if self.offline:
            return _mock_result(stage, prompt, model=self.model, provider=self.name)

        model = kwargs.pop("model", _STAGE_MODELS.get(stage, self.model))
        search_grounding = kwargs.pop("search_grounding", stage in ("research", "evidence", "intake"))

        if self.use_cli and self.gemini_bin:
            try:
                return self._call_cli(stage, prompt, model=model, **kwargs)
            except Exception:
                # If CLI fails and we have an API key, fall through to REST.
                if not self.api_key:
                    raise

        return self._call_real(
            stage=stage,
            prompt=prompt,
            model=model,
            search_grounding=search_grounding,
            **kwargs,
        )

    def _call_cli(
        self,
        stage: str,
        prompt: str,
        *,
        model: str,
        **kwargs: Any,
    ) -> ModelResult:  # pragma: no cover - subprocess path
        timeout = int(kwargs.pop("timeout", 300))
        # Keep user prompt content off argv (`ps`/Activity Monitor can expose
        # command arguments). Gemini CLI accepts stdin appended to a non-empty
        # headless prompt; `-p ""` hangs on some versions.
        args = [
            self.gemini_bin,
            "-p",
            "Follow the instructions provided on stdin.",
            "-m",
            model,
        ]
        proc = subprocess.run(
            args,
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(stderr or f"gemini CLI exited with {proc.returncode}")
        text = proc.stdout.decode("utf-8", errors="replace").strip()
        return ModelResult(
            text=text,
            provider=self.name,
            model=model,
            cost_usd=0.0,
            raw={"mode": "cli"},
        )

    def _call_real(
        self,
        stage: str,
        prompt: str,
        model: str,
        search_grounding: bool,
        **kwargs: Any,
    ) -> ModelResult:  # pragma: no cover
        import urllib.request

        url = self.endpoint_template.format(model=model) + f"?key={self.api_key}"
        body: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": int(kwargs.pop("max_tokens", 1024)),
                "temperature": float(kwargs.pop("temperature", 0.6)),
            },
        }
        if search_grounding:
            body["tools"] = [{"google_search": {}}]

        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        text = ""
        try:
            parts = payload["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError):
            text = json.dumps(payload)

        cost = _estimate_cost(model, payload)
        return ModelResult(
            text=text,
            provider=self.name,
            model=model,
            cost_usd=cost,
            raw=payload,
        )


def _estimate_cost(model: str, payload: dict[str, Any]) -> float:
    """Estimate cost. Google AI Studio free tier is $0 for supported models."""
    usage = payload.get("usageMetadata", {}) or {}
    input_tokens = int(usage.get("promptTokenCount", 0) or 0)
    output_tokens = int(usage.get("candidatesTokenCount", 0) or 0)

    # Paid tier approximate pricing per 1M tokens (input / output)
    # Gemini 2.5 Pro: $1.25 / $10, Flash: $0.15 / $0.60 (as of mid-2025)
    pricing = {
        "gemini-2.5-pro": (1.25, 10.0),
        "gemini-2.5-flash": (0.15, 0.60),
    }.get(model, (0.15, 0.60))

    return round(
        (input_tokens * pricing[0] + output_tokens * pricing[1]) / 1_000_000, 6
    )


def _mock_result(stage: str, prompt: str, *, model: str, provider: str) -> ModelResult:
    snippet = prompt[:60].replace("\n", " ")
    text = f"[mock-{provider}/{stage}] {snippet}"
    return ModelResult(text=text, provider=provider, model=model, cost_usd=0.0)
