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


_DEFAULT_MODEL = "gpt-5.5"


class CodexProvider:
    name = "codex"

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        codex_bin: str | None = None,
        endpoint: str = "https://api.openai.com/v1/chat/completions",
        offline: bool | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.codex_bin = codex_bin or os.environ.get("CODEX_BIN") or shutil.which("codex")
        self.endpoint = endpoint
        if offline is None:
            offline = bool(os.environ.get("CODEX_OFFLINE")) or (
                self.api_key is None and not self.codex_bin
            )
        self.offline = offline

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        if self.offline:
            return _mock_result(stage, prompt, model=self.model, provider=self.name)
        if self.codex_bin and not self.api_key:
            return self._call_subprocess(stage, prompt, **kwargs)
        return self._call_openai(stage, prompt, **kwargs)

    def _call_subprocess(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:  # pragma: no cover
        proc = subprocess.run(
            [self.codex_bin, "exec", "-m", self.model, "-"],
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=int(kwargs.pop("timeout", 60)),
        )
        stderr = proc.stderr.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(stderr or f"codex exited with {proc.returncode}")
        text = proc.stdout.decode("utf-8", errors="replace")
        return ModelResult(
            text=text,
            provider=self.name,
            model=self.model,
            raw={"returncode": proc.returncode, "stderr": stderr},
        )

    def _call_openai(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:  # pragma: no cover
        import urllib.request

        body = json.dumps({
            "model": kwargs.pop("model", self.model),
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
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        text = ""
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            text = json.dumps(payload)
        return ModelResult(text=text, provider=self.name, model=self.model, raw=payload)


def _mock_result(stage: str, prompt: str, *, model: str, provider: str) -> ModelResult:
    snippet = prompt[:60].replace("\n", " ")
    text = f"[mock-{provider}/{stage}] {snippet}"
    return ModelResult(text=text, provider=provider, model=model, cost_usd=0.0)
