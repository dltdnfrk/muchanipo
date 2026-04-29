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

import pytest

from src.evidence.artifact import EvidenceRef, Finding
from src.evidence.findings import annotate_findings, verified_claim_ratio
from src.evidence.store import EvidenceStore
from src.interview.brief import ResearchBrief
from src.research.planner import ResearchPlanner
from src.research.runner import (
    MockResearchRunner,
    WebResearchRunner,
    build_runner,
)


def _plan(question: str = "How to design agent memory for long-horizon tasks?"):
    brief = ResearchBrief(raw_idea="x", research_question=question, purpose="plan")
    return ResearchPlanner().plan(brief)


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


def test_web_runner_accepts_academic_evidence_refs():
    plan = _plan("strawberry diagnostics")
    academic_ref = EvidenceRef(
        id="openalex:W1",
        source_url="https://doi.org/10.123/example",
        source_title="Academic paper",
        quote="strawberry diagnostics evidence",
        source_grade="A",
        provenance={"kind": "openalex", "source_text": "strawberry diagnostics evidence"},
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


def test_web_runner_swallows_backend_exceptions():
    plan = _plan()

    def boom(query: str):
        raise RuntimeError("network down")

    def working_vault(query: str):
        return [{"source": "vault/x.md", "text": "real hit", "score": 0.7}]

    runner = WebResearchRunner(web_search=boom, exa_search=boom, vault_search=working_vault)
    findings = runner.run(plan)
    assert findings[0].support[0].provenance["source"] == "vault/x.md"


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


def test_build_runner_factory_wires_default_academic_search(monkeypatch):
    import src.research.runner as runner_mod

    plan = _plan("sync academic wire")
    calls: list[str] = []
    academic_ref = EvidenceRef(
        id="openalex:W-sync",
        source_url="https://doi.org/10.456/sync-wire",
        source_title="Sync academic paper",
        quote="sync academic wire",
        source_grade="A",
        provenance={"kind": "openalex", "source_text": "sync academic wire"},
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
