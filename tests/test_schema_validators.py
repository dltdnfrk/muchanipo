import copy

from src.council.schema import (
    validate_agent_manifest,
    validate_council_report_v3,
    validate_vault_frontmatter,
)


def valid_manifest():
    return {
        "intent": "시장 근거를 검증하는 회의 페르소나",
        "allowed_tools": ["search", "read_file"],
        "required_outputs": ["claims", "dissent"],
        "token_budget": 2400,
        "reliability_score": 0.82,
    }


def valid_report():
    return {
        "schema_version": "v0.4.0",
        "personas": [
            {
                "name": "grounder",
                "agent_manifest": valid_manifest(),
            }
        ],
        "rounds": [
            {
                "stop_reason": "converged",
                "context_checksum": "sha256:abc123",
                "convergence": {
                    "consensus_score": 0.78,
                    "ambiguity": 0.12,
                    "coverage": 0.91,
                    "contradiction_count": 1,
                    "confidence_mad": 0.08,
                    "belief_delta": 0.03,
                    "dominant_position_ratio": 0.7,
                    "can_stop": True,
                },
                "ratchet": {
                    "decision": "keep",
                    "effect_size_mad": 0.04,
                    "ratchet_score": 0.62,
                    "deltas": [{"axis": "reliability", "delta": 0.1}],
                },
            }
        ],
        "citation_grounding": {
            "verified_claim_ratio": 1.0,
            "total_claim_count": 1,
            "unsupported_critical_claim_count": 0,
            "per_claim_verdict": [
                {
                    "claim_id": "C1",
                    "text": "MuchaNipo v0.4는 근거 검증을 강제한다.",
                    "is_critical": True,
                    "supporting_evidence_ids": ["E1"],
                    "verification_status": "supported",
                }
            ],
        },
        "evidence": [
            {
                "id": "E1",
                "type": "text",
                "source": "internal-test",
                "quote": "MuchaNipo v0.4는 근거 검증을 강제한다.",
                "quote_span": [0, 28],
                "hash": "sha256:def456",
                "fetched_at": "2026-04-25T00:00:00Z",
            }
        ],
        "final": {
            "scores": {
                "axes": {"citation_fidelity": 8},
                "total": 82,
                "rubric_max": 110,
                "verdict": "PASS",
                "verdict_reason": "충분한 근거가 있다.",
            },
            "vault_metadata": {"target": "Muchanipo/Test"},
            "cost_trace": {"tokens": 1200},
        },
    }


def valid_frontmatter():
    return {
        "schema_version": "v04",
        "uncertainty": 0.2,
        "verified_claim_ratio": 0.9,
        "belief_valid_from": "2026-04-25T00:00:00Z",
        "belief_updated_at": "2026-04-25T01:00:00Z",
        "supersedes": ["old-note"],
        "sensitivity": "internal",
    }


def test_validate_agent_manifest_passes():
    ok, errors = validate_agent_manifest(valid_manifest())
    assert ok is True
    assert errors == []


def test_validate_agent_manifest_rejects_missing_required_field():
    manifest = valid_manifest()
    del manifest["token_budget"]

    ok, errors = validate_agent_manifest(manifest)

    assert ok is False
    assert any("token_budget missing" in error for error in errors)


def test_validate_vault_frontmatter_passes():
    ok, errors = validate_vault_frontmatter(valid_frontmatter())
    assert ok is True
    assert errors == []


def test_validate_vault_frontmatter_rejects_bad_enum():
    frontmatter = valid_frontmatter()
    frontmatter["sensitivity"] = "internet"

    ok, errors = validate_vault_frontmatter(frontmatter)

    assert ok is False
    assert any("sensitivity" in error and "one of" in error for error in errors)


def test_validate_council_report_v3_passes():
    ok, errors = validate_council_report_v3(valid_report())
    assert ok is True
    assert errors == []


def test_validate_council_report_v3_requires_schema_version():
    report = valid_report()
    del report["schema_version"]

    ok, errors = validate_council_report_v3(report)

    assert ok is False
    assert any("schema_version missing" in error for error in errors)
    assert any("SchemaVersionMissing" in error for error in errors)


def test_validate_council_report_v3_rejects_bad_claim_status_enum():
    report = valid_report()
    report["citation_grounding"]["per_claim_verdict"][0]["verification_status"] = "laundered"

    ok, errors = validate_council_report_v3(report)

    assert ok is False
    assert any("verification_status" in error and "one of" in error for error in errors)


def test_validate_council_report_v3_rejects_nested_missing_required_field():
    report = copy.deepcopy(valid_report())
    del report["rounds"][0]["convergence"]["coverage"]

    ok, errors = validate_council_report_v3(report)

    assert ok is False
    assert any("coverage missing" in error for error in errors)


def test_validate_council_report_v3_rejects_bad_evidence_type_enum():
    report = valid_report()
    report["evidence"][0]["type"] = "rumor"

    ok, errors = validate_council_report_v3(report)

    assert ok is False
    assert any("evidence[0].type" in error and "one of" in error for error in errors)
