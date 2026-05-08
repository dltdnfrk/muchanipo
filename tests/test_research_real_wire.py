"""C32 worker-2 — research/evidence real-wire tests.

All tests are API-key-free: web/exa/vault searchers are stubbed, and
`src.eval.citation_grounder` runs in stdlib mode. Acceptance:
  - WebResearchRunner aggregates injected backends in priority order
  - empty backends → graceful 'D' fallback evidence (still produces Finding)
  - EvidenceStore wires lockdown provenance flags via citation_grounder
  - findings.verified_claim_ratio routes through ground_claims with quoted evidence
  - factory `build_runner` swaps mock ↔ real with same interface
"""
from __future__ import annotations

from pathlib import Path
import importlib
import time

import pytest

from src.evidence.artifact import EvidenceRef, Finding
from src.evidence.findings import annotate_findings, verified_claim_ratio
from src.evidence.store import EvidenceStore
from src.interview.brief import ResearchBrief
from src.research.karpathy_autoresearch import KarpathyAutoresearchRunner
from src.research.planner import ResearchPlanner
from src.research.runner import (
    MockResearchRunner,
    WebResearchRunner,
    build_runner,
)
from src.research import public_web


def _plan(question: str = "How to design agent memory for long-horizon tasks?"):
    brief = ResearchBrief(raw_idea="x", research_question=question, purpose="plan")
    return ResearchPlanner().plan(brief)


