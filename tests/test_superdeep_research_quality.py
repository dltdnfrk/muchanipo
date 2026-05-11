from __future__ import annotations

import pytest

from src.evidence.artifact import EvidenceRef, Finding
from src.research.depth import VALID_DEPTHS, depth_profile, effective_query_limit
from src.research.karpathy_autoresearch import (
    SourceAuditViolation,
    build_research_quality_audit,
    enforce_source_audit_gate,
)
from src.research.planner import ResearchPlan
from src.report.claim_matrix import build_claim_evidence_matrix, enforce_claim_evidence_gate


TOPIC = "딸기 농가용 저비용 분자진단 키트 시장성"


def _ref(
    ref_id: str,
    *,
    title: str,
    quote: str,
    kind: str = "web",
    grade: str = "B",
    url: str = "https://example.org/source",
) -> EvidenceRef:
    return EvidenceRef(
        id=ref_id,
        source_url=url,
        source_title=title,
        quote=quote,
        source_grade=grade,
        provenance={"kind": kind, "metadata": {"query": TOPIC, "source_text": quote}},
        access_status="abstract_only",
    )


def _plan() -> ResearchPlan:
    return ResearchPlan(
        brief_id="brief-superdeep",
        topic_anchor=TOPIC,
        queries=[
            TOPIC,
            f"{TOPIC} peer reviewed LAMP PCR plant pathogen field validation sensitivity specificity",
            f"{TOPIC} Korea farmer adoption pricing market statistics government",
        ],
        evidence_targets=["market adoption", "field validation", "diagnostic performance"],
    )


def test_superdeep_depth_profile_exceeds_max_with_quality_gate_budget() -> None:
    assert "superdeep" in VALID_DEPTHS
    profile = depth_profile("superdeep")
    max_profile = depth_profile("max")

    assert profile.query_limit > max_profile.query_limit
    assert profile.persona_pool_size > max_profile.persona_pool_size
    assert profile.active_persona_count >= max_profile.active_persona_count
    assert profile.extended_test_time_compute is True
    assert effective_query_limit(profile, source_research=True) >= 18


def test_source_audit_gate_blocks_contaminated_accepted_sources() -> None:
    findings = [
        Finding(
            claim="Generic consumer willingness-to-pay paper was retrieved for a strawberry molecular diagnostics topic.",
            support=[
                _ref(
                    "bad-market",
                    title="Consumer willingness to pay for premium fruit packaging",
                    quote="A survey estimated willingness to pay for premium fruit packaging in retail stores.",
                    kind="industry_report",
                    grade="B",
                )
            ],
            confidence=0.7,
        )
    ]
    audit = build_research_quality_audit(findings, _plan())

    with pytest.raises(SourceAuditViolation, match="source audit gate failed"):
        enforce_source_audit_gate(audit, depth="superdeep")


