from pathlib import Path

from src.evidence.artifact import EvidenceRef, Finding
from src.interview.brief import ResearchBrief
from src.research.karpathy_autoresearch import KarpathyAutoresearchRunner, build_research_quality_audit
from src.research.planner import ResearchPlan, ResearchPlanner


def _plan(question: str):
    return ResearchPlanner().plan(ResearchBrief(raw_idea=question, research_question=question, purpose="research_report"))


def test_autoresearch_metric_prefers_topic_relevant_evidence_over_offtopic_a_grade(tmp_path: Path):
    """Deep-research quality must not optimize only for source grade/count.

    An A-grade DOI about asset pricing is worse evidence for a strawberry
    molecular-diagnostics topic than a lower-grade but directly relevant source.
    """

    plan = _plan("딸기 농가용 저비용 분자진단 키트 시장성")

    class Runner:
        def __init__(self):
            self.calls = 0
            self.last_backend_trace = []

        def run(self, candidate_plan):
            self.calls += 1
            query = candidate_plan.queries[0]
            if self.calls == 1:
                ref = EvidenceRef(
                    id="doi:asset-pricing",
                    source_url="https://doi.org/10.0000/asset",
                    source_title="Asset Pricing With Heterogeneous Risk Aversion",
                    quote="asset pricing and portfolio risk constraints",
                    source_grade="A",
                    provenance={"kind": "crossref", "doi": "10.0000/asset", "metadata": {"query": query}},
                )
            else:
                ref = EvidenceRef(
                    id="field-note:strawberry-diagnostics",
                    source_url="https://example.org/strawberry-diagnostics",
                    source_title="Strawberry plant pathogen molecular diagnostic kit field detection",
                    quote="strawberry farmers need low-cost molecular diagnostic kit field detection evidence",
                    source_grade="B",
                    provenance={"kind": "web", "metadata": {"query": query}},
                )
            self.last_backend_trace = [{"backend": "test", "query": query, "status": "ok", "count": 1}]
            return [Finding(claim=ref.quote or ref.source_title or "claim", support=[ref], confidence=0.7)]

    runner = KarpathyAutoresearchRunner(
        Runner(),
        iteration_budget=2,
        work_root=tmp_path,
        source_dir=Path("third_party/karpathy-autoresearch"),
        run_tag="quality-prefers-relevance",
    )

    findings = runner.run(plan)

    assert runner.last_loop_result is not None
    assert runner.last_loop_result.best_iteration == 2
    assert findings[0].support[0].id == "field-note:strawberry-diagnostics"


def test_autoresearch_source_grade_suffix_does_not_make_any_doi_relevant(tmp_path: Path):
    plan = _plan("딸기 농가용 저비용 분자진단 키트 시장성")

    class Runner:
        def __init__(self):
            self.calls = 0
            self.last_backend_trace = []

        def run(self, candidate_plan):
            self.calls += 1
            query = candidate_plan.queries[0]
            if self.calls == 1:
                ref = EvidenceRef(
                    id="empty",
                    source_url=None,
                    source_title="No evidence",
                    quote=query,
                    source_grade="D",
                    provenance={"kind": "empty", "metadata": {"query": query}},
                )
            elif self.calls == 2:
                # The source-grade candidate query contains the literal word DOI.
                # That must not make an unrelated DOI URL topic-relevant.
                ref = EvidenceRef(
                    id="doi:asset-pricing",
                    source_url="https://doi.org/10.0000/asset",
                    source_title="Asset Pricing With Heterogeneous Risk Aversion",
                    quote="asset pricing and portfolio risk constraints",
                    source_grade="A",
                    provenance={"kind": "crossref", "doi": "10.0000/asset", "metadata": {"query": query}},
                )
            else:
                ref = EvidenceRef(
                    id="field-note:strawberry-diagnostics",
                    source_url="https://example.org/strawberry-diagnostics",
                    source_title="Strawberry plant pathogen molecular diagnostic kit field detection",
                    quote="strawberry farmers need low-cost molecular diagnostic kit field detection evidence",
                    source_grade="B",
                    provenance={"kind": "web", "metadata": {"query": query}},
                )
            self.last_backend_trace = [{"backend": "test", "query": query, "status": "ok", "count": 1}]
            return [Finding(claim=ref.quote or ref.source_title or "claim", support=[ref], confidence=0.7)]

    runner = KarpathyAutoresearchRunner(
        Runner(),
        iteration_budget=3,
        work_root=tmp_path,
        source_dir=Path("third_party/karpathy-autoresearch"),
        run_tag="quality-ignores-doi-token",
    )

    findings = runner.run(plan)

    assert runner.last_loop_result is not None
    assert runner.last_loop_result.best_iteration == 3
    assert findings[0].support[0].id == "field-note:strawberry-diagnostics"


