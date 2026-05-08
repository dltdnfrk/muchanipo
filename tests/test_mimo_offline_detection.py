"""MiMo API key should make Muchanipo online-capable without CLI."""

from __future__ import annotations


def test_server_detects_mimo_api_key_as_online(monkeypatch):
    from src.muchanipo.server import _detect_offline_mode

    monkeypatch.setenv("XIAOMI_MIMO_API_KEY", "tp-test")
    monkeypatch.setenv("MUCHANIPO_PREFER_CLI", "0")
    monkeypatch.delenv("MUCHANIPO_OFFLINE", raising=False)
    monkeypatch.delenv("MUCHANIPO_ONLINE", raising=False)

    assert _detect_offline_mode() is False


def test_pipeline_detects_mimo_api_key_as_online(monkeypatch):
    from src.pipeline.idea_to_council import _detect_offline_mode

    monkeypatch.setenv("MIMO_API_KEY", "tp-test")
    monkeypatch.setenv("MUCHANIPO_PREFER_CLI", "0")
    monkeypatch.delenv("MUCHANIPO_OFFLINE", raising=False)
    monkeypatch.delenv("MUCHANIPO_ONLINE", raising=False)

    assert _detect_offline_mode() is False
