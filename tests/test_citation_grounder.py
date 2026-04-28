import sys

import pytest

from conftest import load_script_module


grounder = load_script_module("citation_grounder", "src/eval/citation_grounder.py")


# ---------------------------------------------------------------------------
# 기존 6 tests (narrow C1 정책 반영해 Korean overlap 케이스만 어서션 갱신)
# ---------------------------------------------------------------------------
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


def test_ground_claims_allows_korean_token_overlap():
    """narrow C1: substring 미일치 시 overlap 만으로는 'partial' 까지만 인정."""
    evidence = [
        {
            "id": "E1",
            "source": "ops-note",
            "quote": "한국어 토큰 중첩 검증은 근거 문장과 핵심 주장을 비교한다.",
        }
    ]
    result = grounder.ground_claims(
        consensus="한국어 토큰 중첩 검증은 핵심 주장을 비교한다.",
        evidence=evidence,
        overlap_threshold=0.5,
    )

    # 새 정책 — overlap 단독으로는 supported 불가, partial 로 강등
    assert result["supported"] == 0
    assert result["partial"] == 1
    assert result["per_claim_verdict"][0]["status"] == "partial"


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


# ---------------------------------------------------------------------------
# 신규 6 tests — narrow C1 정책 회귀 방어
# ---------------------------------------------------------------------------
def test_keyword_overlap_alone_yields_partial_not_supported():
    """overlap_ratio 가 supported 임계를 넘어도 substring 미일치 시 partial 로 머무름."""
    evidence = [
        {
            "id": "E1",
            "source": "ops-note",
            "quote": "한국어 토큰 중첩 검증은 근거 문장과 핵심 주장을 비교한다.",
        }
    ]
    # 같은 content-term 을 모두 포함하지만 substring 일치 X (어순/사이값 다름)
    claim = "검증은 한국어 토큰 중첩 핵심 주장 비교."

    result = grounder.ground_claims(
        consensus=claim,
        evidence=evidence,
        overlap_threshold=0.5,
    )

    verdict = result["per_claim_verdict"][0]
    assert verdict["status"] == "partial"
    assert result["supported"] == 0
    assert result["partial"] == 1


def test_substring_match_under_12_chars_now_supported():
    """8자 이상 (구 12자 임계 미만) 한국어 인용도 substring supported 로 인정."""
    short_claim = "검증 패스 가동된다"  # 9자
    evidence = [
        {
            "id": "E1",
            "source": "ops-note",
            "quote": "오늘 검증 패스 가동된다 보고 받음.",
            "source_text": "오늘 검증 패스 가동된다 보고 받음.",
        }
    ]

    result = grounder.ground_claims(consensus=short_claim, evidence=evidence)

    verdict = result["per_claim_verdict"][0]
    assert verdict["status"] == "supported"
    assert verdict["supporting_evidence_ids"] == ["E1"]


def test_lockdown_integration_provenance_failure_excludes_evidence():
    """provenance 검증 실패 evidence 는 supported 후보에서 제외된다."""
    # quote 가 source_text 에 없으므로 lockdown.validate_evidence_provenance 실패
    fabricated_quote = "MuchaNipo replay harness reduces manual regression review by 25% in 2026."
    evidence = [
        {
            "id": "E1",
            "source": "fabricated-source",
            "quote": fabricated_quote,
            "source_text": "전혀 다른 본문 — 인용은 여기 등장하지 않음.",
        }
    ]
    result = grounder.ground_claims(
        consensus=fabricated_quote,
        evidence=evidence,
    )

    # lockdown 모듈이 있으면 provenance 실패 1건, evidence 가 trusted pool 에서 빠짐
    if grounder._lockdown is not None:
        assert result["provenance_failures"] == 1
        assert result["supported"] == 0
        assert result["per_claim_verdict"][0]["status"] == "unsupported"
    else:
        # lockdown 없는 환경에선 graceful — provenance_failures 키만 0 으로 존재
        assert result["provenance_failures"] == 0


def test_redact_applied_to_per_claim_verdict_when_pii_present():
    """claim 텍스트에 PII (이메일/전화) 가 있으면 redact 가 적용된다."""
    if grounder._lockdown is None:
        pytest.skip("lockdown 모듈 미설치 — redact graceful no-op")

    claim_with_pii = "담당자 연락처는 alice@example.com 이며 010-1234-5678 로 회신 바람."
    result = grounder.ground_claims(consensus=claim_with_pii, evidence=[])

    redacted_text = result["per_claim_verdict"][0]["claim"]
    assert "alice@example.com" not in redacted_text
    assert "010-1234-5678" not in redacted_text
    assert "[REDACTED_EMAIL]" in redacted_text
    assert "[REDACTED_KOREAN_PHONE]" in redacted_text


def test_lockdown_optional_import_failure_graceful(monkeypatch):
    """lockdown 모듈이 None 이어도 source_text 기반 ground_claims 가 정상 동작."""
    monkeypatch.setattr(grounder, "_lockdown", None)

    result = grounder.ground_claims(
        consensus="MuchaNipo replay harness reduces manual regression review by 25% in 2026.",
        evidence=[
            {
                "id": "E1",
                "source": "market-brief",
                "quote": "MuchaNipo replay harness reduces manual regression review by 25% in 2026.",
                "source_text": "MuchaNipo replay harness reduces manual regression review by 25% in 2026.",
            }
        ],
    )

    assert result["supported"] == 1
    assert result["provenance_failures"] == 0
    # PII 가 있어도 redact no-op (원문 유지)
    pii_result = grounder.ground_claims(
        consensus="문의는 alice@example.com 으로 보내주세요 항상.",
        evidence=[],
    )
    assert "alice@example.com" in pii_result["per_claim_verdict"][0]["claim"]


def test_fabricated_quote_with_high_overlap_blocked():
    """citation laundering 회귀 — overlap 0.6 이상이어도 substring 없으면 supported 차단."""
    evidence = [
        {
            "id": "E1",
            "source": "ops-note",
            "quote": "MuchaNipo replay harness reduces manual regression review by 25% in 2026.",
        }
    ]
    # 모든 키워드를 짜집기했지만 직접 인용은 아님 (citation laundering)
    laundered_claim = "MuchaNipo replay harness boosts review reduces regression by 99% in 2099."

    result = grounder.ground_claims(
        consensus=laundered_claim,
        evidence=evidence,
        overlap_threshold=0.6,
    )

    verdict = result["per_claim_verdict"][0]
    assert verdict["status"] != "supported"
    assert result["supported"] == 0


def test_quote_only_direct_match_capped_to_partial():
    claim = "MuchaNipo replay harness reduces manual regression review by 25% in 2026."
    result = grounder.ground_claims(
        consensus=claim,
        evidence=[
            {
                "id": "E1",
                "source": "market-brief",
                "quote": claim,
            }
        ],
    )

    verdict = result["per_claim_verdict"][0]
    assert verdict["status"] == "partial"
    assert result["supported"] == 0
    assert result["partial"] == 1
