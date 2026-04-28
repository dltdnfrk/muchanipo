"""OpenAI Codex CLI / GPT-5.5 provider — offline-safe stub.

PRD-v2 §8.1: Eval stage uses Codex CLI subprocess. We support two modes:
  1. Subprocess via Codex CLI binary (CODEX_BIN env var, default 'codex')
  2. OpenAI API direct (OPENAI_API_KEY) — for non-CLI environments

Falls back to deterministic mock when neither is available.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from src.execution.models import ModelResult


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_DEFAULT_MODEL = os.environ.get("MUCHANIPO_CODEX_MODEL", "gpt-5.5")
_HTTP_TIMEOUT_SEC = _env_int("MUCHANIPO_CODEX_TIMEOUT_SEC", 30)
_CLI_TIMEOUT_SEC = _env_int("MUCHANIPO_CODEX_CLI_TIMEOUT_SEC", 600)


def _cli_enabled() -> bool:
    if os.environ.get("CODEX_USE_CLI", "").strip() in ("1", "true", "yes"):
        return True
    if os.environ.get("MUCHANIPO_USE_CLI", "").strip() in ("1", "true", "yes"):
        return True
    return False


class CodexProvider:
    name = "codex"

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        codex_bin: str | None = None,
        endpoint: str = "",
        offline: bool | None = None,
        use_cli: bool | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.codex_bin = codex_bin or os.environ.get("CODEX_BIN") or shutil.which("codex")
        self.endpoint = endpoint or os.environ.get("OPENAI_ENDPOINT", "https://api.openai.com/v1/chat/completions")
        # CLI is preferred whenever the binary is available AND either the
        # USE_CLI flag is set or there is no API key.
        if use_cli is None:
            use_cli = bool(self.codex_bin) and (_cli_enabled() or not self.api_key)
        self.use_cli = use_cli
        if offline is None:
            offline = bool(os.environ.get("CODEX_OFFLINE")) or (
                self.api_key is None and not self.codex_bin
            )
        self.offline = offline

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        if self.offline:
            return _mock_result(stage, prompt, model=self.model, provider=self.name)
        if self.use_cli and self.codex_bin:
            return self._call_subprocess(stage, prompt, **kwargs)
        return self._call_openai(stage, prompt, **kwargs)

    def _call_subprocess(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:  # pragma: no cover
        proc = subprocess.run(
            [self.codex_bin, "exec", "-m", self.model, "-"],
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=int(kwargs.pop("timeout", _CLI_TIMEOUT_SEC)),
        )
        stderr = proc.stderr.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(stderr or f"codex exited with {proc.returncode}")
        raw_text = proc.stdout.decode("utf-8", errors="replace")
        text = _strip_codex_noise(raw_text)
        return ModelResult(
            text=text,
            provider=self.name,
            model=self.model,
            cost_usd=0.0,
            raw={"returncode": proc.returncode, "stderr": stderr, "mode": "cli"},
        )

    def _call_openai(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:  # pragma: no cover
        import urllib.request

        model = kwargs.pop("model", self.model)
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": int(kwargs.pop("max_tokens", 1024)),
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
        return ModelResult(text=text, provider=self.name, model=model, raw=payload)


def _strip_codex_noise(raw: str) -> str:
    """Codex `exec` mixes hook lifecycle lines + token counters into stdout.

    Drop hook scaffolding so the model output is the only thing returned.
    The conversation transcript also tends to repeat the final assistant
    response, so we deduplicate trailing identical paragraphs.
    """
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Hook scaffolding emitted by codex CLI.
        if stripped.startswith("hook:"):
            continue
        if stripped == "codex":
            continue
        if stripped.startswith("tokens used"):
            continue
        # Codex prints `ERROR codex_models_manager` etc. — usually safe to drop.
        if " ERROR " in stripped and "codex_models_manager" in stripped:
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    # Codex tends to print the final answer twice (transcript + summary).
    if cleaned:
        halves = cleaned.split("\n\n")
        if len(halves) >= 2 and halves[-1] == halves[-2]:
            cleaned = "\n\n".join(halves[:-1])
    return cleaned


def _mock_result(stage: str, prompt: str, *, model: str, provider: str) -> ModelResult:
    snippet = prompt[:60].replace("\n", " ")
    text = f"[mock-{provider}/{stage}] {snippet}"
    return ModelResult(text=text, provider=provider, model=model, cost_usd=0.0)
