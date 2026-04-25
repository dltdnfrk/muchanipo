import json

from conftest import load_script_module


calibrator_mod = load_script_module(
    "persona_bias_calibrator",
    "src/eval/persona_bias_calibrator.py",
)


def test_measure_detects_lexical_shift_without_external_dependencies():
    calibrator = calibrator_mod.PersonaBiasCalibrator(audit=False)

    report = calibrator.measure(
        {
            "id": "farmer-long-risk",
            "value_axes": {
                "time_horizon": "long",
                "risk_tolerance": 0.2,
            },
            "occupation": "farmer",
        },
        control_response="The plan improves yield with a fast pilot and broad rollout.",
        persona_response=(
            "The plan protects farm yield with a long field trial, insurance, "
            "and careful cooperative rollout."
        ),
    )

    assert report.persona_id == "farmer-long-risk"
    assert "time_horizon:long" in report.axis_tags
    assert "risk_tolerance:0.2" in report.axis_tags
    assert "occupation:farmer" in report.axis_tags
    assert report.kl_divergence > 0
    assert report.lexical_shift > 0
    assert report.control_token_count > 0
    assert report.persona_token_count > 0
    assert report.shifted_terms[0]["term"]


def test_same_response_has_lower_shift_than_persona_conditioned_response():
    calibrator = calibrator_mod.PersonaBiasCalibrator(audit=False)
    persona = {"id": "ops", "value_axes": {"stakeholder_priority": "primary"}}
    control = "Use cited evidence, validate assumptions, and ship the smallest safe change."

    same = calibrator.measure(persona, control, control)
    shifted = calibrator.measure(
        persona,
        control,
        "Use community benefit, local jobs, household risk, and long-term fairness.",
    )

    assert same.kl_divergence == 0
    assert same.lexical_shift == 0
    assert shifted.kl_divergence > same.kl_divergence
    assert shifted.lexical_shift > same.lexical_shift


def test_aggregate_groups_reports_by_value_axis():
    calibrator = calibrator_mod.PersonaBiasCalibrator(audit=False)
    high = calibrator.measure(
        {"id": "high-risk", "value_axes": {"risk_tolerance": 0.9}},
        "Stable savings plan with limited downside.",
        "Aggressive expansion plan with experimental upside.",
    )
    low = calibrator.measure(
        {"id": "low-risk", "value_axes": {"risk_tolerance": 0.1}},
        "Stable savings plan with limited downside.",
        "Conservative reserve plan with insured downside.",
    )

    result = calibrator.aggregate([high, low])

    assert result["count"] == 2
    assert result["overall"]["count"] == 2
    assert result["overall"]["mean_kl_divergence"] > 0
    assert result["by_axis"]["risk_tolerance:0.9"]["count"] == 1
    assert result["by_axis"]["risk_tolerance:0.1"]["count"] == 1


def test_audit_log_integration_redacts_context(tmp_path, monkeypatch):
    if calibrator_mod._lockdown is None:
        return

    log_path = tmp_path / "bias-audit.jsonl"
    monkeypatch.setattr(calibrator_mod._lockdown, "AUDIT_PATH", log_path)
    calibrator = calibrator_mod.PersonaBiasCalibrator(audit=True)

    calibrator.measure(
        {"id": "contact-bias", "value_axes": {"time_horizon": "short"}},
        "Contact user@example.com for a neutral baseline.",
        "Contact user@example.com for an urgent short-term action.",
    )

    event = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert event["decision"] == "persona_bias_measure"
    assert event["context"]["persona_id"] == "contact-bias"
    payload = json.dumps(event["context"], ensure_ascii=False)
    assert "user@example.com" not in payload
