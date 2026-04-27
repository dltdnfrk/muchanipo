from pathlib import Path

from src.hitl.plannotator_adapter import HITLAdapter


def test_auto_approve_gate_returns_approved():
    adapter = HITLAdapter(mode="auto_approve")

    result = adapter.gate("brief", {"x": 1})

    assert result.status == "approved"
    assert result.comments == ["auto-approved gate: brief"]


def test_markdown_gate_writes_pending_queue_item(tmp_path: Path):
    adapter = HITLAdapter(mode="markdown", queue_dir=tmp_path, timeout_seconds=0)

    result = adapter.gate("evidence", {"refs": ["E1"]})

    assert result.status == "pending"
    assert result.path is not None
    path = Path(result.path)
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "status: pending" in text
    assert '"refs": [' in text


def test_plannotator_mode_is_pending_stub():
    adapter = HITLAdapter(mode="plannotator")

    result = adapter.gate_report("# Report")

    assert result.status == "pending"
    assert result.comments == ["plannotator API stub: no HTTP call performed"]