def test_relevance_ignores_numeric_doi_prefix_overlap(tmp_path: Path):
    plan = _plan("10 best practices for agent memory")

    class Runner:
        def __init__(self):
            self.calls = 0
            self.last_backend_trace = []

        def run(self, candidate_plan):
            self.calls += 1
            query = candidate_plan.queries[0]
            if self.calls == 1:
                ref = EvidenceRef(
                    id="doi:asset-pricing",
                    source_url="https://doi.org/10.0000/asset",
                    source_title="Asset Pricing With Heterogeneous Risk Aversion",
                    quote="portfolio risk constraints",
                    source_grade="A",
                    provenance={"kind": "crossref", "metadata": {"query": query}},
                )
            else:
                ref = EvidenceRef(
                    id="web:agent-memory",
                    source_url="https://example.org/agent-memory",
                    source_title="Agent memory architecture best practices",
                    quote="agent memory architecture retrieval best practices for long horizon systems",
                    source_grade="B",
                    provenance={"kind": "web", "metadata": {"query": query}},
                )
            self.last_backend_trace = [{"backend": "test", "query": query, "status": "ok", "count": 1}]
            return [Finding(claim=ref.quote or ref.source_title or "claim", support=[ref], confidence=0.7)]

    runner = KarpathyAutoresearchRunner(
        Runner(),
        iteration_budget=2,
        work_root=tmp_path,
        source_dir=Path("third_party/karpathy-autoresearch"),
        run_tag="quality-ignores-numeric-doi-prefix",
    )

    findings = runner.run(plan)

    assert runner.last_loop_result is not None
    assert runner.last_loop_result.best_iteration == 2
    assert findings[0].support[0].id == "web:agent-memory"


def test_autoresearch_candidate_queries_do_not_inject_vertical_suffixes_for_unrelated_topics(tmp_path: Path):
    unrelated_topics = [
        "LLM memory architecture for long-horizon agents",
        "cybersecurity intrusion detection with graph embeddings",
        "probability distribution shift detection in ML systems",
        "stock market forecasting with transformers",
        "주식시장 예측 transformers",
        "증권시장 변동성 예측",
        "암호화폐 시장 예측",
        "financial market adoption pricing SaaS",
    ]
    runner = KarpathyAutoresearchRunner(
        base_runner=object(),
        iteration_budget=4,
        work_root=tmp_path,
        source_dir=Path("third_party/karpathy-autoresearch"),
        run_tag="query-neutrality",
    )

    for topic in unrelated_topics:
        plan = _plan(topic)
        mutated_queries = [query for candidate in runner._candidate_plans(plan) for query in candidate.plan.queries]
        joined = "\n".join(mutated_queries).lower()

        assert "korea" not in joined
        assert "diagnostic accuracy" not in joined
        assert "field validation sensitivity specificity" not in joined
        assert "willingness to pay" not in joined


def test_quality_audit_rejects_offtopic_a_grade_doi_even_for_general_facet():
    plan = ResearchPlan(
        brief_id="brief-strawberry-diagnostics-market",
        queries=["딸기 농가용 저비용 분자진단 키트 시장성"],
    )
    off_topic = EvidenceRef(
        id="doi:waterfront-development",
        source_url="https://doi.org/10.21740/jas.2025.11.30.2.521",
        source_title="Structural Limitations and Improvement Directions of Waterfront Development in Korea",
        quote="Comparative study of representative waterfront development cases in Korea.",
        source_grade="A",
        provenance={"kind": "doi", "metadata": {"query": "limitations constraints counter evidence failure cases"}},
    )

    audit = build_research_quality_audit(
        [Finding(claim="off-topic waterfront claim", support=[off_topic])],
        plan,
    )

    evaluation = audit.source_evaluations[0]
    assert evaluation.accepted is False
    assert evaluation.relevance_score < 0.35
    assert "relevance" in evaluation.reason or "overlap" in evaluation.reason


def test_diagnostics_market_topic_infers_specific_facets_not_general_only():
    plan = ResearchPlan(
        brief_id="brief-strawberry-diagnostics-market",
        queries=["딸기 농가용 저비용 분자진단 키트 시장성 한국 농가 가격 도입 현장 검증"],
    )

    audit = build_research_quality_audit([], plan)
    facet_ids = {facet.id for facet in audit.facets}

    assert "scientific" in facet_ids
    assert "field_validation" in facet_ids
    assert "market" in facet_ids
    assert "regional_adoption" in facet_ids
    assert "general" not in facet_ids


