"""Tests for src/execution/providers/opencode.py."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

from src.execution.providers.opencode import OpenCodeProvider, _extract_opencode_text


class TestOpenCodeProviderCli:
    @patch("subprocess.run")
    def test_cli_mode_uses_attached_prompt_file_not_argv(self, mock_run, monkeypatch):
        monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
        monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
        prompt = "secret prompt body"
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"message": {"content": "ok"}}),
            stderr="",
        )

        provider = OpenCodeProvider(
            offline=False,
            use_cli=True,
            opencode_bin="/usr/local/bin/opencode",
        )
        result = provider.call("eval", prompt, timeout=12)

        assert result.text == "ok"
        args = mock_run.call_args.args[0]
        assert args[:7] == [
            "/usr/local/bin/opencode",
            "run",
            "--pure",
            "--model",
            "opencode-go/kimi-k2.6",
            "--format",
            "json",
        ]
        assert "--file" in args
        assert args.index("--file") > args.index("Follow the attached prompt file. Return only the final answer.")
        assert "--dangerously-skip-permissions" not in args
        assert prompt not in args
        assert mock_run.call_args.kwargs["timeout"] == 12

    @patch("subprocess.run")
    def test_cli_nonzero_without_api_key_raises(self, mock_run, monkeypatch):
        monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
        monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout="",
            stderr="auth failed",
        )
        provider = OpenCodeProvider(
            api_key=None,
            offline=False,
            use_cli=True,
            opencode_bin="/usr/local/bin/opencode",
        )

        try:
            provider.call("eval", "prompt")
        except RuntimeError as exc:
            assert "auth failed" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected RuntimeError")

    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    @patch("subprocess.run")
    def test_cli_failure_falls_back_to_go_api_when_key_exists(
        self,
        mock_run,
        mock_request,
        mock_urlopen,
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout="",
            stderr="cli failed",
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"choices":[{"message":{"content":"api ok"}}],"usage":{}}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        provider = OpenCodeProvider(
            api_key="oc-test",
            offline=False,
            use_cli=True,
            opencode_bin="/usr/local/bin/opencode",
        )

        result = provider.call("eval", "prompt")

        assert result.text == "api ok"
        request_body = mock_request.call_args.kwargs["data"].decode("utf-8")
        assert '"model": "kimi-k2.6"' in request_body


def test_extract_opencode_text_from_json_lines():
    raw = "\n".join([
        json.dumps({"type": "start"}),
        json.dumps({"message": {"role": "assistant", "content": "final answer"}}),
    ])

    assert _extract_opencode_text(raw) == "final answer"


def test_extract_opencode_text_from_part_text_event():
    raw = json.dumps({"type": "text", "part": {"text": "OK"}})

    assert _extract_opencode_text(raw) == "OK"


def test_extract_opencode_text_falls_back_to_raw_text():
    assert _extract_opencode_text("plain answer") == "plain answer"
