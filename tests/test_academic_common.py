"""Tests for src.research.academic.common structured evidence_ref."""
from __future__ import annotations

from src.evidence.store import EvidenceStore
from src.research.academic.common import evidence_ref


def test_evidence_ref_with_structured_provenance() -> None:
    ref = evidence_ref(
        source="openalex",
        paper_id="W123456789",
        raw={"title": "Demo Paper"},
        source_url="https://openalex.org/works/W123456789",
        source_title="Demo Paper",
        quote="significant result",
        source_grade="A",
        doi="10.1234/demo",
        journal="Journal of Examples",
        institution="KAIST",
        retrieved_at="2026-04-30T12:00:00+00:00",
    )
    assert ref.source_grade == "A"
    prov = ref.provenance
    assert prov["doi"] == "10.1234/demo"
    assert prov["journal"] == "Journal of Examples"
    assert prov["institution"] == "KAIST"
    assert prov["retrieved_at"] == "2026-04-30T12:00:00+00:00"
    assert prov["paper_id"] == "W123456789"
    assert prov["source_text"]["title"] == "Demo Paper"
    assert "_muchanipo_quote" not in prov["source_text"]


def test_structured_academic_provenance_can_be_trusted_without_self_grounding() -> None:
    ref = evidence_ref(
        source="openalex",
        paper_id="W123456789",
        raw={"display_name": "Demo Paper", "abstract": "significant result"},
        source_url="https://doi.org/10.1234/demo",
        source_title="Demo Paper",
        quote="significant result",
        source_grade="A",
        doi="10.1234/demo",
    )
    store = EvidenceStore(require_live=True)

    store.add(ref)

    assert store.provenance_flag(ref.id) is True
    assert store.summary()["trusted"] == 1


def test_evidence_ref_without_optional_provenance_fields() -> None:
    ref = evidence_ref(
        source="mock",
        paper_id="M1",
        raw={},
        source_url=None,
        source_title=None,
        quote=None,
    )
    prov = ref.provenance
    assert "doi" not in prov
    assert "journal" not in prov
    assert "institution" not in prov
    assert "retrieved_at" not in prov


def test_evidence_ref_does_not_self_ground_quote() -> None:
    ref = evidence_ref(
        source="openalex",
        paper_id="W-fabricated",
        raw={"title": "Unrelated Paper"},
        source_url="https://doi.org/10.1234/fabricated",
        source_title="Unrelated Paper",
        quote="fabricated quote not in raw",
        source_grade="A",
        doi="10.1234/fabricated",
    )

    store = EvidenceStore()
    store.add(ref)

    assert store.provenance_flag(ref.id) is False
    assert ref.provenance.get("provenance_failed") is True