def test_market_adoption_facet_rejects_cross_domain_adoption_source():
    plan = ResearchPlan(
        brief_id="brief-strawberry-diagnostics-market",
        queries=[
            "딸기 농가용 저비용 분자진단 키트 시장성",
            "strawberry molecular diagnostic plant pathogen detection kit low cost farmer field validation market adoption pricing Korea",
            "strawberry molecular diagnostic plant pathogen detection kit low cost farmer field validation market adoption pricing Korea Korea agricultural statistics farmer willingness to pay",
        ],
    )
    off_topic_market = EvidenceRef(
        id="web:nigerian-banking-fraud-adoption",
        source_url="https://example.org/nigerian-banking-fraud-detection-adoption",
        source_title="Adoption of AI-Driven Fraud Detection System in the Nigerian Banking Sector: An Analysis of Cost, Compliance, and Competition",
        quote="The study analyzes adoption, compliance cost, market competition, and willingness to pay for fraud detection systems in Nigerian banking.",
        source_grade="B",
        provenance={
            "kind": "web",
            "metadata": {
                "query": "strawberry molecular diagnostic plant pathogen detection kit low cost farmer field validation market adoption pricing Korea government statistics willingness to pay adoption"
            },
        },
    )

    audit = build_research_quality_audit(
        [Finding(claim="off-topic adoption market claim", support=[off_topic_market])],
        plan,
    )

    evaluation = audit.source_evaluations[0]
    assert evaluation.accepted is False
    assert evaluation.relevance_score < 0.35
    assert "market" not in evaluation.facet_ids
    assert "overlap" in evaluation.reason or "relevance" in evaluation.reason


def test_live_verification_10_arxiv_farmer_galaxy_payload_gets_no_regional_adoption_facet():
    """검증 10 live payload: generic 'farmer' in an astronomy package is not regional adoption evidence."""

    plan = ResearchPlan(
        brief_id="brief-diagnostics-market",
        queries=[
            "low cost molecular diagnostic kit market adoption pricing source-backed Deep Research council persona verification 10",
            "molecular diagnostic pathogen detection kit low cost field validation market adoption pricing Korea regional statistics willingness to pay",
        ],
    )
    off_topic_farmer = EvidenceRef(
        id="arxiv:http://arxiv.org/abs/2310.07757v1",
        source_url="http://arxiv.org/abs/2310.07757v1",
        source_title="The Farmer: A reproducible profile-fitting photometry package for deep galaxy surveys",
        quote="The Farmer is a reproducible profile-fitting photometry package for deep galaxy surveys and astronomical imaging workflows.",
        source_grade="B",
        provenance={
            "kind": "arxiv",
            "metadata": {
                "query": "molecular diagnostic pathogen detection kit low cost field validation market adoption pricing Korea regional statistics willingness to pay"
            },
        },
    )

    audit = build_research_quality_audit(
        [Finding(claim="off-topic farmer adoption claim", support=[off_topic_farmer])],
        plan,
    )

    evaluation = audit.source_evaluations[0]
    assert evaluation.accepted is False
    assert "regional_adoption" not in evaluation.facet_ids
    assert "field_validation" not in evaluation.facet_ids



