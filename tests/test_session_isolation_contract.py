from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from src.evidence.artifact import Finding
from src.muchanipo.server import _build_demo_rounds, serve_full
from src.research.max_plus_benchmark import benchmark_metrics, build_b1_probe_fixture
from src.research.session_contract import (
    DEFAULT_MEMORY_POLICY,
    ResearchContract,
    scope_event,
)


def _events(stdout: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]


def test_research_contract_defaults_are_hermetic() -> None:
    contract = ResearchContract.new(topic="strawberry diagnostics", app_run_id="app-a")

    assert contract.memory_policy == DEFAULT_MEMORY_POLICY
    assert contract.imported_knowledge_refs == ()
    assert contract.benchmark_fixture_id is None
    assert contract.app_run_id == "app-a"
    assert contract.research_session_id
    assert contract.to_artifacts()["imported_knowledge_refs"] == "[]"


def test_scope_event_adds_session_identity_when_missing() -> None:
    contract = ResearchContract.new(topic="session A", app_run_id="app-a")
    event = scope_event({"event": "research_progress"}, contract)

    assert event["research_session_id"] == contract.research_session_id
    assert event["app_run_id"] == "app-a"
    assert event["memory_policy"] == DEFAULT_MEMORY_POLICY
    assert event["imported_knowledge_refs"] == []


def test_scope_event_rejects_stale_session_identity() -> None:
    contract = ResearchContract.new(topic="session A", app_run_id="app-a")

    with pytest.raises(ValueError, match="research_session_id mismatch"):
        scope_event(
            {
                "event": "research_progress",
                "research_session_id": "backend-session",
                "app_run_id": "app-a",
            },
            contract,
        )

    with pytest.raises(ValueError, match="app_run_id mismatch"):
        scope_event(
            {
                "event": "research_progress",
                "research_session_id": contract.research_session_id,
                "app_run_id": "backend-app",
            },
            contract,
        )


def test_benchmark_metrics_requires_explicit_fixture_selection() -> None:
    with pytest.raises(ValueError, match="explicit benchmark fixture"):
        benchmark_metrics([])

    metrics = benchmark_metrics([], fixture=build_b1_probe_fixture(report_path=Path("/tmp/ref.md")))
    assert metrics["expected_claim_recall"] == 0.0


def test_two_serve_sessions_do_not_share_scope_or_imported_refs(tmp_path, monkeypatch) -> None:
    import src.pipeline.runner as runner_mod

    seen_contracts: list[ResearchContract] = []

    def fake_run_pipeline(topic, **kwargs):
        contract = kwargs["research_contract"]
        seen_contracts.append(contract)
        return {
            "rounds": _build_demo_rounds(topic),
            "executed_council_round_count": 1,
            "council_turn_transcript": [],
            "report_md": f"# Report\n\n## Chapter 1\n\n{topic} only\n",
            "council_persona_pool_size": 1,
            "active_council_persona_count": 1,
            "pipeline_result": None,
        }

    monkeypatch.setattr(runner_mod, "run_pipeline", fake_run_pipeline)

    monkeypatch.setenv("MUCHANIPO_APP_RUN_ID", "app-session-a")
    stdout_a = io.StringIO()
    assert serve_full("strawberry diagnostics", report_path=tmp_path / "a.md", stdout=stdout_a) == 0

    monkeypatch.setenv("MUCHANIPO_APP_RUN_ID", "app-session-b")
    stdout_b = io.StringIO()
    assert serve_full("semiconductor packaging", report_path=tmp_path / "b.md", stdout=stdout_b) == 0

    events_a = _events(stdout_a)
    events_b = _events(stdout_b)
    session_a = events_a[0]["research_session_id"]
    session_b = events_b[0]["research_session_id"]

    assert session_a != session_b
    assert seen_contracts[0].topic == "strawberry diagnostics"
    assert seen_contracts[1].topic == "semiconductor packaging"
    assert seen_contracts[0].imported_knowledge_refs == ()
    assert seen_contracts[1].imported_knowledge_refs == ()
    assert seen_contracts[0].memory_policy == DEFAULT_MEMORY_POLICY
    assert seen_contracts[1].memory_policy == DEFAULT_MEMORY_POLICY

    scoped_names = {
        "run_started",
        "phase_change",
        "report_chunk",
        "final_report",
        "done",
    }
    scoped_a = [event for event in events_a if event["event"] in scoped_names]
    scoped_b = [event for event in events_b if event["event"] in scoped_names]
    assert scoped_a and scoped_b
    assert all(event["research_session_id"] == session_a for event in scoped_a)
    assert all(event["research_session_id"] == session_b for event in scoped_b)
    assert all(event["app_run_id"] == "app-session-a" for event in scoped_a)
    assert all(event["app_run_id"] == "app-session-b" for event in scoped_b)
    assert all(event["memory_policy"] == DEFAULT_MEMORY_POLICY for event in scoped_a + scoped_b)
    assert all(event["imported_knowledge_refs"] == [] for event in scoped_a + scoped_b)

    chunks_a = "\n".join(str(event.get("markdown", "")) for event in events_a if event["event"] == "report_chunk")
    chunks_b = "\n".join(str(event.get("markdown", "")) for event in events_b if event["event"] == "report_chunk")
    assert "strawberry diagnostics" in chunks_a
    assert "semiconductor packaging" not in chunks_a
    assert "semiconductor packaging" in chunks_b
    assert "strawberry diagnostics" not in chunks_b


