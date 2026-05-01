import json
from urllib.request import Request

from src.hitl.plannotator_adapter import HITLAdapter, HITLResult
import pytest

from src.hitl.plannotator_http import PlannotatorClient, PlannotatorError


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_client_creates_session_with_authorized_post(monkeypatch):
    captured: list[Request] = []

    def fake_urlopen(request, timeout):
        captured.append(request)
        return _Response({"session_id": "sess-123"})

    monkeypatch.setattr("src.hitl.plannotator_http.urllib.request.urlopen", fake_urlopen)
    client = PlannotatorClient(
        endpoint="https://example.test/api/",
        api_key="secret",
        offline=False,
    )

    session_id = client.create_session({"gate": "brief", "payload": {"x": 1}})

    assert session_id == "sess-123"
    assert captured[0].full_url == "https://example.test/api/sessions"
    assert captured[0].get_method() == "POST"
    assert captured[0].headers["Authorization"] == "Bearer secret"
    assert json.loads(captured[0].data.decode("utf-8")) == {
        "gate": "brief",
        "payload": {"x": 1},
    }


def test_client_polls_pending_to_approved_and_fetches_annotations(monkeypatch):
    responses = [
        {"status": "pending"},
        {"status": "approved"},
        {
            "annotations": [
                {
                    "type": "edit",
                    "target": "report.summary",
                    "instruction": "Tighten summary.",
                    "extra": "preserved",
                }
            ]
        },
    ]
    urls: list[str] = []

    def fake_urlopen(request, timeout):
        urls.append(request.full_url)
        return _Response(responses.pop(0))

    monkeypatch.setattr("src.hitl.plannotator_http.urllib.request.urlopen", fake_urlopen)
    client = PlannotatorClient(
        endpoint="https://example.test/api",
        api_key="secret",
        offline=False,
    )

    status = client.poll_until_decision("sess/123", timeout_sec=1, poll_interval_sec=0.01)
    annotations = client.fetch_annotations("sess/123")
    result = client.to_hitl_result(annotations, status)

    assert status == "approved"
    assert urls == [
        "https://example.test/api/sessions/sess%2F123/status",
        "https://example.test/api/sessions/sess%2F123/status",
        "https://example.test/api/sessions/sess%2F123/annotations",
    ]
    assert result == HITLResult(
        status="approved",
        annotations=[
            {
                "type": "edit",
                "target": "report.summary",
                "instruction": "Tighten summary.",
                "extra": "preserved",
            }
        ],
        comments=["Tighten summary."],
        synthetic=False,
    )


def test_hitl_adapter_uses_plannotator_client():
    class MockClient:
        def __init__(self):
            self.created_payload = None

        def create_session(self, payload):
            self.created_payload = payload
            return "sess-abc"

        def poll_until_decision(self, session_id, timeout_sec=86400):
            assert session_id == "sess-abc"
            assert timeout_sec == 86400
            return "changes_requested"

        def fetch_annotations(self, session_id):
            assert session_id == "sess-abc"
            return [{"target": "brief", "instruction": "Clarify audience."}]

        def to_hitl_result(self, annotations, status):
            return HITLResult(
                status=status,
                annotations=annotations,
                comments=[item["instruction"] for item in annotations],
            )

    client = MockClient()
    adapter = HITLAdapter(mode="plannotator", client=client)

    result = adapter.gate("brief", {"topic": "pricing"})

    assert client.created_payload == {
        "gate": "brief",
        "payload": {"topic": "pricing"},
    }
    assert result.status == "changes_requested"
    assert result.gate_id == "sess-abc"
    assert result.path == "plannotator://sessions/sess-abc"
    assert result.comments == ["Clarify audience."]


def test_offline_mode_returns_approved_without_annotations(monkeypatch):
    monkeypatch.setenv("PLANNOTATOR_OFFLINE", "1")
    monkeypatch.delenv("PLANNOTATOR_API_KEY", raising=False)
    monkeypatch.setattr("src.hitl.plannotator_http.time.sleep", lambda _seconds: None)
    client = PlannotatorClient()

    session_id = client.create_session({"gate": "report"})
    status = client.poll_until_decision(session_id)
    result = client.to_hitl_result(client.fetch_annotations(session_id), status)

    assert session_id.startswith("offline-")
    assert result.status == "approved"
    assert result.annotations == []
    assert result.comments == ["plannotator offline mock - no API key configured"]
    assert result.synthetic is True


def test_missing_api_key_fails_closed_without_offline(monkeypatch):
    monkeypatch.delenv("PLANNOTATOR_OFFLINE", raising=False)
    monkeypatch.delenv("PLANNOTATOR_API_KEY", raising=False)
    client = PlannotatorClient()

    assert client.offline is False
    with pytest.raises(PlannotatorError, match="no api key"):
        client.create_session({"gate": "report"})
