"""Tests for safety/lockdown.py validate_targeting_map."""

from __future__ import annotations

import pytest

from src.safety.lockdown import validate_targeting_map
from src.targeting import TargetingMap


class TestValidateTargetingMap:
    def test_all_provenance_present_passes(self):
        tmap = TargetingMap(
            domains=["cs"],
            target_institutions=["MIT"],
            target_journals=["Nature"],
            seed_papers=["Attention Is All You Need"],
            search_queries={"cs": ["transformer"]},
            provenance={
                "target_institutions": [{"name": "MIT", "api": "openalex"}],
                "target_journals": [{"name": "Nature", "api": "crossref"}],
                "seed_papers": [{"name": "Attention Is All You Need", "api": "semantic_scholar"}],
            },
        )
        passed, warnings = validate_targeting_map(tmap)
        assert passed is True
        assert warnings == []
        assert tmap.target_institutions == ["MIT"]
        assert tmap.target_journals == ["Nature"]
        assert tmap.seed_papers == ["Attention Is All You Need"]

    def test_fabricated_institution_removed(self):
        tmap = TargetingMap(
            domains=["cs"],
            target_institutions=["Fake University", "MIT"],
            target_journals=["Real Journal"],
            seed_papers=["Real Paper"],
            search_queries={},
            provenance={
                "target_institutions": [
                    {"name": "MIT", "api": "openalex"},
                ],
                "target_journals": [{"name": "Real Journal", "api": "crossref"}],
                "seed_papers": [{"name": "Real Paper", "api": "semantic_scholar"}],
            },
        )
        passed, warnings = validate_targeting_map(tmap)
        assert passed is True
        assert any("Fake University" in w for w in warnings)
        assert "Fake University" not in tmap.target_institutions
        assert "MIT" in tmap.target_institutions
        assert tmap.target_journals == ["Real Journal"]
        assert tmap.seed_papers == ["Real Paper"]

    def test_fabricated_journal_removed(self):
        tmap = TargetingMap(
            domains=["cs"],
            target_institutions=["MIT"],
            target_journals=["Ghost Journal"],
            seed_papers=["Real Paper"],
            search_queries={},
            provenance={
                "target_institutions": [{"name": "MIT", "api": "openalex"}],
                "target_journals": [],
                "seed_papers": [{"name": "Real Paper", "api": "semantic_scholar"}],
            },
        )
        passed, warnings = validate_targeting_map(tmap)
        assert passed is False  # no journals left
        assert any("Ghost Journal" in w for w in warnings)
        assert tmap.target_journals == []

    def test_fabricated_paper_removed(self):
        tmap = TargetingMap(
            domains=["cs"],
            target_institutions=["MIT"],
            target_journals=["Nature"],
            seed_papers=["Ghost Paper"],
            search_queries={},
            provenance={
                "target_institutions": [{"name": "MIT", "api": "openalex"}],
                "target_journals": [{"name": "Nature", "api": "crossref"}],
                "seed_papers": [],
            },
        )
        passed, warnings = validate_targeting_map(tmap)
        assert passed is False  # no papers left
        assert any("Ghost Paper" in w for w in warnings)
        assert tmap.seed_papers == []

    def test_all_fabricated_fails(self):
        tmap = TargetingMap(
            domains=["cs"],
            target_institutions=["Fake Inst"],
            target_journals=["Fake Journal"],
            seed_papers=["Fake Paper"],
            search_queries={},
            provenance={},
        )
        passed, warnings = validate_targeting_map(tmap)
        assert passed is False
        assert len(warnings) == 3
        assert tmap.target_institutions == []
        assert tmap.target_journals == []
        assert tmap.seed_papers == []

    def test_none_targeting_map_fails(self):
        passed, warnings = validate_targeting_map(None)
        assert passed is False
        assert "TargetingMap is None" in warnings
