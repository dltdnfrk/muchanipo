"""Real LLM smoke tests — auto-skipped without provider API keys.

These tests opt-in to the live API so they can stay green in CI without
costing money. Set the relevant env var (and unset *_OFFLINE) to run them
locally.

Run only the available providers:
    ANTHROPIC_API_KEY=sk-... pytest tests/test_real_llm_smoke.py -v
    KIMI_API_KEY=mk-... pytest tests/test_real_llm_smoke.py -v
"""

from __future__ import annotations

import os
import re

import pytest


def _has_key(name: str) -> bool:
    """Return True if the env var is set to a non-empty, non-mock value."""
    val = os.environ.get(name, "").strip()
    if not val:
        return False
    if val.startswith(("mock", "test", "demo")):
        return False
    return True


@pytest.mark.skipif(not _has_key("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set")
def test_anthropic_real_call_returns_non_mock_text():
    from src.execution.providers.anthropic import AnthropicProvider

    # Force real-mode by clearing offline flag.
    os.environ.pop("ANTHROPIC_OFFLINE", None)

    provider = AnthropicProvider()
    result = provider.call(
        stage="interview",
        prompt="Reply with exactly the single word: pong",
        max_tokens=16,
    )
    text = (result.text or "").strip().lower()
    assert text, "empty response from Anthropic"
    # Real model output should not contain the mock prefix.
    assert "[mock-" not in text


@pytest.mark.skipif(not _has_key("KIMI_API_KEY"), reason="KIMI_API_KEY not set")
def test_kimi_real_call_returns_non_mock_text():
    from src.execution.providers.kimi import KimiProvider

    os.environ.pop("KIMI_OFFLINE", None)

    provider = KimiProvider(offline=False)
    result = provider.call(
        stage="evidence",
        prompt="Reply with exactly the single word: pong",
        max_tokens=16,
    )
    text = (result.text or "").strip().lower()
    assert text
    assert "[mock-" not in text


@pytest.mark.skipif(
    not (_has_key("GEMINI_API_KEY") or _has_key("GOOGLE_API_KEY")),
    reason="GEMINI_API_KEY / GOOGLE_API_KEY not set",
)
def test_gemini_real_call_returns_non_mock_text():
    from src.execution.providers.gemini import GeminiProvider

    os.environ.pop("GEMINI_OFFLINE", None)

    provider = GeminiProvider(offline=False)
    result = provider.call(
        stage="research",
        prompt="Reply with exactly the single word: pong",
        max_tokens=16,
    )
    text = (result.text or "").strip().lower()
    assert text
    assert "[mock-" not in text


@pytest.mark.skipif(
    not _has_key("ANTHROPIC_API_KEY"),
    reason="full pipeline real test needs ANTHROPIC_API_KEY at minimum",
)
def test_full_pipeline_serve_with_real_anthropic(tmp_path):
    """End-to-end: serve_full → real Council via Anthropic → 6 chapters.

    NOTE: This costs real money (~$0.10-0.50). Skipped by default.
    """
    import io

    from src.muchanipo.server import serve_full

    os.environ.pop("ANTHROPIC_OFFLINE", None)
    report = tmp_path / "REPORT.md"
    stdout = io.StringIO()

    rc = serve_full("AI 기반 농업 진단키트 시장성", report_path=report, stdout=stdout)
    assert rc == 0
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    # Six chapters should always be present even with real LLM (ChapterMapper
    # always emits all six, even if some chapters say "추가 리서치 필요").
    for n in range(1, 7):
        assert re.search(rf"^## Chapter {n}", text, re.MULTILINE), \
            f"Chapter {n} missing"
