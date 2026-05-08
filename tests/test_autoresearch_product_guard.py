import json
from pathlib import Path

import src.governance.autoresearch_guard as guard_mod
from src.governance.autoresearch_guard import run_product_guard, run_product_guard_iterations
from src.muchanipo.server import main


def _install_fast_runtime_smoke(monkeypatch, tmp_path):
    report_path = tmp_path / "runtime-smoke-report.md"
    events_path = tmp_path / "runtime-smoke-events.jsonl"
    report_path.write_text(
        "# source-backed report\n\n## Evidence Index\n\nEvidence: `source-1`\n",
        encoding="utf-8",
    )
    events = [
        {
            "event": "run_started",
            "offline": True,
            "source_research": True,
            "depth": "shallow",
        },
    ]
    for stage in guard_mod.RUNTIME_STAGES:
        event = {"event": "stage_started", "stage": stage}
        if stage in {"targeting", "research"}:
            event["reference_projects"] = ["runtime-reference"]
        events.append(event)
        events.append({"event": "stage_completed", "stage": stage})
    events.extend(
        [
            {"event": "research_progress", "stage": "research", "status": "searching", "query": "topic"},
            {
                "event": "research_progress",
                "stage": "research",
                "status": "source_found",
                "source_title": "Official source",
                "source_url": "https://example.com/source",
            },
            {"event": "council_turn", "round": 1},
            *[
                {"event": "report_chunk", "chapter_no": chapter_no}
                for chapter_no in range(1, 7)
            ],
            {"event": "final_report", "chapter_count": 6, "markdown": report_path.read_text(encoding="utf-8")},
            {"event": "done", "pipeline": "full"},
        ]
    )

    def fake_smoke(_root):
        return guard_mod.RuntimeSmokeResult(
            returncode=0,
            stdout="\n".join(json.dumps(event) for event in events) + "\n",
            stderr="",
            timed_out=False,
            elapsed_sec=0.123,
            report_path=report_path,
            events_path=events_path,
        )

    monkeypatch.setattr(guard_mod, "_run_runtime_truth_smoke", fake_smoke)


def test_product_guard_writes_passing_completion_artifact(tmp_path, monkeypatch):
    _install_fast_runtime_smoke(monkeypatch, tmp_path)
    output = tmp_path / "result.json"

    report = run_product_guard(output_path=output)

    assert report["passed"] is True
    assert report["status"] == "passed"
    assert report["autoresearch"]["validation_mode"] == "mission-validator-script"
    assert report["autoresearch"]["metric_name"] == "product_security_risk_score"
    assert output.exists()
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["passed"] is True
    check_ids = {check["id"] for check in written["checks"]}
    assert {
        "six_stage_reference_parity",
        "karpathy_autoresearch_surface",
        "runtime_truth_smoke",
        "secret_scan",
        "dangerous_action_review",
    }.issubset(check_ids)
    assert not written["blockers"]
    assert not written["warnings"]


def test_guard_cli_json_outputs_completion_artifact(tmp_path, capsys, monkeypatch):
    _install_fast_runtime_smoke(monkeypatch, tmp_path)
    output = tmp_path / "guard-result.json"

    rc = main(["guard", "--json", "--output", str(output)])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["autoresearch"]["completion_artifact_path"] == str(output)
    assert output.exists()


def test_product_guard_iterations_require_stable_zero_warning_artifact(tmp_path, monkeypatch):
    _install_fast_runtime_smoke(monkeypatch, tmp_path)
    output = tmp_path / "iterative-result.json"

    report = run_product_guard_iterations(
        output_path=output,
        min_iterations=3,
        max_iterations=3,
    )

    assert report["passed"] is True
    assert report["status"] == "passed"
    assert report["warnings"] == []
    assert report["blockers"] == []
    assert report["autoresearch"]["iteration_mode"] == "iterative_stability"
    assert report["autoresearch"]["iteration_count"] == 3
    assert report["autoresearch"]["stable_iterations"] == 3
    written = json.loads(output.read_text(encoding="utf-8"))
    assert len(written["iterations"]) == 3
    assert all(item["clean"] for item in written["iterations"])


def test_guard_cli_iterate_json_outputs_stable_artifact(tmp_path, capsys, monkeypatch):
    _install_fast_runtime_smoke(monkeypatch, tmp_path)
    output = tmp_path / "guard-iterative-result.json"

    rc = main([
        "guard",
        "--json",
        "--iterate",
        "--min-iterations",
        "2",
        "--max-iterations",
        "2",
        "--output",
        str(output),
    ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["warnings"] == []
    assert payload["autoresearch"]["iteration_count"] == 2
    assert output.exists()


def test_runtime_truth_smoke_fails_on_incomplete_or_mock_report(tmp_path, monkeypatch):
    report_path = tmp_path / "bad-report.md"
    events_path = tmp_path / "bad-events.jsonl"
    report_path.write_text(
        "mock-evidence-1\nTrusted evidence: 0\nUnsupported finding count: 4\n",
        encoding="utf-8",
    )
    events = [
        {"event": "run_started", "offline": True, "source_research": True},
        {"event": "stage_started", "stage": "intake"},
        {"event": "stage_completed", "stage": "intake"},
        {"event": "stage_started", "stage": "targeting"},
    ]

    def fake_smoke(_root):
        return guard_mod.RuntimeSmokeResult(
            returncode=0,
            stdout="\n".join(json.dumps(event) for event in events) + "\n",
            stderr="",
            timed_out=False,
            elapsed_sec=0.123,
            report_path=report_path,
            events_path=events_path,
        )

    monkeypatch.setattr(guard_mod, "_run_runtime_truth_smoke", fake_smoke)

    check = guard_mod._check_runtime_truth_smoke(Path.cwd())

    assert check.status == "failed"
    kinds = {finding.kind for finding in check.findings}
    assert "runtime_stage_completed_mismatch" in kinds
    assert "runtime_report_placeholder_marker" in kinds
    assert "runtime_report_unsupported_findings" in kinds
    assert "runtime_report_zero_trusted_evidence" in kinds
