"""scripts/e2e_smoke.sh를 pytest로 실행 — Tauri shell 없이 Python E2E 검증."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "e2e_smoke.sh"


@pytest.mark.skipif(not SCRIPT.exists(), reason="e2e_smoke.sh not present")
def test_e2e_smoke_script_passes():
    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ},
    )
    assert proc.returncode == 0, f"smoke failed:\n{proc.stdout}\n{proc.stderr}"
    assert "[smoke] PASS" in proc.stdout
    assert "Chapter" in proc.stdout or proc.returncode == 0
