"""Tests for src/targeting/builder.py."""

from __future__ import annotations

import pytest

from src.evidence.artifact import EvidenceRef
from src.interview.brief import ResearchBrief
from src.targeting import TargetingMap
from src.targeting import builder as targeting_builder
from src.targeting.builder import build_targeting_map, _decompose_domains, _build_search_queries


class TestBuildTargetingMap:
    def test_returns_targeting_map(self):
        brief = ResearchBrief(
            raw_idea="strawberry disease molecular probe",
            research_question="molecular diagnosis fluorescent probe for strawberry blight",
            purpose="literature review",
            context="agriculture",
        )
        tmap = build_targeting_map(brief)
        assert isinstance(tmap, TargetingMap)
        assert isinstance(tmap.domains, list)
        assert isinstance(tmap.search_queries, dict)

    def test_domains_are_populated(self):
        brief = ResearchBrief(
            raw_idea="AI algorithm for drug discovery",
            research_question="machine learning algorithm for drug discovery",
            purpose="research",
            context="medicine",
        )
        tmap = build_targeting_map(brief)
        assert "medicine" in tmap.domains or "computer_science" in tmap.domains

    def test_empty_brief_falls_back_to_general(self):
        brief = ResearchBrief(
            raw_idea="",
            research_question="",
            purpose="",
            context="",
        )
        tmap = build_targeting_map(brief)
        assert "general" in tmap.domains

    def test_korean_agriculture_terms_match_agriculture_domain(self):
        brief = ResearchBrief(
            raw_idea="딸기 농가 진단키트",
            research_question="한국 딸기 농가용 저비용 진단키트 시장성",
            purpose="research",
            context="농업 기술",
        )
        tmap = build_targeting_map(brief)
        assert "agriculture" in tmap.domains

    def test_provenance_structure(self):
        brief = ResearchBrief(
            raw_idea="test",
            research_question="test",
            purpose="test",
        )
        tmap = build_targeting_map(brief)
        assert "target_institutions" in tmap.provenance
        assert "target_journals" in tmap.provenance
        assert "seed_papers" in tmap.provenance

    def test_search_queries_per_domain(self):
        brief = ResearchBrief(
            raw_idea="quantum computing",
            research_question="quantum computing algorithms",
            purpose="review",
            context="physics",
        )
        tmap = build_targeting_map(brief)
        for domain in tmap.domains:
            assert domain in tmap.search_queries
            assert len(tmap.search_queries[domain]) >= 2

    def test_live_targeting_falls_back_to_multi_source_seed_papers(self, monkeypatch):
        brief = ResearchBrief(
            raw_idea="agent memory",
            research_question="agent memory architectures",
            purpose="research",
        )
        monkeypatch.setenv("MUCHANIPO_ACADEMIC_TARGETING", "1")
        monkeypatch.setattr(targeting_builder, "query_seed_papers", lambda domains: ([], []))
        monkeypatch.setattr(targeting_builder, "query_institutions", lambda domains: ([], []))
        monkeypatch.setattr(targeting_builder, "query_journals", lambda domains: ([], []))
        ref = EvidenceRef(
            id="crossref:10.1234/memory",
            source_url="https://doi.org/10.1234/memory",
            source_title="Agent Memory Architectures",
            quote="agent memory architectures",
            source_grade="A",
            provenance={"kind": "crossref", "doi": "10.1234/memory", "source_text": "agent memory architectures"},
        )
        monkeypatch.setattr(targeting_builder.academic_sync_search, "search", lambda query, limit=5: [ref])

        tmap = build_targeting_map(brief)

        assert tmap.seed_papers == ["10.1234/memory"]
        assert tmap.provenance["seed_papers"][0]["source"] == "crossref"
        assert tmap.provenance["seed_papers"][0]["paper_id"] == "crossref:10.1234/memory"


class TestDecomposeDomains:
    def test_matches_keywords(self):
        brief = ResearchBrief(
            raw_idea="",
            research_question="",
            purpose="",
            context="chemical synthesis of polymers",
        )
        domains = _decompose_domains(brief)
        assert "chemistry" in domains

    def test_fallback_general(self):
        brief = ResearchBrief(
            raw_idea="xyz",
            research_question="abc",
            purpose="def",
            context="zzz",
        )
        domains = _decompose_domains(brief)
        assert domains == ["general"]


class TestBuildSearchQueries:
    def test_empty_base_fallback(self):
        brief = ResearchBrief(
            raw_idea="",
            research_question="",
            purpose="",
        )
        queries = _build_search_queries(brief, ["general"])
        assert "general" in queries
        assert "review" in queries["general"]

    def test_populated_base(self):
        brief = ResearchBrief(
            raw_idea="autonomous driving",
            research_question="autonomous driving safety",
            purpose="report",
        )
        queries = _build_search_queries(brief, ["computer_science"])
        assert "autonomous driving safety" in queries["computer_science"]
        assert any("review" in q for q in queries["computer_science"])