def test_source_audit_rejects_generic_research_corpus_pages_without_topic_anchor() -> None:
    noisy_live_query = (
        "딸기 농가용 저비용 분자진단 키트 시장성: 국내 시설 딸기 농가의 구매의사, 가격 민감도, "
        "유통채널, 검증/규제 리스크, 90일 사업화 실험 설계까지 source-backed deep research max 수준으로 분석 "
        "distribution channel regulatory adoption case studies"
    )
    plan = ResearchPlan(
        brief_id="brief-live-noisy-query",
        topic_anchor=TOPIC,
        queries=[noisy_live_query],
        evidence_targets=["market adoption", "field validation", "diagnostic performance"],
    )
    findings = [
        Finding(
            claim="A generic DOI corpus page was incorrectly retrieved for strawberry diagnostics.",
            support=[
                EvidenceRef(
                    id="bad-corpus-page",
                    source_url="https://doi.org/10.26782/jmcms.spl.10/2020.06.00041",
                    source_title=(
                        "Special Issue No. – 10, June, 2020 Quantative Methods in Modern Science "
                        "MORPHOLOGICAL AND ANATOMICAL FEATURES OF THE GENUS GAGEA SALISB., "
                        "GROWING IN THE EAST KAZAKHSTAN REGION DOI https://doi.org/10.26782/jmcms.spl.10/2020.06.00041"
                    ),
                    quote=(
                        "The present research focuses on anatomical and morphological features of two Altai species. "
                        "The obtained research results will prove useful for studies of medicinal raw materials and honey plants."
                    ),
                    source_grade="A",
                    provenance={"kind": "academic", "metadata": {"query": noisy_live_query}},
                    access_status="abstract_only",
                )
            ],
            confidence=0.7,
        )
    ]
    audit = build_research_quality_audit(findings, plan)

    evaluation = audit.source_evaluations[0]
    assert evaluation.accepted is False
    assert evaluation.facet_ids == ()
    assert "topic-specific" in evaluation.reason or "relevance score" in evaluation.reason
    with pytest.raises(SourceAuditViolation, match="source audit gate failed"):
        enforce_source_audit_gate(audit, depth="superdeep")


def test_source_audit_rejects_search_result_echo_when_landing_page_is_off_topic() -> None:
    plan = _plan()
    findings = [
        Finding(
            claim="A public-data search-result echo was incorrectly treated as strawberry diagnostics evidence.",
            support=[
                EvidenceRef(
                    id="bad-search-echo",
                    source_url="https://www.data.go.kr/tcs/dss/selectDataSetList.do?keyword=strawberry-diagnostics-market",
                    source_title="범죄 통계 데이터",
                    quote=(
                        "Search result page for 딸기 농가용 저비용 분자진단 키트 시장성; "
                        "the actual dataset title is crime statistics data."
                    ),
                    source_grade="B",
                    provenance={"kind": "government", "metadata": {"query": TOPIC}},
                    access_status="landing_page_only",
                )
            ],
            confidence=0.7,
        )
    ]
    audit = build_research_quality_audit(findings, plan)

    evaluation = audit.source_evaluations[0]
    assert evaluation.accepted is False
    assert evaluation.facet_ids == ()
    assert "search-result echo" in evaluation.reason or "topic-specific" in evaluation.reason


def test_source_audit_rejects_search_result_echo_even_when_title_repeats_topic() -> None:
    plan = _plan()
    findings = [
        Finding(
            claim="A public-data keyword search page repeated the requested topic as its title.",
            support=[
                EvidenceRef(
                    id="bad-topic-echo",
                    source_url=(
                        "https://www.data.go.kr/tcs/dss/selectDataSetList.do?"
                        "keyword=%EB%94%B8%EA%B8%B0%20%EB%86%8D%EA%B0%80%EC%9A%A9"
                    ),
                    source_title=TOPIC,
                    quote="검색 결과 페이지가 제출된 딸기 농가용 저비용 분자진단 키트 시장성 쿼리를 반복한다.",
                    source_grade="B",
                    provenance={"kind": "government", "metadata": {"query": TOPIC}},
                    access_status="abstract_only",
                )
            ],
            confidence=0.7,
        )
    ]
    audit = build_research_quality_audit(findings, plan)

    evaluation = audit.source_evaluations[0]
    assert evaluation.accepted is False
    assert evaluation.facet_ids == ()
    assert "search-result echo" in evaluation.reason


