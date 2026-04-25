from conftest import load_script_module


grounder = load_script_module("citation_grounder", "src/eval/citation_grounder.py")


def test_extract_atomic_claims_deduplicates_and_skips_questions():
    claims = grounder.extract_atomic_claims(
        "- Replay reduces review time.\n- Replay reduces review time.\nIs this true?"
    )

    assert claims == ["Replay reduces review time."]


def test_ground_claims_prefers_substring_support(sample_evidence):
    result = grounder.ground_claims(
        consensus="MuchaNipo replay harness reduces manual regression review by 25% in 2026.",
        evidence=sample_evidence,
    )

    verdict = result["per_claim_verdict"][0]
    assert verdict["status"] == "supported"
    assert verdict["overlap_ratio"] == 1.0
    assert verdict["supporting_evidence_ids"] == ["E1"]


def test_ground_claims_allows_korean_token_overlap(sample_evidence):
    result = grounder.ground_claims(
        consensus="한국어 토큰 중첩 검증은 핵심 주장을 비교한다.",
        evidence=sample_evidence,
        overlap_threshold=0.5,
    )

    assert result["supported"] == 1
    assert result["verified_claim_ratio"] == 1.0


def test_grounding_gate_blocks_unsupported_critical_claim(unsupported_council_report):
    result = grounder.ground_claims(
        consensus=unsupported_council_report["consensus"],
        recommendations=unsupported_council_report["recommendations"],
        evidence=unsupported_council_report["evidence"],
    )

    allow, reason = grounder.grounding_gate(result)

    assert result["unsupported_critical_claim_count"] == 1
    assert allow is False
    assert "unsupported_critical_claims=1" in reason


def test_empty_evidence_yields_unsupported_claim(sample_council_report):
    result = grounder.ground_claims(
        consensus=sample_council_report["consensus"],
        evidence=[],
    )

    assert result["supported"] == 0
    assert result["unsupported"] == result["total_claims"]


def test_no_claims_passes_gate():
    result = grounder.ground_claims(consensus="", evidence=[])

    assert result["verified_claim_ratio"] == 1.0
    assert grounder.grounding_gate(result) == (True, "no_claims_to_verify")