def test_source_research_http_timeouts_are_env_tunable_for_bounded_live_runs(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_PUBLIC_WEB_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("MUCHANIPO_ACADEMIC_HTTP_TIMEOUT_SECONDS", "3.5")
    monkeypatch.setenv("MUCHANIPO_ACADEMIC_HTTP_MAX_RETRIES", "1")

    reloaded_public_web = importlib.reload(public_web)
    from src.research.academic import common as academic_common

    reloaded_academic_common = importlib.reload(academic_common)

    assert reloaded_public_web.DEFAULT_TIMEOUT == 2.5
    assert reloaded_academic_common.DEFAULT_TIMEOUT == 3.5
    assert reloaded_academic_common.MAX_RETRIES == 1

    monkeypatch.delenv("MUCHANIPO_PUBLIC_WEB_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("MUCHANIPO_ACADEMIC_HTTP_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("MUCHANIPO_ACADEMIC_HTTP_MAX_RETRIES", raising=False)
    importlib.reload(reloaded_public_web)
    importlib.reload(reloaded_academic_common)


def test_web_runner_bounds_each_backend_with_outer_watchdog(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_RESEARCH_BACKEND_TIMEOUT_SECONDS", "0.05")
    plan = _plan("strawberry molecular diagnostic market pricing Korea")
    plan.queries = ["strawberry molecular diagnostic market pricing Korea"]

    def slow_web(_query):
        time.sleep(1.0)
        return [
            {
                "source": "https://example.test/late",
                "text": "strawberry molecular diagnostic market pricing Korea late result",
                "score": 0.99,
            }
        ]

    runner = WebResearchRunner(
        web_search=slow_web,
        vault_search=lambda _query: [],
        academic_search=None,
        exa_search=None,
        insight_forge_search=None,
        emit_empty_fallback=False,
    )

    started = time.monotonic()
    assert runner.run(plan) == []
    assert time.monotonic() - started < 0.5
    timeout_trace = [entry for entry in runner.last_backend_trace if entry["backend"] == "web"]
    assert timeout_trace
    assert timeout_trace[0]["status"] == "error"
    assert "timed out" in timeout_trace[0]["error"]


def test_source_research_http_timeouts_are_read_at_call_time(monkeypatch):
    import src.research.academic.common as academic_common

    observed_timeouts: list[float] = []

    def fake_get(url, **kwargs):
        observed_timeouts.append(float(kwargs["timeout"]))
        raise TimeoutError("bounded")

    monkeypatch.setattr(public_web.httpx, "get", fake_get)
    monkeypatch.setenv("MUCHANIPO_PUBLIC_WEB_TIMEOUT_SECONDS", "1.25")

    assert public_web.search("strawberry market pricing", limit=1) == []
    assert observed_timeouts == [1.25]

    import asyncio

    monkeypatch.setenv("MUCHANIPO_ACADEMIC_HTTP_TIMEOUT_SECONDS", "2.25")
    monkeypatch.setenv("MUCHANIPO_ACADEMIC_HTTP_MAX_RETRIES", "1")

    async def build_client():
        return academic_common.AcademicHttpClient(base_url="https://example.test")

    client = asyncio.run(build_client())

    assert client._timeout == 2.25
    assert academic_common.current_max_retries() == 1


def test_public_web_parser_classifies_government_statistics_source_channel():
    markup = '''
    <div class="result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fkosis.kr%2FstatisticsList%2FstatisticsListIndex.do">KOSIS Korea strawberry farm statistics</a>
      <a class="result__snippet">Korea government statistics survey on strawberry farms, price, adoption and distribution channel.</a>
    </div>
    '''

    hits = public_web._parse_duckduckgo_html(markup, limit=3)

    assert hits == [
        {
            "kind": "government",
            "url": "https://kosis.kr/statisticsList/statisticsListIndex.do",
            "source": "https://kosis.kr/statisticsList/statisticsListIndex.do",
            "title": "KOSIS Korea strawberry farm statistics",
            "text": "KOSIS Korea strawberry farm statistics Korea government statistics survey on strawberry farms, price, adoption and distribution channel.",
            "score": 0.82,
        }
    ]


def test_public_web_data_go_kr_fallback_recovers_korean_market_sources():
    markup = '''
      <input value="서울농수산식품공사_딸기 경매결과">
      <p>가락 도매시장에서 거래된 딸기 품목의 일자별 경매 결과를 수집 정제 가공한 가격 통계 데이터입니다.</p>
      <input value="농수축산 경락 및 조사가격정보">
      <p>딸기 농수축산 경락 가격 조사 통계와 유통시장 정보를 제공합니다.</p>
      <input value="농식품 소비자행태조사정보">
      <p>딸기 소비 구매 행태 조사 및 소비 트렌드 통계 데이터입니다.</p>
    '''

    hits = public_web._parse_data_go_kr_html(
        markup,
        query="딸기 가격 통계 소비 구매",
        source_url="https://www.data.go.kr/tcs/dss/selectDataSetList.do?keyword=x",
        limit=5,
    )

    assert len(hits) == 3
    assert all(hit["kind"] in {"government", "statistics"} for hit in hits)
    assert any("딸기 경매" in hit["title"] for hit in hits)
    assert all("딸기" in hit["text"] for hit in hits)
    assert all(float(hit["score"]) >= 0.8 for hit in hits)


def test_web_runner_keeps_market_source_channel_when_diagnostic_topic_is_present():
    """Market public-data hits need not repeat the diagnostic method words.

    The facet audit will decide whether they satisfy market/regional_adoption;
    the runner should not pre-filter a consumer-statistics source just because
    it is not itself a molecular assay.
    """

    query = "low cost molecular diagnostic kit market adoption pricing distribution"
    runner = WebResearchRunner(
        web_search=lambda q: [
            {
                "kind": "government",
                "url": "https://www.data.go.kr/data/15156401/fileData.do",
                "title": "Korea Diagnostic Kit Market Consumer Trends",
                "text": "Diagnostic kit consumer trend purchase price survey government public data statistics",
                "score": 0.91,
            }
        ],
        academic_search=lambda q: [],
        vault_search=lambda q: [],
        insight_forge_search=lambda q: [],
        emit_empty_fallback=False,
    )

    findings = runner.run(ResearchPlanner().plan(ResearchBrief(raw_idea=query, research_question=query, purpose="plan"), max_queries=1))

    assert findings
    assert findings[0].support[0].source_title == "Korea Diagnostic Kit Market Consumer Trends"


def test_build_runner_wires_default_public_web_source_channel_for_real_runs(monkeypatch):
    calls: list[str] = []

    def fake_public_search(query: str, *, limit: int = 5):
        calls.append(query)
        return [
            {
                "kind": "government",
                "url": "https://kosis.kr/diagnostic-market",
                "title": "Korea diagnostic kit adoption pricing statistics",
                "text": "Korea government statistics for diagnostic kits, market adoption, pricing, and distribution channel.",
                "score": 0.9,
            }
        ]

    monkeypatch.setattr(public_web, "search", fake_public_search)
    runner = build_runner(use_real=True, academic_search=lambda q: [], vault_search=lambda q: [])
    plan = _plan("Korea strawberry farmer market adoption pricing statistics")

    findings = runner.run(plan)

    assert calls == plan.queries
    assert findings
    ref = findings[0].support[0]
    assert ref.provenance["kind"] == "government"
    assert ref.source_url == "https://kosis.kr/diagnostic-market"
    assert ref.source_grade == "B"


def test_web_runner_aggregates_injected_backends_in_priority_order():
    plan = _plan()
    web_calls: list[str] = []
    vault_calls: list[str] = []

    def fake_web(query: str):
        web_calls.append(query)
        return [{"url": "https://example.com/a", "title": "Web A", "text": "Agent memory matters", "score": 0.55}]

    def fake_vault(query: str):
        vault_calls.append(query)
        return [{"source": "vault/agent.md", "text": "memory palace pattern", "score": 0.9}]

    runner = WebResearchRunner(web_search=fake_web, vault_search=fake_vault, exa_search=None)
    findings = runner.run(plan)

    assert findings, "runner must produce at least one finding"
    finding = findings[0]
    assert web_calls == plan.queries
    assert vault_calls == plan.queries
    # Highest-score (vault, 0.9) should be ranked first by the score-sort.
    assert finding.support[0].provenance["source"] == "vault/agent.md"
    # vault item gets B grade, web gets C below 0.8 — both present
    grades = {ev.source_grade for ev in finding.support}
    assert "B" in grades and "C" in grades
    assert {item["backend"] for item in runner.last_backend_trace} == {"vault", "web"}
    assert all(item["status"] == "ok" for item in runner.last_backend_trace)
    assert all(item["count"] == 1 for item in runner.last_backend_trace)


def test_karpathy_autoresearch_runner_keeps_metric_improvement(tmp_path):
    plan = _plan("strawberry diagnostics")

    class FakeRunner:
        def __init__(self):
            self.calls: list[list[str]] = []
            self.last_backend_trace: list[dict] = []

        def run(self, candidate_plan):
            self.calls.append(list(candidate_plan.queries))
            query = candidate_plan.queries[0]
            grade = "A" if "official statistics" in query else "D"
            ref = EvidenceRef(
                id=f"ref-{len(self.calls)}",
                source_url="https://doi.org/10.1234/example" if grade == "A" else None,
                source_title="Official strawberry diagnostics source" if grade == "A" else "No live evidence",
                quote="strawberry diagnostics official statistics source evidence",
                source_grade=grade,
                provenance={"kind": "openalex" if grade == "A" else "empty"},
            )
            self.last_backend_trace = [
                {
                    "backend": "academic",
                    "query": query,
                    "status": "ok",
                    "count": 1,
                }
            ]
            return [Finding(claim="source-backed claim", support=[ref], confidence=0.7)]

    runner = KarpathyAutoresearchRunner(
        FakeRunner(),
        iteration_budget=2,
        work_root=tmp_path,
        source_dir=Path("third_party/karpathy-autoresearch"),
        run_tag="unit-keep",
    )

    findings = runner.run(plan)
    loop = runner.last_loop_result

    assert loop is not None
    assert loop.best_iteration == 2
    assert [item.status for item in loop.experiments] == ["keep", "keep"]
    assert findings[0].support[0].source_grade == "A"
    assert findings[0].support[0].provenance["metadata"]["karpathy_autoresearch"]["iteration"] == 2
    assert Path(loop.program_path).exists()
    assert Path(loop.results_path).read_text(encoding="utf-8").splitlines()[0] == (
        "commit\tval_bpb\tmemory_gb\tstatus\tdescription"
    )
    assert runner.last_backend_trace[0]["autoresearch_iteration"] == 1
    assert runner.last_backend_trace[-1]["autoresearch_iteration"] == 2


def test_karpathy_autoresearch_runner_discards_non_improvement(tmp_path):
    plan = _plan("agent memory research")

    class FlatRunner:
        def __init__(self):
            self.last_backend_trace: list[dict] = []

        def run(self, candidate_plan):
            query = candidate_plan.queries[0]
            ref = EvidenceRef(
                id="ref-flat",
                source_url="https://example.com/source",
                source_title="Flat source",
                quote="agent memory source",
                source_grade="B",
                provenance={"kind": "vault"},
            )
            self.last_backend_trace = [
                {
                    "backend": "vault",
                    "query": query,
                    "status": "ok",
                    "count": 1,
                }
            ]
            return [Finding(claim="same claim", support=[ref], confidence=0.7)]

    runner = KarpathyAutoresearchRunner(
        FlatRunner(),
        iteration_budget=2,
        work_root=tmp_path,
        source_dir=Path("third_party/karpathy-autoresearch"),
        run_tag="unit-discard",
    )

    findings = runner.run(plan)
    loop = runner.last_loop_result

    assert loop is not None
    assert loop.best_iteration == 1
    assert [item.status for item in loop.experiments] == ["keep", "discard"]
    assert findings[0].support[0].provenance["metadata"]["karpathy_autoresearch"]["iteration"] == 1


def test_web_runner_accepts_academic_evidence_refs():
    plan = _plan("strawberry diagnostics")
    academic_ref = EvidenceRef(
        id="openalex:W1",
        source_url="https://doi.org/10.1234/example",
        source_title="Academic paper",
        quote="strawberry diagnostics evidence",
        source_grade="A",
        provenance={"kind": "openalex", "doi": "10.1234/example", "source_text": "strawberry diagnostics evidence"},
    )
    runner = WebResearchRunner(
        academic_search=lambda q: [academic_ref],
        web_search=None,
        vault_search=lambda q: [],
        exa_search=None,
    )

    findings = runner.run(plan)

    assert findings[0].support[0] is academic_ref
    assert findings[0].support[0].source_grade == "A"


def test_web_runner_prioritizes_insight_forge_backend_when_enabled():
    plan = _plan("딸기 재배 자동 연구")
    calls: list[str] = []

    def fake_insight_forge(query: str):
        calls.append(query)
        return [
            {
                "source": "vault/insight.md",
                "text": "딸기 재배 자동 연구 InsightForge RRF result with GBrain dedup",
                "score": 0.99,
                "matched_questions": ["who", "why"],
            }
        ]

    runner = WebResearchRunner(
        insight_forge_search=fake_insight_forge,
        vault_search=lambda q: [],
        academic_search=lambda q: [],
        web_search=None,
        exa_search=None,
    )

    findings = runner.run(plan)

    assert calls == plan.queries
    first = findings[0].support[0]
    assert first.provenance["kind"] == "insight_forge"
    assert first.provenance["source"] == "vault/insight.md"
    assert first.source_grade == "B"


def test_web_runner_filters_generated_muchanipo_mock_artifacts():
    plan = _plan("딸기 진단 시장성")

    def fake_insight_forge(query: str):
        return [
            {
                "source": "projects/muchanipo/memory.md#handoff",
                "text": "Muchanipo report with mock-evidence-1 and trusted evidence: 0",
                "score": 0.99,
            },
            {
                "source": "Neobio/meetings/field-validation.md",
                "text": "딸기 농가 현장 실증에서 PCR 비교 데이터 확보가 필요했다.",
                "score": 0.8,
            },
        ]

    runner = WebResearchRunner(
        insight_forge_search=fake_insight_forge,
        vault_search=lambda q: [],
        academic_search=lambda q: [],
        web_search=None,
        exa_search=None,
    )

    findings = runner.run(plan)

    sources = [ev.provenance["source"] for ev in findings[0].support]
    assert "projects/muchanipo/memory.md#handoff" not in sources
    assert "Neobio/meetings/field-validation.md" in sources


def test_web_runner_filters_low_relevance_academic_pricing_hits():
    plan = _plan("딸기 농가용 저비용 분자진단 키트 시장성 adoption constraints pricing risk")
    relevant = EvidenceRef(
        id="crossref:strawberry",
        source_url="https://doi.org/10.1234/strawberry",
        source_title="Strawberry farmer diagnostics willingness to pay",
        quote="strawberry farmers diagnostic kit willingness to pay evidence",
        source_grade="A",
        provenance={"kind": "crossref", "source_text": "strawberry farmers diagnostic kit willingness to pay evidence"},
    )
    irrelevant = EvidenceRef(
        id="crossref:asset-pricing",
        source_url="https://doi.org/10.1234/asset",
        source_title="Asset Pricing With Heterogeneous Risk Aversion",
        quote="asset pricing and portfolio risk constraints",
        source_grade="A",
        provenance={"kind": "crossref", "source_text": "asset pricing and portfolio risk constraints"},
    )
    runner = WebResearchRunner(
        insight_forge_search=lambda q: [],
        vault_search=lambda q: [],
        academic_search=lambda q: [irrelevant, relevant],
        web_search=None,
        exa_search=None,
    )

    finding = runner.run(plan)[0]

    assert [ev.id for ev in finding.support] == ["crossref:strawberry"]


def test_web_runner_requires_diagnostic_concept_for_diagnostic_queries():
    plan = _plan("딸기 농가용 저비용 분자진단 키트 시장성")
    generic_strawberry_value = EvidenceRef(
        id="crossref:strawberry-value",
        source_url="https://doi.org/10.1234/value",
        source_title="출하일 별 딸기 상품가치 비교",
        quote="딸기 상품가치와 출하일 차이를 비교한 연구",
        source_grade="A",
        provenance={"kind": "crossref", "source_text": "딸기 상품가치와 출하일 차이를 비교한 연구"},
    )
    diagnostics = EvidenceRef(
        id="crossref:diagnostics",
        source_url="https://doi.org/10.1234/diagnostics",
        source_title="Strawberry plant pathogen molecular diagnostic kit field detection",
        quote="strawberry plant pathogen molecular diagnostic kit field detection evidence",
        source_grade="A",
        provenance={
            "kind": "crossref",
            "source_text": "strawberry plant pathogen molecular diagnostic kit field detection evidence",
        },
    )
    runner = WebResearchRunner(
        insight_forge_search=lambda q: [],
        vault_search=lambda q: [],
        academic_search=lambda q: [generic_strawberry_value, diagnostics],
        web_search=None,
        exa_search=None,
    )

    finding = runner.run(plan)[0]

    assert [ev.id for ev in finding.support] == ["crossref:diagnostics"]


def test_web_runner_finding_claim_comes_from_source_text():
    plan = _plan("딸기 진단 시장성")
    runner = WebResearchRunner(
        insight_forge_search=lambda q: [
            {
                "source": "Neobio/meetings/field-validation.md",
                "text": "딸기 농가 현장 실증에서 PCR 비교 데이터 확보가 필요했다.",
                "score": 0.8,
            }
        ],
        vault_search=lambda q: [],
        academic_search=lambda q: [],
        web_search=None,
        exa_search=None,
    )

    finding = runner.run(plan)[0]

    assert finding.claim == "딸기 농가 현장 실증에서 PCR 비교 데이터 확보가 필요했다."
    assert verified_claim_ratio(finding) == 1.0


def test_web_runner_graceful_fallback_when_all_backends_empty():
    plan = _plan("Quoque obscura quaestio")
    runner = WebResearchRunner(
        web_search=lambda q: [],
        vault_search=lambda q: [],
        exa_search=lambda q: [],
    )
    findings = runner.run(plan)
    assert len(findings) == len(plan.queries)
    ev = findings[0].support[0]
    assert ev.source_grade == "D"
    assert ev.provenance["kind"] == "empty"


def test_web_runner_live_mode_omits_empty_fallback_evidence():
    plan = _plan("Quoque obscura quaestio")
    runner = WebResearchRunner(
        web_search=lambda q: [],
        vault_search=lambda q: [],
        exa_search=lambda q: [],
        emit_empty_fallback=False,
    )

    assert runner.run(plan) == []
    assert runner.last_backend_trace
    assert all(item["count"] == 0 for item in runner.last_backend_trace)


def test_web_runner_swallows_backend_exceptions():
    plan = _plan()

    def boom(query: str):
        raise RuntimeError("network down")

    def working_vault(query: str):
        return [{"source": "vault/x.md", "text": "agent memory real hit", "score": 0.7}]

    runner = WebResearchRunner(web_search=boom, exa_search=boom, vault_search=working_vault)
    findings = runner.run(plan)
    assert findings[0].support[0].provenance["source"] == "vault/x.md"
    errors = [item for item in runner.last_backend_trace if item["status"] == "error"]
    assert {item["backend"] for item in errors} == {"web", "exa"}
    assert all("network down" in item["error"] for item in errors)


def test_evidence_store_wires_provenance_check_via_citation_grounder():
    """Default provenance check (lockdown wrapper) should pass clean refs and
    record a flag dictionary so downstream code can filter trusted evidence."""
    store = EvidenceStore()
    ref = EvidenceRef(
        id="vault-1",
        source_url="https://example.com/x",
        source_title="X",
        quote="memory palace pattern",
        source_grade="B",
        provenance={"kind": "vault", "source_text": "memory palace pattern explained"},
    )
    store.add(ref)
    assert store.get("vault-1") is ref
    assert store.provenance_flag("vault-1") is True
    assert store.trusted() == [ref]
    assert store.provenance_failures() == 0


def test_evidence_store_marks_provenance_failure_when_lockdown_rejects(monkeypatch):
    """If `_lockdown_validate_provenance` flags an item, the store must
    surface that flag without raising — supported claims downstream filter on it."""
    import src.evidence.store as store_mod

    def fake_validate(payload):
        return {entry["id"]: False for entry in payload}

    monkeypatch.setattr(store_mod, "_validate_provenance", lambda refs, **kwargs: fake_validate(
        [{"id": ref.id} for ref in refs]
    ))

    store = store_mod.EvidenceStore()
    ref = EvidenceRef(
        id="bad-1",
        source_url=None,
        source_title=None,
        quote="anything",
        source_grade="C",
        provenance={"kind": "web"},
    )
    store.add(ref)
    assert store.provenance_flag("bad-1") is False
    assert store.trusted() == []
    assert store.provenance_failures() == 1
    assert ref.provenance.get("provenance_failed") is True


def test_evidence_store_structural_validation_blocks_permissive_lockdown(monkeypatch):
    """Structural checks must still reject fabricated quotes if lockdown passes."""
    import src.eval.citation_grounder as grounder_mod

    monkeypatch.setattr(
        grounder_mod,
        "_lockdown_validate_provenance",
        lambda payload: {entry["id"]: True for entry in payload},
    )

    store = EvidenceStore()
    ref = EvidenceRef(
        id="fabricated-1",
        source_url="https://example.com/article",
        source_title="Article",
        quote="fabricated quote",
        source_grade="B",
        provenance={"kind": "web", "source_text": "grounded source text"},
    )

    store.add(ref)

    assert store.provenance_flag("fabricated-1") is False
    assert store.trusted() == []
    assert ref.provenance.get("provenance_failed") is True


def test_evidence_store_structural_validation_accepts_normalized_doi_url(monkeypatch):
    import src.eval.citation_grounder as grounder_mod

    monkeypatch.setattr(
        grounder_mod,
        "_lockdown_validate_provenance",
        lambda payload: {entry["id"]: True for entry in payload},
    )

    store = EvidenceStore()
    ref = EvidenceRef(
        id="openalex:doi-ok",
        source_url="https://doi.org/10.1234/example",
        source_title="Academic paper",
        quote="source-backed claim",
        source_grade="A",
        provenance={
            "kind": "openalex",
            "doi": "https://doi.org/10.1234/example",
            "source_text": "source-backed claim with more context",
        },
    )

    store.add(ref)

    assert store.provenance_flag("openalex:doi-ok") is True
    assert store.trusted() == [ref]


def test_evidence_store_structural_validation_rejects_invalid_academic_doi(monkeypatch):
    import src.eval.citation_grounder as grounder_mod

    monkeypatch.setattr(
        grounder_mod,
        "_lockdown_validate_provenance",
        lambda payload: {entry["id"]: True for entry in payload},
    )

    store = EvidenceStore()
    ref = EvidenceRef(
        id="openalex:doi-bad",
        source_url="https://doi.org/not-a-doi",
        source_title="Academic paper",
        quote="source-backed claim",
        source_grade="A",
        provenance={
            "kind": "openalex",
            "doi": "not-a-doi",
            "source_text": "source-backed claim with more context",
        },
    )

    store.add(ref)

    assert store.provenance_flag("openalex:doi-bad") is False
    assert store.trusted() == []


def test_verified_claim_ratio_routes_through_citation_grounder():
    """Substring source text in evidence → 'supported' → ratio == 1.0."""
    ev = EvidenceRef(
        id="e1",
        source_url=None,
        source_title="src",
        quote="Initial research direction for: agent memory architectures",
        source_grade="B",
        provenance={
            "kind": "vault",
            "source_text": "Initial research direction for: agent memory architectures",
        },
    )
    finding = Finding(
        claim="Initial research direction for: agent memory architectures",
        support=[ev],
        confidence=0.7,
    )
    ratio = verified_claim_ratio(finding)
    assert ratio == 1.0


def test_verified_claim_ratio_unsupported_when_no_overlap():
    ev = EvidenceRef(
        id="e1",
        source_url=None,
        source_title="src",
        quote="totally unrelated text about cooking pasta",
        source_grade="C",
        provenance={"kind": "web"},
    )
    finding = Finding(
        claim="quantum entanglement of photonic qubits at room temperature",
        support=[ev],
        confidence=0.4,
    )
    ratio = verified_claim_ratio(finding)
    assert ratio < 1.0


def test_annotate_findings_keeps_input_order_and_ids():
    plan = _plan()
    findings = MockResearchRunner().run(plan)
    annotated = annotate_findings(findings)
    assert len(annotated) == len(findings)
    for src, dst in zip(findings, annotated):
        assert dst["claim"] == src.claim
        assert dst["evidence_ids"] == [ev.id for ev in src.support]
        assert 0.0 <= dst["verified_claim_ratio"] <= 1.0


def test_build_runner_factory_swaps_mock_and_real_with_same_interface():
    plan = _plan()
    mock = build_runner(use_real=False)
    real = build_runner(
        use_real=True,
        vault_search=lambda q: [{"source": "vault/n.md", "text": q, "score": 0.6}],
        web_search=None,
        exa_search=None,
        academic_search=lambda q: [],
    )
    assert isinstance(mock, MockResearchRunner)
    assert isinstance(real, WebResearchRunner)
    assert callable(real.academic_search)
    # Both expose .run(plan) → list[Finding]
    for runner in (mock, real):
        out = runner.run(plan)
        assert out and all(isinstance(f, Finding) for f in out)


def test_build_runner_disables_empty_fallback_when_live_is_required(monkeypatch):
    import src.research.runner as runner_mod

    monkeypatch.setenv("MUCHANIPO_REQUIRE_LIVE", "1")

    real = runner_mod.build_runner(
        use_real=True,
        web_search=None,
        vault_search=lambda q: [],
        exa_search=None,
        academic_search=lambda q: [],
        insight_forge_search=lambda q: [],
    )

    assert real.emit_empty_fallback is False


def test_build_runner_disables_empty_fallback_for_source_research(monkeypatch):
    import src.research.runner as runner_mod

    monkeypatch.setenv("MUCHANIPO_SOURCE_RESEARCH", "1")

    real = runner_mod.build_runner(
        use_real=True,
        web_search=None,
        vault_search=lambda q: [],
        exa_search=None,
        academic_search=lambda q: [],
        insight_forge_search=lambda q: [],
    )

    assert real.emit_empty_fallback is False


def test_build_runner_factory_wires_default_academic_search(monkeypatch):
    import src.research.runner as runner_mod

    plan = _plan("sync academic wire")
    calls: list[str] = []
    academic_ref = EvidenceRef(
        id="openalex:W-sync",
        source_url="https://doi.org/10.4567/sync-wire",
        source_title="Sync academic paper",
        quote="sync academic wire",
        source_grade="A",
        provenance={"kind": "openalex", "doi": "10.4567/sync-wire", "source_text": "sync academic wire"},
    )

    def fake_academic(query: str):
        calls.append(query)
        return [academic_ref]

    monkeypatch.setattr(runner_mod.academic_sync_search, "search", fake_academic)

    real = runner_mod.build_runner(
        use_real=True,
        web_search=None,
        vault_search=lambda q: [],
        exa_search=None,
    )
    findings = real.run(plan)

    assert real.academic_search is fake_academic
    assert calls == plan.queries
    assert findings[0].support[0] is academic_ref


def test_research_brief_to_report_e2e_with_real_wire_stub():
    """End-to-end: ResearchBrief → ResearchPlan → WebResearchRunner (stubbed)
    → Finding[] → EvidenceStore → annotate_findings. No API keys, no network."""
    brief = ResearchBrief(
        raw_idea="long-horizon agent memory",
        research_question="How does memory palace pattern improve long-horizon agent recall?",
        purpose="research_report",
        context="autonomous research loop",
    )
    plan = ResearchPlanner().plan(brief)
    runner = WebResearchRunner(
        web_search=lambda q: [
            {"url": "https://ex.com/p", "title": "Memory palace overview",
             "text": "How does memory palace pattern improve long-horizon agent recall?",
             "score": 0.85}
        ],
        vault_search=lambda q: [
            {"source": "vault/mp.md", "text": "memory palace recall study", "score": 0.7}
        ],
        exa_search=None,
    )
    findings = runner.run(plan)
    store = EvidenceStore()
    for finding in findings:
        for ev in finding.support:
            store.add(ev)
    assert store.list(), "store must capture evidence end-to-end"
    annotated = annotate_findings(findings)
    # Finding's claim is 'Initial research direction for: <question>' which is a substring
    # of the web hit text → at least one supported claim, ratio > 0.
    assert any(item["verified_claim_ratio"] > 0 for item in annotated)
