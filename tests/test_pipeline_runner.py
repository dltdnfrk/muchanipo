from pathlib import Path

from src.pipeline.runner import run_pipeline, round_result_to_digest


def test_round_result_to_digest_extracts_claims_and_confidence():
    digest = round_result_to_digest(
        {
            "convergence": {"consensus_score": 0.82},
            "results": [
                {
                    "analysis": "Primary market signal is strong.",
                    "key_points": ["Customers need fast diagnosis.", "Distribution is the constraint."],
                    "evidence": [{"id": "E1"}, "E2"],
                    "confidence": 0.7,
                }
            ],
        },
        "L1_market_sizing",
        "시장 규모",
    )

    assert digest.layer_id == "L1_market_sizing"
    assert digest.key_claim == "Primary market signal is strong."
    assert digest.body_claims[:2] == ["Customers need fast diagnosis.", "Distribution is the constraint."]
    assert digest.evidence_ref_ids == ["E1", "E2"]
    assert digest.confidence == 0.82


def test_run_pipeline_returns_ten_rounds_six_chapter_report_and_progress():
    events = []

    result = run_pipeline("딸기 진단키트 시장성", progress_callback=events.append, offline=True)

    assert len(result["rounds"]) == 10
    assert result["brief"].is_ready
    assert Path(result["vault_path"]).exists()
    assert Path(result["report_path"]).exists()
    for n in range(1, 7):
        assert f"## Chapter {n}" in result["report_md"]

    started = [event["stage"] for event in events if event["event"] == "stage_started"]
    assert started == [
        "intake",
        "interview",
        "targeting",
        "research",
        "evidence",
        "council",
        "report",
        "finalize",
    ]
    completed = [event["stage"] for event in events if event["event"] == "stage_completed"]
    assert completed == started
