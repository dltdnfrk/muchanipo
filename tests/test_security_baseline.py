from __future__ import annotations

import json
from pathlib import Path


TAURI_ROOT = Path("app/muchanipo-tauri/src-tauri")


def _load_tauri_config() -> dict:
    return json.loads((TAURI_ROOT / "tauri.conf.json").read_text(encoding="utf-8"))


def test_tauri_config_declares_strict_csp_instead_of_disabling_it() -> None:
    config = _load_tauri_config()
    csp = config["app"]["security"].get("csp")

    assert isinstance(csp, str)
    assert csp.strip()
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-src 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "form-action 'none'" in csp
    assert "*" not in csp
    assert "http:" not in csp.replace("http://127.0.0.1:1420", "")


def test_tauri_dev_server_is_bound_to_loopback_only() -> None:
    config = _load_tauri_config()
    build = config["build"]

    assert build["devUrl"] == "http://127.0.0.1:1420"
    assert "--host 127.0.0.1" in build["beforeDevCommand"]
    assert "0.0.0.0" not in build["beforeDevCommand"]
    assert "--host 0.0.0.0" not in build["beforeDevCommand"]


def test_default_tauri_capability_stays_minimal() -> None:
    capability = json.loads((TAURI_ROOT / "capabilities" / "default.json").read_text(encoding="utf-8"))
    permissions = set(capability["permissions"])

    assert capability["windows"] == ["main"]
    assert permissions == {"core:default", "core:window:allow-start-dragging"}
    forbidden_fragments = ("shell", "fs", "http", "process", "clipboard", "notification")
    assert not any(any(fragment in permission for fragment in forbidden_fragments) for permission in permissions)


def test_muchanipo_security_baseline_document_exists() -> None:
    doc = Path("docs/security-baseline.md").read_text(encoding="utf-8")

    assert "# Muchanipo Security Baseline" in doc
    assert "Tauri CSP" in doc
    assert "Loopback-only dev server" in doc
    assert "Renderer environment allowlist" in doc
    assert "No Express/Helmet server" in doc
