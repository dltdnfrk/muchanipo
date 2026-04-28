"""Tests for src/execution/providers/gemini.py."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.execution.providers.gemini import (
    GeminiProvider,
    _estimate_cost,
    _resolve_api_key,
)


class TestResolveApiKey:
    def test_gemini_api_key(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "g-test")
        assert _resolve_api_key() == "g-test"

    def test_google_api_key_fallback(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "g-fallback")
        assert _resolve_api_key() == "g-fallback"

    def test_none_when_missing(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        assert _resolve_api_key() is None


class TestEstimateCost:
    def test_pro_pricing(self):
        payload = {"usageMetadata": {"promptTokenCount": 1_000_000, "candidatesTokenCount": 1_000_000}}
        cost = _estimate_cost("gemini-2.5-pro", payload)
        assert pytest.approx(cost, 0.001) == 11.25

    def test_flash_pricing(self):
        payload = {"usageMetadata": {"promptTokenCount": 2_000_000, "candidatesTokenCount": 1_000_000}}
        cost = _estimate_cost("gemini-2.5-flash", payload)
        assert pytest.approx(cost, 0.001) == 0.9

    def test_no_usage(self):
        cost = _estimate_cost("gemini-2.5-flash", {})
        assert cost == 0.0


class TestGeminiProviderOffline:
    def test_offline_when_no_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        p = GeminiProvider()
        assert p.offline is True
        result = p.call("test", "hello world")
        assert result.provider == "gemini"
        assert "[mock-gemini/test]" in result.text
        assert result.cost_usd == 0.0

    def test_offline_override(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "g-test")
        monkeypatch.setenv("GEMINI_OFFLINE", "1")
        p = GeminiProvider()
        assert p.offline is True


class TestGeminiProviderRealCall:
    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    def test_search_grounding_enabled_for_research(self, mock_request, mock_urlopen, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "g-test")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        p = GeminiProvider(api_key="g-test", offline=False)
        result = p.call("research", "prompt text")
        assert result.text == "ok"
        assert result.model == "gemini-2.5-pro"

        call_args = mock_request.call_args
        sent_body = json.loads(call_args[1]["data"].decode("utf-8"))
        assert "tools" in sent_body
        assert sent_body["tools"] == [{"google_search": {}}]

    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    def test_search_grounding_disabled_when_false(self, mock_request, mock_urlopen, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "g-test")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        p = GeminiProvider(api_key="g-test", offline=False)
        result = p.call("research", "prompt text", search_grounding=False)
        assert result.text == "ok"

        call_args = mock_request.call_args
        sent_body = json.loads(call_args[1]["data"].decode("utf-8"))
        assert "tools" not in sent_body

    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    def test_stage_routing_intake_uses_flash(self, mock_request, mock_urlopen, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "g-test")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        p = GeminiProvider(api_key="g-test", offline=False)
        result = p.call("intake", "prompt")
        assert result.model == "gemini-2.5-flash"

    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    def test_response_parsing(self, mock_request, mock_urlopen, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "g-test")
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "parsed"}]}}],
            "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 50},
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        p = GeminiProvider(api_key="g-test", offline=False)
        result = p.call("stage", "prompt")
        assert result.text == "parsed"
        assert result.cost_usd > 0


class TestGeminiProviderCli:
    @patch("subprocess.run")
    def test_cli_mode_passes_prompt_via_stdin_not_argv(self, mock_run, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setenv("MUCHANIPO_USE_CLI", "1")
        prompt = "secret prompt body"
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=b"ok\n",
            stderr=b"",
        )

        provider = GeminiProvider(
            offline=False,
            use_cli=True,
            gemini_bin="/usr/local/bin/gemini",
        )
        result = provider.call("intake", prompt, timeout=12)

        assert result.text == "ok"
        args = mock_run.call_args.args[0]
        assert args == [
            "/usr/local/bin/gemini",
            "-p",
            "Follow the instructions provided on stdin.",
            "-m",
            "gemini-2.5-flash",
        ]
        assert prompt not in args
        assert mock_run.call_args.kwargs["input"] == prompt.encode("utf-8")
        assert mock_run.call_args.kwargs["timeout"] == 12

    @patch("subprocess.run")
    def test_cli_nonzero_without_api_key_raises(self, mock_run, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout=b"",
            stderr=b"auth failed",
        )
        provider = GeminiProvider(
            api_key=None,
            offline=False,
            use_cli=True,
            gemini_bin="/usr/local/bin/gemini",
        )

        with pytest.raises(RuntimeError, match="auth failed"):
            provider.call("intake", "prompt")

    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    @patch("subprocess.run")
    def test_cli_failure_falls_back_to_rest_when_api_key_exists(
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
        mock_resp.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "rest ok"}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        provider = GeminiProvider(
            api_key="g-test",
            offline=False,
            use_cli=True,
            gemini_bin="/usr/local/bin/gemini",
        )

        result = provider.call("intake", "prompt", search_grounding=False)

        assert result.text == "rest ok"
        assert mock_request.called
