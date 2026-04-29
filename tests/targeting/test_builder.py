"""Tests for src/targeting/builder.py."""

from __future__ import annotations

import pytest

from src.interview.brief import ResearchBrief
from src.targeting import TargetingMap
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
