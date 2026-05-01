"""Tests for structured provenance fields (Council Blocker 3 fix)."""
from __future__ import annotations

from src.evidence.provenance import Provenance


def test_provenance_has_structured_fields() -> None:
    p = Provenance(
        kind="openalex",
        doi="10.1234/example",
        journal="Nature",
        institution="Seoul National University",
        retrieved_at="2026-04-30T12:00:00+00:00",
    )
    assert p.doi == "10.1234/example"
    assert p.journal == "Nature"
    assert p.institution == "Seoul National University"
    assert p.retrieved_at == "2026-04-30T12:00:00+00:00"


def test_provenance_as_dict_includes_optional_fields() -> None:
    p = Provenance(
        kind="crossref",
        doi="10.5678/demo",
        journal="Science",
    )
    d = p.as_dict()
    assert d["kind"] == "crossref"
    assert d["doi"] == "10.5678/demo"
    assert d["journal"] == "Science"
    assert "institution" not in d
    assert "retrieved_at" not in d


def test_provenance_as_dict_omits_none_fields() -> None:
    p = Provenance(kind="mock")
    d = p.as_dict()
    assert "doi" not in d
    assert "journal" not in d
    assert "institution" not in d
    assert "retrieved_at" not in d
