"""Tests for src/execution/providers/codex.py."""

from __future__ import annotations

import subprocess

import pytest

from src.execution.providers.codex import CodexProvider


def test_codex_subprocess_nonzero_returncode_raises_runtime_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=2,
            stdout=b"",
            stderr=b"codex failed",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    provider = CodexProvider(codex_bin="/usr/bin/codex", offline=False)

    with pytest.raises(RuntimeError, match="codex failed"):
        provider.call("eval", "check this")
