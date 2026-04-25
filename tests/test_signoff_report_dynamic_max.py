from conftest import load_script_module


signoff_report = load_script_module("signoff_report", "src/hitl/signoff-report.py")


def _entry_with_scores(scores):
    return {
        "id": "sq-test",
        "timestamp": "2026-04-25T00:00:00Z",
        "topic": "Dynamic rubric max",
        "council_id": "council-test",
        "eval_result": {
            "scores": scores,
            "total": sum(scores.values()),
            "verdict": "UNCERTAIN",
            "reasoning": "test reasoning",
        },
        "council_report": {
            "consensus": "Consensus text.",
            "confidence": 0.6,
            "evidence": ["Evidence text."],
            "recommendations": ["Check dynamic max."],
        },
    }


def test_dynamic_rubric_max_for_4_axis_input():
    html = signoff_report.generate_html(
        _entry_with_scores({
            "usefulness": 7,
            "reliability": 6,
            "novelty": 5,
            "actionability": 6,
        })
    )

    assert "24/40" in html


def test_dynamic_rubric_max_for_10_axis_input():
    scores = {
        "usefulness": 7,
        "reliability": 7,
        "novelty": 7,
        "actionability": 7,
        "completeness": 7,
        "evidence_quality": 7,
        "perspective_diversity": 7,
        "coherence": 7,
        "depth": 7,
        "impact": 7,
    }

    html = signoff_report.generate_html(_entry_with_scores(scores))

    assert "70/100" in html


def test_dynamic_rubric_max_for_11_axis_input():
    scores = {
        "usefulness": 7,
        "reliability": 7,
        "novelty": 7,
        "actionability": 7,
        "completeness": 7,
        "evidence_quality": 7,
        "perspective_diversity": 7,
        "coherence": 7,
        "depth": 7,
        "impact": 7,
        "citation_fidelity": 7,
    }

    html = signoff_report.generate_html(_entry_with_scores(scores))

    assert "77/110" in html
    assert "Citation Fidelity" in html