def test_live_verification_9_nigerian_banking_payload_gets_no_market_facet():
    """Payload-faithful RED test from 검증 9: generic adoption/cost is not market evidence.

    The bug source was accepted because the query had diagnostic/Korea terms while
    the source itself was about Nigerian banking fraud detection. The gate must judge source-side
    domain overlap, not provenance-query terms.
    """

    plan = ResearchPlan(
        brief_id="brief-diagnostics-market",
        queries=[
            "low cost molecular diagnostic kit market adoption pricing",
            "molecular diagnostic pathogen detection kit low cost field validation market adoption pricing Korea",
            "molecular diagnostic pathogen detection kit low cost field validation market adoption pricing Korea distribution channel regulatory adoption official statistics DOI peer reviewed source evidence",
        ],
    )
    off_topic_market = EvidenceRef(
        id="arxiv:http://arxiv.org/abs/2511.00061v1",
        source_url="http://arxiv.org/abs/2511.00061v1",
        source_title="Adoption of AI-Driven Fraud Detection System in the Nigerian Banking Sector: An Analysis of Cost, Compliance, and Competency",
        quote=(
            "The inception of AI-based fraud detection systems has presented the banking sector across the globe "
            "the opportunity to enhance fraud prevention mechanisms. However, the extent of adoption in Nigeria "
            "has been slow, fragmented, and inconsistent due to high cost of implementation and lack of technical "
            "expertise. This study seeks to investigate extent of adoption and determinants of AI-driven fraud "
            "detection systems in Nigerian banks. The results showed that regulatory compliance, staff competency "
            "and perceived effectiveness accelerate the uptake of AI-driven fraud detection systems adoption."
        ),
        source_grade="B",
        provenance={
            "kind": "arxiv",
            "metadata": {
                "query": "molecular diagnostic pathogen detection kit low cost field validation market adoption pricing Korea distribution channel regulatory adoption official statistics DOI peer reviewed source evidence"
            },
        },
    )

    audit = build_research_quality_audit(
        [Finding(claim="off-topic adoption market claim", support=[off_topic_market])],
        plan,
    )

    evaluation = audit.source_evaluations[0]
    assert evaluation.accepted is False
    assert evaluation.relevance_score < 0.35
    assert "market" not in evaluation.facet_ids
    assert "regional_adoption" not in evaluation.facet_ids


def test_generic_korea_saas_market_source_does_not_satisfy_specific_healthcare_adoption_facets():
    """A bridge-query match is not enough for market/regional adoption evidence.

    Korea/SaaS/adoption/pricing are channel/facet terms. For a healthcare topic,
    the source itself must still mention the healthcare domain.
    """

    plan = _plan("Korea home healthcare SaaS market adoption pricing")
    broad_saas_market = EvidenceRef(
        id="web:korea-saas-market",
        source_url="https://example.org/korea-saas-market",
        source_title="Korea SaaS market adoption and pricing statistics",
        quote="Korea SaaS vendors report adoption, pricing pressure, and enterprise channel growth.",
        source_grade="B",
        provenance={
            "kind": "government",
            "metadata": {
                "query": "market adoption pricing Korea Korea market statistics willingness to pay"
            },
        },
    )

    audit = build_research_quality_audit(
        [Finding(claim="broad SaaS market claim", support=[broad_saas_market])],
        plan,
    )

    evaluation = audit.source_evaluations[0]
    assert evaluation.accepted is False
    assert "market" not in evaluation.facet_ids
    assert "regional_adoption" not in evaluation.facet_ids


def test_specific_healthcare_source_satisfies_regional_market_adoption_facets():
    plan = _plan("Korea home healthcare SaaS market adoption pricing")
    healthcare_market = EvidenceRef(
        id="gov:home-healthcare-market",
        source_url="https://example.org/korea-home-healthcare",
        source_title="Korea home healthcare SaaS adoption pricing for single-person households",
        quote=(
            "Korea home healthcare providers report adoption barriers, pricing, "
            "and channel needs for single-person households."
        ),
        source_grade="B",
        provenance={
            "kind": "government",
            "metadata": {"query": "home healthcare SaaS Korea adoption pricing household"},
        },
    )

    audit = build_research_quality_audit(
        [Finding(claim="relevant healthcare adoption claim", support=[healthcare_market])],
        plan,
    )

    evaluation = audit.source_evaluations[0]
    assert evaluation.accepted is True
    assert "market" in evaluation.facet_ids
    assert "regional_adoption" in evaluation.facet_ids


