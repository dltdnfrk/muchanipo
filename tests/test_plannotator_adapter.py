from pathlib import Path

from src.hitl.plannotator_adapter import HITLAdapter, HITLResult


def test_auto_approve_gate_returns_synthetic_approved():
    adapter = HITLAdapter(mode="auto_approve")

    result = adapter.gate("brief", {"x": 1})

    assert result.status == "approved"
    assert result.comments == ["auto-approved gate: brief"]
    assert result.synthetic is True
    assert result.path == "synthetic://auto-approve/brief"
    assert result.decision_provenance["mode"] == "auto_approve"
    assert result.decision_provenance["synthetic"] is True


def test_markdown_gate_writes_pending_queue_item(tmp_path: Path):
    adapter = HITLAdapter(mode="markdown", queue_dir=tmp_path, timeout_seconds=0)

    result = adapter.gate("evidence", {"refs": ["E1"]})

    assert result.status == "pending"
    assert result.path is not None
    path = Path(result.path)
    assert path.exists()
    assert result.decision_provenance["mode"] == "markdown"
    assert result.decision_provenance["path"] == str(path)
    assert result.decision_provenance["synthetic"] is False
    text = path.read_text(encoding="utf-8")
    assert "status: pending" in text
    assert '"refs": [' in text


def test_changes_requested_results_are_resumable():
    result = HITLResult(status="changes_requested")

    assert result.resumable is True


def test_plannotator_mode_uses_configured_client():
    class Client:
        def create_session(self, payload):
            assert payload == {"gate": "report", "payload": {"report_md": "# Report"}}
            return "sess-report"

        def poll_until_decision(self, session_id, timeout_sec=86400):
            assert session_id == "sess-report"
            return "approved"

        def fetch_annotations(self, session_id):
            assert session_id == "sess-report"
            return []

        def to_hitl_result(self, annotations, status):
            return HITLResult(status=status, annotations=annotations)

    adapter = HITLAdapter(mode="plannotator", client=Client())

    result = adapter.gate_report("# Report")

    assert result.status == "approved"
    assert result.gate_id == "sess-report"