def test_interactive_prompt_events_are_scoped_to_current_session(tmp_path, monkeypatch) -> None:
    import src.pipeline.runner as runner_mod

    def fake_run_pipeline(topic, **kwargs):
        return {
            "rounds": _build_demo_rounds(topic),
            "executed_council_round_count": 1,
            "council_turn_transcript": [],
            "report_md": f"# Report\n\n## Chapter 1\n\n{topic}\n",
            "council_persona_pool_size": 1,
            "active_council_persona_count": 1,
            "pipeline_result": None,
        }

    monkeypatch.setattr(runner_mod, "run_pipeline", fake_run_pipeline)
    monkeypatch.setenv("MUCHANIPO_APP_RUN_ID", "app-interview-a")
    stdin = io.StringIO(
        "\n".join(
            json.dumps(
                {
                    "action": "interview_answer",
                    "q_id": f"Q{idx}",
                    "answer": f"session a answer {idx}",
                }
            )
            for idx in range(1, 7)
        )
        + "\n"
    )
    stdout = io.StringIO()

    assert (
        serve_full(
            "session-a prompt scope",
            report_path=tmp_path / "interactive.md",
            stdout=stdout,
            stdin=stdin,
            wait_for_input=True,
        )
        == 0
    )

    events = _events(stdout)
    session_id = events[0]["research_session_id"]
    prompt_events = [
        event
        for event in events
        if event["event"] in {"deep_interview_progress", "interview_ontology_delta", "interview_question"}
    ]

    assert prompt_events
    assert all(event["research_session_id"] == session_id for event in prompt_events)
    assert all(event["app_run_id"] == "app-interview-a" for event in prompt_events)
    assert all(event["memory_policy"] == DEFAULT_MEMORY_POLICY for event in prompt_events)
    assert all(event["imported_knowledge_refs"] == [] for event in prompt_events)


def test_expected_claims_are_session_local_when_fixture_is_explicit() -> None:
    fixture_a = build_b1_probe_fixture(report_path=Path("/tmp/session-a.md"))
    fixture_b = build_b1_probe_fixture(report_path=Path("/tmp/session-b.md"))
    findings_a = [
        Finding(
            claim="Strawberry pathogen LAMP assay field validation sensitivity specificity",
            support=[],
            confidence=0.8,
        )
    ]
    findings_b = [
        Finding(
            claim="Semiconductor packaging thermal vias and yield learning",
            support=[],
            confidence=0.8,
        )
    ]

    metrics_a = benchmark_metrics(findings_a, fixture=fixture_a)
    metrics_b = benchmark_metrics(findings_b, fixture=fixture_b)

    assert metrics_a["expected_claim_recall"] > metrics_b["expected_claim_recall"]
    assert metrics_b["expected_claim_recall"] == 0.0
