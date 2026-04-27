import subprocess
from pathlib import Path


def test_e2e_smoke_script_passes():
    repo = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        ["bash", str(repo / "scripts" / "e2e_smoke.sh")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "PASS" in proc.stdout
