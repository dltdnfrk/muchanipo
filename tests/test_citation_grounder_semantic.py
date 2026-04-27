from conftest import load_script_module


grounder = load_script_module("citation_grounder_semantic", "src/eval/citation_grounder.py")


def test_semantic_match_accepts_english_paraphrase_by_jaccard():
    ok, score, details = grounder.semantic_match(
        "In 2026 replay harness reduces manual regression review by 25%.",
        "The source states that replay harness reduces manual regression review by 25% in 2026 for local eval loops.",
    )

    assert ok is True
    assert score >= 0.6
    assert details["method"] in {"jaccard", "trigram"}


def test_semantic_match_accepts_korean_reordered_claim_by_jaccard():
    ok, score, details = grounder.semantic_match(
        "한국어 토큰 중첩 검증 핵심 주장 비교",
        "근거 문장 기반으로 핵심 주장 비교 한국어 토큰 중첩 검증 수행",
    )

    assert ok is True
    assert score >= 0.6
    assert details["method"] == "jaccard"


def test_semantic_match_accepts_mixed_korean_english_terms():
    ok, score, details = grounder.semantic_match(
        "citation grounding gate demotes unsupported critical claims",
        "평가 단계에서 citation grounding gate는 unsupported critical claims를 demotes 처리한다.",
    )

    assert ok is True
    assert score >= 0.6
    assert details["method"] in {"jaccard", "trigram"}


def test_semantic_match_accepts_short_phrase_by_trigram_overlap():
    ok, score, details = grounder.semantic_match(
        "groundinggate",
        "The report shows grounding-gate behavior for unsupported claims.",
        threshold=0.45,
    )

    assert ok is True
    assert score >= 0.45
    assert details["method"] == "trigram"


def test_ground_claims_uses_semantic_fallback_with_source_text():
    evidence = [
        {
            "id": "E1",
            "quote": "Replay harness reduces manual regression review by 25% in 2026.",
            "source_text": (
                "Replay harness reduces manual regression review by 25% in 2026. "
                "The evaluation note links this to local regression checks."
            ),
        }
    ]

    result = grounder.ground_claims(
        consensus="In 2026 replay harness reduces regression review manually by 25%.",
        evidence=evidence,
    )

    verdict = result["per_claim_verdict"][0]
    assert verdict["status"] == "supported"
    assert verdict["match_method"] in {"jaccard", "trigram"}
    assert verdict["supporting_evidence_ids"] == ["E1"]


def test_semantic_match_rejects_unrelated_english_text():
    ok, score, details = grounder.semantic_match(
        "Replay harness reduces manual regression review.",
        "The product roadmap discusses payment routing and account provisioning.",
    )

    assert ok is False
    assert score < 0.6
    assert details["method"] != "substring"


def test_semantic_match_rejects_unrelated_korean_text():
    ok, score, _details = grounder.semantic_match(
        "한국어 토큰 중첩 검증 핵심 주장 비교",
        "결제 시스템은 사용자 청구서와 구독 상태를 동기화한다",
    )

    assert ok is False
    assert score < 0.6


def test_semantic_match_rejects_numeric_mismatch():
    ok, score, details = grounder.semantic_match(
        "Replay harness reduces manual regression review by 99% in 2099.",
        "Replay harness reduces manual regression review by 25% in 2026.",
    )

    assert ok is False
    assert score == 0.0
    assert details["method"] == "numeric_mismatch"


def test_semantic_match_rejects_low_overlap_mixed_language():
    ok, score, _details = grounder.semantic_match(
        "citation grounding gate critical claims",
        "한국 농가 페르소나 샘플은 지역과 직업 정보를 포함한다.",
    )

    assert ok is False
    assert score < 0.6


def test_ground_claims_keeps_quote_only_overlap_partial():
    evidence = [
        {
            "id": "E1",
            "quote": "한국어 토큰 중첩 검증은 근거 문장과 핵심 주장을 비교한다.",
        }
    ]

    result = grounder.ground_claims(
        consensus="한국어 토큰 중첩 검증은 핵심 주장을 비교한다.",
        evidence=evidence,
        overlap_threshold=0.5,
    )

    verdict = result["per_claim_verdict"][0]
    assert verdict["status"] == "partial"
    assert verdict["match_method"] == "overlap"


def test_semantic_threshold_boundary():
    quote = "alpha beta gamma"
    source_text = "alpha beta delta"

    accepted, score, _details = grounder.semantic_match(quote, source_text, threshold=0.5)
    rejected, same_score, _details = grounder.semantic_match(quote, source_text, threshold=0.51)

    assert score == 0.5
    assert same_score == 0.5
    assert accepted is True
    assert rejected is False
