"""Tests for src/execution/providers/kimi.py."""

from __future__ import annotations

import subprocess
import os
from unittest.mock import MagicMock, patch

import pytest

from src.execution.providers.kimi import KimiProvider, _strip_kimi_cli_noise


class TestKimiProviderCli:
    @patch("subprocess.run")
    def test_cli_mode_passes_prompt_via_stdin_not_argv(self, mock_run, monkeypatch):
        monkeypatch.delenv("KIMI_API_KEY", raising=False)
        monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
        monkeypatch.setenv("MUCHANIPO_USE_CLI", "1")
        prompt = "secret prompt body"
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=b"ok\n\nTo resume this session: kimi -r abc\n",
            stderr=b"",
        )

        provider = KimiProvider(
            offline=False,
            use_cli=True,
            kimi_bin="/usr/local/bin/kimi",
        )
        result = provider.call("evidence", prompt, timeout=12)

        assert result.text == "ok"
        args = mock_run.call_args.args[0]
        assert args == [
            "/usr/local/bin/kimi",
            "--work-dir",
            os.getcwd(),
            "--print",
            "--final-message-only",
            "--input-format",
            "text",
        ]
        assert prompt not in args
        assert mock_run.call_args.kwargs["input"] == prompt.encode("utf-8")
        assert mock_run.call_args.kwargs["timeout"] == 12

    @patch("subprocess.run")
    def test_cli_nonzero_without_api_key_raises(self, mock_run, monkeypatch):
        monkeypatch.delenv("KIMI_API_KEY", raising=False)
        monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout=b"",
            stderr=b"auth failed",
        )
        provider = KimiProvider(
            api_key=None,
            offline=False,
            use_cli=True,
            kimi_bin="/usr/local/bin/kimi",
        )

        with pytest.raises(RuntimeError, match="auth failed"):
            provider.call("evidence", "prompt")

    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    @patch("subprocess.run")
    def test_cli_failure_falls_back_to_api_when_key_exists(
        self,
        mock_run,
        mock_request,
        mock_urlopen,
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout=b"",
            stderr=b"cli failed",
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"choices":[{"message":{"content":"api ok"}}],"usage":{}}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        provider = KimiProvider(
            api_key="k-test",
            offline=False,
            use_cli=True,
            kimi_bin="/usr/local/bin/kimi",
        )

        result = provider.call("evidence", "prompt")

        assert result.text == "api ok"
        assert mock_request.called


def test_strip_kimi_cli_noise_removes_resume_hint():
    assert _strip_kimi_cli_noise("OK\n\nTo resume this session: kimi -r abc\n") == "OK"