def test_source_audit_gate_passes_when_each_required_facet_has_topic_anchored_sources() -> None:
    findings = [
        Finding(
            claim="Strawberry LAMP assays can detect plant pathogens in field-adjacent workflows.",
            support=[
                _ref(
                    "paper-1",
                    title="LAMP detection of strawberry plant pathogen in field samples",
                    quote="A strawberry plant disease LAMP assay reported field validation with sensitivity and specificity metrics.",
                    kind="academic",
                    url="https://doi.org/10.1000/strawberry-lamp",
                ),
                _ref(
                    "paper-2",
                    title="PCR diagnosis for strawberry pathogen management",
                    quote="PCR and LAMP molecular diagnostic methods were evaluated for strawberry pathogen detection.",
                    kind="academic",
                    url="https://doi.org/10.1000/strawberry-pcr",
                ),
                _ref(
                    "paper-3",
                    title="Review of plant disease diagnostics for strawberry crops",
                    quote="Review of strawberry crop disease diagnostic assays including LAMP, PCR, and field deployment constraints.",
                    kind="academic",
                    url="https://doi.org/10.1000/strawberry-review",
                ),
            ],
            confidence=0.8,
        ),
        Finding(
            claim="Korean strawberry farms need pricing and adoption evidence before kit commercialization.",
            support=[
                _ref(
                    "market-1",
                    title="Korea strawberry farm statistics and production area",
                    quote="Korean government statistics report strawberry farm production area, farm counts, and regional distribution.",
                    kind="web",
                    url="https://kosis.kr/strawberry",
                ),
                _ref(
                    "market-2",
                    title="농가 딸기 병해 진단 키트 가격 도입 조사",
                    quote="국내 딸기 농가 대상 병해 진단 키트 가격, 구매의향, 유통 채널 조사 결과.",
                    kind="industry_report",
                ),
                _ref(
                    "market-3",
                    title="Strawberry disease management kit pricing catalog Korea",
                    quote="Strawberry disease management diagnostic kit pricing and distribution channel information for Korean farms.",
                    kind="web",
                ),
            ],
            confidence=0.8,
        ),
    ]
    audit = build_research_quality_audit(findings, _plan())

    summary = enforce_source_audit_gate(audit, depth="superdeep")

    assert summary["passed"] is True
    assert summary["accepted_source_count"] >= 6
    assert summary["gap_count"] == 0


def test_claim_evidence_gate_requires_each_atomic_claim_to_have_non_mock_citation() -> None:
    refs = [
        _ref(
            "paper-1",
            title="Strawberry LAMP field validation",
            quote="A strawberry plant disease LAMP assay reported field validation sensitivity and specificity metrics.",
            kind="academic",
        )
    ]
    findings = [
        Finding(
            claim="A strawberry plant disease LAMP assay reported field validation sensitivity and specificity metrics.",
            support=refs,
            confidence=0.8,
        ),
        Finding(
            claim="Korean farms will buy the kit at high margins without further evidence.",
            support=[],
            confidence=0.2,
        ),
    ]

    matrix = build_claim_evidence_matrix(findings, refs)

    assert matrix.unsupported_count == 1
    with pytest.raises(SourceAuditViolation, match="unsupported claim blocked report"):
        enforce_claim_evidence_gate(matrix, depth="superdeep")


def test_claim_evidence_gate_does_not_count_rejected_sources_as_supported() -> None:
    refs = [
        _ref(
            "bad-search-echo",
            title=TOPIC,
            quote="검색 결과 페이지가 제출된 딸기 농가용 저비용 분자진단 키트 시장성 쿼리를 반복한다.",
            kind="government",
            url="https://www.data.go.kr/tcs/dss/selectDataSetList.do?keyword=strawberry-diagnostics-market",
        )
    ]
    findings = [
        Finding(
            claim="A search-results page cannot prove strawberry diagnostics market demand.",
            support=refs,
            confidence=0.8,
        )
    ]
    audit = build_research_quality_audit(findings, _plan())
    accepted_ids = {item.source_id for item in audit.source_evaluations if item.accepted}

    matrix = build_claim_evidence_matrix(findings, refs, accepted_evidence_ids=accepted_ids)
    summary = enforce_claim_evidence_gate(matrix, depth="shallow")

    assert accepted_ids == set()
    assert matrix.supported_count == 0
    assert matrix.partial_count == 1
    assert summary["passed"] is False

