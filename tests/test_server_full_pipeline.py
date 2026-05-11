"""server.py --pipeline=full smoke test (US-TAURI-BRIDGE)."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.muchanipo.server import JSONLineHITLAdapter, serve_full, _PipelineHeartbeat, _build_demo_rounds
from src.pipeline.idea_to_council import _max_plus_benchmark_decision
from src.report.chapter_mapper import ChapterMapper, RoundDigest
from src.report.pyramid_formatter import PyramidFormatter
from src.runtime.live_mode import (
    LiveModeViolation,
    assert_mimo_opencode_policy_credentials,
    mimo_opencode_live_credentials_present,
    mimo_opencode_only_requested_from_env,
)


def _writable_tmp(name: str) -> Path:
    base = os.environ.get("TMPDIR") or "/tmp"
    return Path(base) / name


def test_max_plus_benchmark_decision_treats_zero_weak_source_penalty_as_keep() -> None:
    decision = _max_plus_benchmark_decision(
        {
            "expected_claim_recall": 1.0,
            "evidence_quote_coverage": 1.0,
            "weak_source_penalty": 0.0,
        }
    )

    assert decision == "keep"


def test_mimo_opencode_policy_credential_gate_uses_nonblank_approved_keys_only(monkeypatch):
    for name in (
        "XIAOMI_MIMO_API_KEY",
        "MIMO_API_KEY",
        "OPENCODE_GO_API_KEY",
        "OPENCODE_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MUCHANIPO_VERIFICATION_ROUTING", "mimo_opencode_go_only")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-approved-for-this-policy")
    monkeypatch.setenv("XIAOMI_MIMO_API_KEY", "   ")

    assert mimo_opencode_only_requested_from_env() is True
    assert mimo_opencode_live_credentials_present() is False
    with pytest.raises(LiveModeViolation, match="XIAOMI_MIMO_API_KEY"):
        assert_mimo_opencode_policy_credentials()

    monkeypatch.setenv("OPENCODE_GO_API_KEY", "oc-test")
    assert mimo_opencode_live_credentials_present() is True
    assert_mimo_opencode_policy_credentials()


def test_serve_full_mimo_opencode_policy_fails_before_run_started_without_api_key(tmp_path, monkeypatch):
    for name in ("XIAOMI_MIMO_API_KEY", "MIMO_API_KEY", "OPENCODE_GO_API_KEY", "OPENCODE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MUCHANIPO_VERIFICATION_ROUTING", "mimo_opencode_go_only")
    monkeypatch.setenv("MUCHANIPO_ONLINE", "1")
    stdout = io.StringIO()

    rc = serve_full("딸기 진단키트", report_path=tmp_path / "R.md", stdout=stdout)

    assert rc == 1
    events = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert events[0]["event"] == "error"
    assert events[0]["kind"] == "live_mode_violation"
    assert "mimo_opencode_go_only" in events[0]["message"]
    assert all(event["event"] != "run_started" for event in events)
    assert events[-1]["event"] == "done"
    assert events[-1]["aborted"] is True


def test_serve_full_writes_six_chapters_to_report_md(tmp_path):
    report = tmp_path / "REPORT.md"
    stdout = io.StringIO()
    rc = serve_full("딸기 진단키트", report_path=report, stdout=stdout)
    assert rc == 0
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    for n in range(1, 7):
        assert f"## Chapter {n}" in text, f"Chapter {n} missing"


def test_serve_full_emits_all_pipeline_stages(tmp_path):
    stdout = io.StringIO()
    serve_full("test topic", report_path=tmp_path / "R.md", stdout=stdout)
    lines = [l for l in stdout.getvalue().splitlines() if l.strip()]
    events = [json.loads(l) for l in lines]
    stage_events = [e for e in events if e["event"] == "stage_started"]
    stages = [e["stage"] for e in stage_events]
    assert stages == [
        "intake", "interview", "targeting",
        "research", "evidence", "council",
        "report", "vault", "agents", "finalize",
    ]


def test_serve_full_emits_runtime_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("MUCHANIPO_APP_RUN_ID", "app-run-test-123")
    stdout = io.StringIO()
    serve_full("test topic", report_path=tmp_path / "R.md", stdout=stdout)
    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    started = events[0]
    startup = next(e for e in events if e["event"] == "phase_change" and e["phase"] == "STARTUP")

    assert started["event"] == "run_started"
    assert started["pipeline"] == "full"
    assert started["python_pid"] == os.getpid()
    assert started["python_executable"] == sys.executable
    assert started["app_run_id"] == "app-run-test-123"
    assert startup["data"]["app_run_id"] == "app-run-test-123"
    assert started["run_id"]
    assert started["started_at"]


def test_pipeline_heartbeat_emits_runtime_liveness():
    stdout = io.StringIO()
    heartbeat = _PipelineHeartbeat(run_id="test-run", stream=stdout, interval_sec=0.05)

    heartbeat.start()
    time.sleep(0.08)
    heartbeat.stop()

    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    assert events
    assert events[0]["event"] == "pipeline_heartbeat"
    assert events[0]["run_id"] == "test-run"
    assert events[0]["python_pid"] == os.getpid()
    assert events[0]["python_executable"] == sys.executable


def test_serve_full_emits_ten_council_rounds(tmp_path):
    stdout = io.StringIO()
    serve_full("topic", report_path=tmp_path / "R.md", stdout=stdout)
    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    starts = [e for e in events if e["event"] == "council_round_start"]
    assert len(starts) == 10
    assert [e["round"] for e in starts] == list(range(1, 11))


def test_serve_full_streams_research_progress(tmp_path, monkeypatch):
    monkeypatch.setenv("MUCHANIPO_MAX_PLUS_BENCHMARK_ID", "b1")
    stdout = io.StringIO()
    serve_full(
        "B-1 fluorescent probe diagnosis for Erwinia amylovora fire blight",
        report_path=tmp_path / "R.md",
        stdout=stdout,
    )
    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    progress = [event for event in events if event["event"] == "research_progress"]

    assert progress
    assert any(event["status"] == "searching" and event["query"] for event in progress)
    assert any(event["status"] == "source_found" and event["source_title"] for event in progress)
    assert all(
        event["stage"] == "research"
        for event in progress
        if event["status"] in {"searching", "source_found", "source_evaluated", "knowledge_gap", "facet_summary"}
    )
    assert any(event["stage"] == "quality_gate" for event in progress)
    benchmark_events = [event for event in progress if event.get("status") == "max_plus_benchmark_scored"]
    assert benchmark_events
    benchmark = benchmark_events[-1]
    assert benchmark["benchmark_id"] == "muchanipo-deep-research-max-plus-b1"
    assert set(benchmark["metrics"]) >= {
        "source_authority_score",
        "weak_source_penalty",
        "expected_claim_recall",
        "evidence_quote_coverage",
        "claim_traceability",
    }
    assert benchmark["decision"] in {"keep", "blocked"}


def test_serve_full_streams_council_debate_progress(tmp_path):
    stdout = io.StringIO()
    serve_full("strawberry diagnostics", report_path=tmp_path / "R.md", stdout=stdout)
    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]

    starts = [event for event in events if event["event"] == "council_round_start"]
    turns = [event for event in events if event["event"] == "council_turn"]
    tokens = [event for event in events if event["event"] == "council_persona_token"]

    assert starts and starts[0]["active_persona_count"] > 0
    assert starts[0]["active_persona_ids"]
    assert any(event["council_stage"] == "individual" for event in turns)
    assert any(event["council_stage"] == "peer_review" for event in turns)
    assert any(event["council_stage"] == "chairman" for event in turns)
    assert any(event["delta"] and event["visualization_source"] for event in tokens)


def test_serve_full_shallow_depth_emits_executed_round_count(tmp_path):
    stdout = io.StringIO()
    serve_full("topic", report_path=tmp_path / "R.md", stdout=stdout, depth="shallow")
    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    startup = next(e for e in events if e["event"] == "phase_change" and e["phase"] == "STARTUP")
    starts = [e for e in events if e["event"] == "council_round_start"]
    done = events[-1]

    assert startup["data"]["depth"] == "shallow"
    assert startup["data"]["council_persona_pool_size"] == 24
    assert startup["data"]["active_council_persona_count"] == 6
    assert len(starts) == 6
    assert [e["round"] for e in starts] == list(range(1, 7))
    assert done["depth"] == "shallow"
    assert done["council_persona_pool_size"] == 24
    assert done["active_council_persona_count"] == 6
    assert done["council_turn_count"] > 0


def test_serve_full_emits_six_report_chunks(tmp_path):
    stdout = io.StringIO()
    serve_full("topic", report_path=tmp_path / "R.md", stdout=stdout)
    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    chunks = [e for e in events if e["event"] == "report_chunk"]
    assert len(chunks) == 6
    assert [c["chapter_no"] for c in chunks] == [1, 2, 3, 4, 5, 6]


def test_serve_full_emits_final_report_event_with_markdown(tmp_path):
    stdout = io.StringIO()
    serve_full("topic", report_path=tmp_path / "R.md", stdout=stdout)
    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    finals = [e for e in events if e["event"] == "final_report"]
    assert len(finals) == 1
    assert finals[0]["chapter_count"] == 6
    assert "## Chapter 1" in finals[0]["markdown"]
    assert "## Chapter 6" in finals[0]["markdown"]
    assert "## ReACT Execution Plan" in finals[0]["markdown"]
    assert "## GBrain Compiled Truth + Timeline" in finals[0]["markdown"]


def test_serve_full_emits_done_at_end(tmp_path):
    stdout = io.StringIO()
    serve_full("topic", report_path=tmp_path / "R.md", stdout=stdout)
    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    assert events[-1]["event"] == "done"
    assert events[-1]["pipeline"] == "full"


def test_serve_full_completion_evidence_is_substantive_and_session_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv("MUCHANIPO_APP_RUN_ID", "app-run-substantive-123")
    stdout = io.StringIO()

    rc = serve_full("substantive evidence topic", report_path=tmp_path / "R.md", stdout=stdout)

    assert rc == 0
    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    started = next(event for event in events if event["event"] == "run_started")
    expected_session = started["research_session_id"]
    substantive_events = [
        event
        for event in events
        if event["event"] in {"council_turn", "report_chunk", "final_report", "done"}
    ]
    names = {event["event"] for event in substantive_events}

    assert {"council_turn", "report_chunk", "final_report", "done"}.issubset(names)
    assert all(event["research_session_id"] == expected_session for event in substantive_events)
    assert all(event["app_run_id"] == "app-run-substantive-123" for event in substantive_events)
    assert any(str(event.get("council_stage") or "").strip() for event in substantive_events if event["event"] == "council_turn")
    assert any(str(event.get("markdown") or "").strip() for event in substantive_events if event["event"] == "report_chunk")
    final_report = next(event for event in substantive_events if event["event"] == "final_report")
    done = next(event for event in substantive_events if event["event"] == "done")
    assert final_report["chapter_count"] >= 1
    assert "## Chapter" in final_report["markdown"]
    assert done["council_turn_count"] > 0
    assert done.get("aborted") is not True


def test_serve_full_research_quality_only_stops_after_quality_gates_before_council(tmp_path, monkeypatch):
    monkeypatch.setenv("MUCHANIPO_RESEARCH_QUALITY_ONLY", "1")
    stdout = io.StringIO()
    report = tmp_path / "R.md"

    rc = serve_full("strawberry diagnostics market evidence", report_path=report, stdout=stdout)

    assert rc == 0
    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    quality_events = [
        event
        for event in events
        if event["event"] == "research_progress" and event.get("stage") == "quality_gate"
    ]
    terminal_events = [event["event"] for event in events]
    assert terminal_events.count("research_quality_ready") + terminal_events.count("research_quality_needs_review") == 1
    assert {event["status"] for event in quality_events} >= {
        "source_audit_gate",
        "claim_evidence_gate",
    }
    assert not any(event.get("stage") == "council" for event in events if event["event"] == "stage_started")
    done = events[-1]
    assert done["event"] == "done"
    assert done["status"] in {"research_quality_ready", "research_quality_needs_review"}
    assert done["research_quality_only"] is True
    assert done["research_quality_stop"] in {"before_council", "needs_review_before_council", "blocked_before_council"}
    assert done.get("aborted") is False
    assert not report.exists()


def test_serve_full_waits_for_jsonline_interview_answers(tmp_path, monkeypatch):
    import src.pipeline.runner as runner_mod

    calls: list[str] = []

    def fake_run_pipeline(topic, **kwargs):
        calls.append(topic)
        return {
            "rounds": _build_demo_rounds(topic),
            "executed_council_round_count": 1,
            "council_turn_transcript": [],
            "report_md": "# Report\n\n## Chapter 1\n\nbody\n",
            "council_persona_pool_size": 1,
            "active_council_persona_count": 1,
        }

    monkeypatch.setattr(runner_mod, "run_pipeline", fake_run_pipeline)
    stdin = io.StringIO(
        "\n".join(
            json.dumps(
                {
                    "action": "interview_answer",
                    "q_id": f"Q{idx}",
                    "answer": f"answer {idx}",
                }
            )
            for idx in range(1, 7)
        )
        + "\n"
    )
    stdout = io.StringIO()

    rc = serve_full(
        "base topic",
        report_path=tmp_path / "R.md",
        stdout=stdout,
        stdin=stdin,
        wait_for_input=True,
    )

    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    question_events = [e for e in events if e["event"] == "interview_question"]
    ontology_events = [e for e in events if e["event"] == "interview_ontology_delta"]
    clarity_events = [e for e in events if e["event"] == "deep_interview_progress"]
    artifact_events = [e for e in events if e["event"] == "deep_interview_artifacts"]
    phase_events = [e for e in events if e["event"] == "phase_change" and e.get("phase") == "INTERVIEW"]
    first_pipeline_index = next(
        i
        for i, e in enumerate(events)
        if e["event"] in {"council_round_start", "report_chunk", "done"}
    )
    first_question_index = next(i for i, e in enumerate(events) if e["event"] == "interview_question")
    first_ontology_index = next(i for i, e in enumerate(events) if e["event"] == "interview_ontology_delta")
    first_clarity_index = next(i for i, e in enumerate(events) if e["event"] == "deep_interview_progress")

    assert rc == 0
    assert len(question_events) == 6
    assert len(ontology_events) == 6
    assert clarity_events
    assert artifact_events
    assert phase_events[0]["data"]["workflow"] == "show-me-the-prd"
    assert phase_events[0]["data"]["workflow_document_outputs"] == [
        "PRD/01_PRD.md",
        "PRD/02_DATA_MODEL.md",
        "PRD/03_PHASES.md",
        "PRD/04_PROJECT_SPEC.md",
    ]
    assert phase_events[0]["data"]["workflow_research_batches"][0]["queries"]
    assert first_clarity_index < first_question_index
    assert first_ontology_index < first_question_index
    assert clarity_events[0]["phase"] == "idea_dump"
    assert clarity_events[0]["stage"] == "intake"
    assert clarity_events[0]["ambiguity_score"] >= 0
    assert question_events[0]["q_id"] == "Q1_research_question"
    assert question_events[0]["header"] == "핵심 개체·질문"
    assert question_events[0]["data"]["planning_schema"] == "socratic_ontology_extraction"
    assert question_events[0]["data"]["deep_interview"]["focus_dimension"] == "Q1_research_question"
    assert question_events[0]["data"]["deep_interview"]["phase"] == "question"
    assert question_events[0]["targets_unknown_ids"]
    assert question_events[0]["question_quality_gate"]["passed"] is True
    assert question_events[0]["data"]["ontology_state"]["unknowns"]
    assert ontology_events[0]["unknowns"]
    assert ontology_events[0]["targets_unknown_ids"] == question_events[0]["targets_unknown_ids"]
    assert ontology_events[0]["data"]["planning_schema"] == "socratic_ontology_extraction"
    assert "핵심 개체" in question_events[0]["preview"]
    assert question_events[0]["options"][0]["description"]
    assert any(event["phase"] == "research_batch" for event in clarity_events)
    artifact = artifact_events[0]
    assert artifact["workflow"] == "show-me-the-prd"
    assert artifact["document_count"] == 4
    assert artifact["document_outputs"] == [
        "PRD/01_PRD.md",
        "PRD/02_DATA_MODEL.md",
        "PRD/03_PHASES.md",
        "PRD/04_PROJECT_SPEC.md",
    ]
    assert "# Product Requirements Document" in artifact["data"]["documents"]["PRD/01_PRD.md"]
    assert "answer 2" in artifact["data"]["documents"]["PRD/01_PRD.md"]
    assert artifact["data"]["document_manifest"][0]["chars"] > 100
    assert first_question_index < first_pipeline_index
    assert calls and "answer 1" in calls[0]


@pytest.mark.parametrize("q1_selected", ["A", "한 문장 제품 정의"])
def test_serve_full_does_not_use_q1_format_choice_as_research_topic(tmp_path, monkeypatch, q1_selected):
    import src.pipeline.runner as runner_mod

    calls: list[str] = []

    def fake_run_pipeline(topic, **kwargs):
        calls.append(topic)
        return {
            "rounds": _build_demo_rounds(topic),
            "executed_council_round_count": 1,
            "council_turn_transcript": [],
            "report_md": "# Report\n\n## Chapter 1\n\nbody\n",
            "council_persona_pool_size": 1,
            "active_council_persona_count": 1,
        }

    monkeypatch.setattr(runner_mod, "run_pipeline", fake_run_pipeline)
    lines = [
        json.dumps({"action": "interview_answer", "q_id": "Q1_research_question", "selected": q1_selected}),
        json.dumps({"action": "interview_answer", "q_id": "Q2_purpose", "answer": "학습·이해"}),
        json.dumps({"action": "interview_answer", "q_id": "Q3_context", "answer": "데이터 사이언스 / 지식 그래프 맥락"}),
        json.dumps({"action": "interview_answer", "q_id": "Q4_known", "answer": "온톨로지, RDF, OWL, knowledge graph"}),
        json.dumps({"action": "interview_answer", "q_id": "Q5_deliverable", "answer": "개념 설명 리서치 리포트"}),
        json.dumps({"action": "interview_answer", "q_id": "Q6_quality", "answer": "학술 논문 우선"}),
    ]
    stdin = io.StringIO("\n".join(lines) + "\n")
    stdout = io.StringIO()

    rc = serve_full(
        "데이터 사이언스 분야에서의 온톨로지",
        report_path=tmp_path / "R.md",
        stdout=stdout,
        stdin=stdin,
        wait_for_input=True,
    )

    assert rc == 0
    assert calls
    assert "데이터 사이언스 분야에서의 온톨로지" in calls[0]
    assert "한 문장 제품 정의" not in calls[0]
    assert "[Q1_research_question]" not in calls[0]
    assert "[Q2_purpose] 학습·이해" in calls[0]
    assert "[Q3_context] 데이터 사이언스 / 지식 그래프 맥락" in calls[0]


def test_serve_full_wires_jsonline_hitl_gate_when_waiting(tmp_path, monkeypatch):
    import src.pipeline.runner as runner_mod

    gate_statuses: list[str] = []

    def fake_run_pipeline(topic, **kwargs):
        hitl_adapter = kwargs["hitl_adapter"]
        result = hitl_adapter.gate("plan", {"topic": topic})
        gate_statuses.append(result.status)
        return {
            "rounds": _build_demo_rounds(topic),
            "executed_council_round_count": 1,
            "council_turn_transcript": [],
            "report_md": "# Report\n\n## Chapter 1\n\nbody\n",
            "council_persona_pool_size": 1,
            "active_council_persona_count": 1,
        }

    monkeypatch.setattr(runner_mod, "run_pipeline", fake_run_pipeline)
    lines = [
        json.dumps({"action": "interview_answer", "q_id": f"Q{idx}", "answer": f"answer {idx}"})
        for idx in range(1, 7)
    ]
    lines.append(json.dumps({"action": "hitl_decision", "gate": "plan", "status": "approved"}))
    stdin = io.StringIO("\n".join(lines) + "\n")
    stdout = io.StringIO()

    rc = serve_full(
        "base topic",
        report_path=tmp_path / "R.md",
        stdout=stdout,
        stdin=stdin,
        wait_for_input=True,
    )

    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    gates = [event for event in events if event["event"] == "hitl_gate"]
    assert rc == 0
    assert gate_statuses == ["approved"]
    assert gates and gates[0]["gate"] == "plan"
    assert gates[0]["options"][0]["value"] == "approved"


def test_jsonline_report_hitl_gate_uses_compact_payload():
    report_md = "# Report\n\n" + ("body\n" * 3000)
    stdin = io.StringIO(json.dumps({"action": "hitl_decision", "gate": "report", "status": "approved"}) + "\n")
    stdout = io.StringIO()

    result = JSONLineHITLAdapter(stdout=stdout, stdin=stdin).gate_report(report_md)

    event = json.loads(stdout.getvalue().splitlines()[0])
    payload = event["data"]["payload"]
    assert result.status == "approved"
    assert event["gate"] == "report"
    assert payload["report_md_chars"] == len(report_md)
    assert "report_md" not in payload
    assert len(json.dumps(event, ensure_ascii=False)) < 6000


def test_jsonline_plan_gate_accepts_inline_annotations():
    action = {
        "action": "hitl_decision",
        "gate": "plan",
        "status": "approved",
        "annotations": [
            {
                "type": "edit",
                "target": "planning_prd.overview.one_line",
                "replacement": "edited plan",
            }
        ],
        "comment": "inline plan review edits: 1",
    }
    stdin = io.StringIO(json.dumps(action) + "\n")
    stdout = io.StringIO()

    result = JSONLineHITLAdapter(stdout=stdout, stdin=stdin).gate(
        "plan",
        {
            "design_doc": {"pain_root": "raw"},
            "consensus_plan": {"consensus_score": 0.9, "gate_passed": True},
            "gate_reason": "ok",
            "editable_plan": {
                "editable_summary": {
                    "research_question": "raw",
                    "purpose": "decision",
                }
            },
        },
    )

    event = json.loads(stdout.getvalue().splitlines()[0])
    assert result.status == "approved"
    assert result.annotations == action["annotations"]
    assert event["data"]["payload"]["editable_plan"]["editable_summary"]["purpose"] == "decision"
    assert "Inline edit" in event["preview"]


def test_serve_full_emits_terminal_error_on_live_mode_violation(tmp_path, monkeypatch):
    import src.pipeline.runner as runner_mod

    def fail_live(*args, **kwargs):
        raise LiveModeViolation("live evidence missing")

    monkeypatch.setattr(runner_mod, "run_pipeline", fail_live)
    stdout = io.StringIO()

    rc = serve_full("topic", report_path=tmp_path / "R.md", stdout=stdout)

    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    assert rc == 1
    assert events[-2]["event"] == "error"
    assert events[-2]["kind"] == "live_mode_violation"
    assert "live evidence missing" in events[-2]["message"]
    assert events[-1]["event"] == "done"
    assert events[-1]["pipeline"] == "full"
    assert events[-1]["aborted"] is True
    assert events[-1]["memory_policy"] == "no_implicit_cross_session_memory"
    assert events[-1]["imported_knowledge_refs"] == []
    assert not (tmp_path / "R.md").exists()


def test_serve_full_emits_terminal_error_on_pipeline_exception(tmp_path, monkeypatch):
    import src.pipeline.runner as runner_mod

    def fail_pipeline(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(runner_mod, "run_pipeline", fail_pipeline)
    stdout = io.StringIO()

    rc = serve_full("topic", report_path=tmp_path / "R.md", stdout=stdout)

    events = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    assert rc == 1
    assert events[-2]["event"] == "error"
    assert events[-2]["kind"] == "pipeline_error"
    assert events[-2]["error_class"] == "RuntimeError"
    assert "provider unavailable" in events[-2]["message"]
    assert events[-1]["event"] == "done"
    assert events[-1]["pipeline"] == "full"
    assert events[-1]["aborted"] is True
    assert events[-1]["memory_policy"] == "no_implicit_cross_session_memory"
    assert events[-1]["imported_knowledge_refs"] == []
    assert not (tmp_path / "R.md").exists()


def test_demo_rounds_produce_full_six_chapter_mapping():
    rounds = _build_demo_rounds("test topic")
    chapters = ChapterMapper().map(rounds)
    formatted = PyramidFormatter().reorder_all(chapters)
    assert len(formatted) == 6
    assert formatted[0].title == "Executive Summary"
    # SCR present in chapter 1
    assert formatted[0].scr is not None
    assert formatted[0].scr["situation"]
    assert formatted[0].scr["complication"]
    assert formatted[0].scr["resolution"]


def test_serve_subcommand_dispatches_to_full_pipeline_via_cli(tmp_path):
    """python -m muchanipo serve --pipeline full 으로 호출 시에도 동작."""
    report = _writable_tmp("smoke_report.md")
    proc = subprocess.run(
        [
            sys.executable, "-m", "muchanipo", "serve",
            "--topic", "smoke topic",
            "--pipeline", "full",
            "--report-path", str(report),
            "--no-wait",
        ],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    text = report.read_text(encoding="utf-8")
    for n in range(1, 7):
        assert f"## Chapter {n}" in text
    report.unlink(missing_ok=True)