def test_b1_erwinia_fixture_rejects_protocol_and_statistics_false_positives():
    plan = ResearchPlan(
        brief_id="brief-b1-erwinia",
        topic_anchor=(
            "B-1 turn-on fluorescent probe for Erwinia amylovora fire blight bacteria diagnosis; "
            "anchor DOI 10.1016/j.isci.2023.106557 PMCID PMC10123346 and DOI 10.1016/j.xpro.2023.102412 PMCID PMC10339246; "
            "assess source-backed protocol specificity selectivity field/on-site applicability, no strawberry topic."
        ),
        queries=[
            "B-1 turn-on fluorescent probe for Erwinia amylovora fire blight bacteria diagnosis",
            "B-1 fluorescent probe Erwinia amylovora protocol specificity selectivity field on-site applicability",
            "B-1 Erwinia amylovora official statistics peer reviewed evidence",
        ],
    )
    anchor_sources = [
        EvidenceRef(
            id="doi:10.1016/j.isci.2023.106557",
            source_url="https://doi.org/10.1016/j.isci.2023.106557",
            source_title="On-site applicable diagnostic fluorescent probe for fire blight bacteria",
            quote="A B-1 turn-on fluorescent probe selectively detects fire blight bacteria including Erwinia amylovora for on-site diagnosis.",
            source_grade="A",
            provenance={"kind": "crossref", "metadata": {"query": plan.queries[1]}},
        ),
        EvidenceRef(
            id="doi:10.1016/j.xpro.2023.102412",
            source_url="https://doi.org/10.1016/j.xpro.2023.102412",
            source_title="Protocol for diagnosing Erwinia amylovora infection using a fluorescent probe",
            quote="This protocol describes diagnosing Erwinia amylovora infection using a fluorescent probe with specificity and selectivity steps.",
            source_grade="A",
            provenance={"kind": "crossref", "metadata": {"query": plan.queries[1]}},
        ),
    ]
    false_positives = [
        EvidenceRef(
            id="arxiv:turn-sip",
            source_url="http://arxiv.org/abs/1002.1178v1",
            source_title="Adaptation of TURN protocol to SIP protocol",
            quote="This paper presents an adaptation of TURN protocol to SIP protocol for NAT traversal in VoIP networks.",
            source_grade="B",
            provenance={"kind": "arxiv", "metadata": {"query": plan.queries[0]}},
        ),
        EvidenceRef(
            id="crossref:bobath-stroke",
            source_url="https://doi.org/10.4103/jfmpc.jfmpc_2080_22",
            source_title="Letter to the Editor re: The Bobath Concept (NDT) as rehabilitation in stroke patients",
            quote="The Bobath concept is discussed for rehabilitation in stroke patients and neurological physiotherapy.",
            source_grade="B",
            provenance={"kind": "crossref", "metadata": {"query": plan.queries[2]}},
        ),
        EvidenceRef(
            id="arxiv:official-statistics-ml",
            source_url="http://arxiv.org/abs/2409.04365v1",
            source_title="Changing Data Sources in the Age of Machine Learning for Official Statistics",
            quote="Machine learning can help official statistics agencies process changing administrative data sources.",
            source_grade="B",
            provenance={"kind": "arxiv", "metadata": {"query": plan.queries[2]}},
        ),
    ]

    audit = build_research_quality_audit(
        [Finding(claim=ref.source_title or ref.id, support=[ref]) for ref in [*anchor_sources, *false_positives]],
        plan,
    )

    facet_ids = {facet.id for facet in audit.facets}
    accepted_ids = {item.source_id for item in audit.source_evaluations if item.accepted}
    rejected = [item for item in audit.source_evaluations if item.source_id not in accepted_ids]
    assert "scientific" in facet_ids
    assert "field_validation" in facet_ids
    assert "general" not in facet_ids
    assert "doi:10.1016/j.isci.2023.106557" in accepted_ids
    assert "doi:10.1016/j.xpro.2023.102412" in accepted_ids
    assert accepted_ids.isdisjoint({ref.id for ref in false_positives})
    assert all(item.facet_ids == () for item in rejected)


def test_generic_non_b1_topic_keeps_specific_domain_anchor_gate():
    plan = _plan("Korea home healthcare SaaS market adoption pricing")
    off_topic_bridge_source = EvidenceRef(
        id="web:generic-enterprise-saas",
        source_url="https://example.org/korea-enterprise-saas",
        source_title="Korea enterprise SaaS adoption and pricing statistics",
        quote="Enterprise SaaS vendors in Korea report adoption, pricing, channel, and public-sector procurement trends.",
        source_grade="B",
        provenance={"kind": "government", "metadata": {"query": "Korea home healthcare SaaS market adoption pricing"}},
    )
    relevant_source = EvidenceRef(
        id="web:home-healthcare-saas",
        source_url="https://example.org/korea-home-healthcare-saas",
        source_title="Korea home healthcare SaaS adoption pricing for single-person households",
        quote="Home healthcare providers in Korea report SaaS adoption barriers, pricing constraints, and distribution channels.",
        source_grade="B",
        provenance={"kind": "government", "metadata": {"query": "Korea home healthcare SaaS market adoption pricing"}},
    )

    audit = build_research_quality_audit(
        [Finding(claim="healthcare SaaS adoption evidence", support=[off_topic_bridge_source, relevant_source])],
        plan,
    )

    evaluations = {item.source_id: item for item in audit.source_evaluations}
    assert evaluations["web:generic-enterprise-saas"].accepted is False
    assert evaluations["web:generic-enterprise-saas"].facet_ids == ()
    assert evaluations["web:home-healthcare-saas"].accepted is True
    assert "market" in evaluations["web:home-healthcare-saas"].facet_ids
