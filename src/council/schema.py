#!/usr/bin/env python3
"""MuchaNipo v0.4 lightweight schema validators.

jsonschema 의존성을 추가하지 않기 위해 v0.4에서 필요한 필수 필드, enum,
범위만 stdlib 코드로 검증한다. 반환값은 항상 (ok, errors) 튜플이다.
"""

from typing import Any, Dict, Iterable, List, Tuple


ValidationResult = Tuple[bool, List[str]]

COUNCIL_SCHEMA_VERSION = "v0.4.0"
VAULT_SCHEMA_VERSION = "v04"
VERDICTS = {"PASS", "UNCERTAIN", "FAIL"}
CLAIM_STATUSES = {"supported", "partial", "unsupported", "unknown"}
EVIDENCE_TYPES = {"text", "image", "chart", "table", "vault_page", "kg_triple"}
SENSITIVITY_LEVELS = {"public", "internal", "confidential", "restricted"}


def validate_agent_manifest(d: Any) -> ValidationResult:
    """Agent manifest 자체를 검증한다."""
    errors: List[str] = []
    _require_object(d, "manifest", errors)
    if errors:
        return False, errors

    manifest = d
    _require_string(manifest, "intent", "manifest", errors)
    _require_string_list(manifest, "allowed_tools", "manifest", errors, min_items=1)
    _require_string_list(manifest, "required_outputs", "manifest", errors, min_items=1)
    _require_int(manifest, "token_budget", "manifest", errors, min_value=1)
    _require_number(manifest, "reliability_score", "manifest", errors, min_value=0, max_value=1)
    return len(errors) == 0, errors


def validate_vault_frontmatter(d: Any) -> ValidationResult:
    """Vault page frontmatter v0.4 필수 메타데이터를 검증한다."""
    errors: List[str] = []
    _require_object(d, "frontmatter", errors)
    if errors:
        return False, errors

    frontmatter = d
    _require_schema_version(frontmatter, VAULT_SCHEMA_VERSION, "frontmatter", errors)
    _require_number(frontmatter, "uncertainty", "frontmatter", errors, min_value=0, max_value=1)
    _require_number(frontmatter, "verified_claim_ratio", "frontmatter", errors, min_value=0, max_value=1)
    _require_string(frontmatter, "belief_valid_from", "frontmatter", errors)
    _require_string(frontmatter, "belief_updated_at", "frontmatter", errors)
    _require_string_list(frontmatter, "supersedes", "frontmatter", errors, allow_empty=True)
    _require_enum(frontmatter, "sensitivity", "frontmatter", errors, SENSITIVITY_LEVELS)
    return len(errors) == 0, errors


def validate_council_report_v3(d: Any) -> ValidationResult:
    """Council Report v3 구조와 v0.4 schema_version 강제를 검증한다."""
    errors: List[str] = []
    _require_object(d, "report", errors)
    if errors:
        return False, errors

    report = d
    _require_schema_version(report, COUNCIL_SCHEMA_VERSION, "report", errors)
    personas = _require_list(report, "personas", "report", errors, min_items=1)
    rounds = _require_list(report, "rounds", "report", errors, min_items=1)

    for idx, persona in enumerate(personas):
        path = f"report.personas[{idx}]"
        if not _is_object(persona, path, errors):
            continue
        manifest = persona.get("agent_manifest")
        ok, manifest_errors = validate_agent_manifest(manifest)
        if not ok:
            errors.extend(f"{path}.agent_manifest: {error}" for error in manifest_errors)

    for idx, round_entry in enumerate(rounds):
        _validate_round(round_entry, f"report.rounds[{idx}]", errors)

    grounding = report.get("citation_grounding")
    if _is_object(grounding, "report.citation_grounding", errors):
        _validate_citation_grounding(grounding, "report.citation_grounding", errors)

    evidence = report.get("evidence", [])
    if evidence is not None:
        if not isinstance(evidence, list):
            errors.append("report.evidence must be a list")
        else:
            for idx, item in enumerate(evidence):
                _validate_evidence(item, f"report.evidence[{idx}]", errors)

    final = report.get("final")
    if _is_object(final, "report.final", errors):
        _validate_final(final, "report.final", errors)

    return len(errors) == 0, errors


def _validate_round(d: Any, path: str, errors: List[str]) -> None:
    if not _is_object(d, path, errors):
        return
    _require_string(d, "stop_reason", path, errors)
    _require_string(d, "context_checksum", path, errors)

    convergence = d.get("convergence")
    if _is_object(convergence, f"{path}.convergence", errors):
        _require_number(convergence, "consensus_score", f"{path}.convergence", errors, min_value=0, max_value=1)
        _require_number(convergence, "ambiguity", f"{path}.convergence", errors, min_value=0, max_value=1)
        _require_number(convergence, "coverage", f"{path}.convergence", errors, min_value=0, max_value=1)
        _require_int(convergence, "contradiction_count", f"{path}.convergence", errors, min_value=0)
        _require_number(convergence, "confidence_mad", f"{path}.convergence", errors, min_value=0)
        _require_number(convergence, "belief_delta", f"{path}.convergence", errors)
        _require_number(convergence, "dominant_position_ratio", f"{path}.convergence", errors, min_value=0, max_value=1)
        _require_bool(convergence, "can_stop", f"{path}.convergence", errors)

    ratchet = d.get("ratchet")
    if _is_object(ratchet, f"{path}.ratchet", errors):
        _require_string(ratchet, "decision", f"{path}.ratchet", errors)
        _require_number(ratchet, "effect_size_mad", f"{path}.ratchet", errors, min_value=0)
        _require_number(ratchet, "ratchet_score", f"{path}.ratchet", errors)
        _require_list(ratchet, "deltas", f"{path}.ratchet", errors)


def _validate_citation_grounding(d: Dict[str, Any], path: str, errors: List[str]) -> None:
    _require_number(d, "verified_claim_ratio", path, errors, min_value=0, max_value=1)
    _require_int(d, "total_claim_count", path, errors, min_value=0)
    _require_int(d, "unsupported_critical_claim_count", path, errors, min_value=0)
    claims = _require_list(d, "per_claim_verdict", path, errors)
    for idx, claim in enumerate(claims):
        _validate_claim(claim, f"{path}.per_claim_verdict[{idx}]", errors)


def _validate_claim(d: Any, path: str, errors: List[str]) -> None:
    if not _is_object(d, path, errors):
        return
    _require_string(d, "claim_id", path, errors)
    _require_string(d, "text", path, errors)
    _require_bool(d, "is_critical", path, errors)
    _require_string_list(d, "supporting_evidence_ids", path, errors, allow_empty=True)
    _require_enum(d, "verification_status", path, errors, CLAIM_STATUSES)


def _validate_evidence(d: Any, path: str, errors: List[str]) -> None:
    if not _is_object(d, path, errors):
        return
    _require_string(d, "id", path, errors)
    _require_enum(d, "type", path, errors, EVIDENCE_TYPES)
    _require_string(d, "source", path, errors)
    _require_string(d, "quote", path, errors)
    span = _require_list(d, "quote_span", path, errors)
    if len(span) != 2 or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in span):
        errors.append(f"{path}.quote_span must be two non-negative integers")
    _require_string(d, "hash", path, errors)
    _require_string(d, "fetched_at", path, errors)


def _validate_final(d: Dict[str, Any], path: str, errors: List[str]) -> None:
    scores = d.get("scores")
    if _is_object(scores, f"{path}.scores", errors):
        axes = scores.get("axes")
        if not isinstance(axes, dict):
            errors.append(f"{path}.scores.axes must be an object")
        _require_number(scores, "total", f"{path}.scores", errors)
        _require_number(scores, "rubric_max", f"{path}.scores", errors, min_value=1)
        _require_enum(scores, "verdict", f"{path}.scores", errors, VERDICTS)
        _require_string(scores, "verdict_reason", f"{path}.scores", errors)
    if not isinstance(d.get("vault_metadata"), dict):
        errors.append(f"{path}.vault_metadata must be an object")
    if not isinstance(d.get("cost_trace"), dict):
        errors.append(f"{path}.cost_trace must be an object")


def _require_schema_version(d: Dict[str, Any], expected: str, path: str, errors: List[str]) -> None:
    if "schema_version" not in d:
        errors.append(f"{path}.schema_version missing")
        errors.append("SchemaVersionMissing: schema_version missing")
        return
    if d.get("schema_version") != expected:
        errors.append(f"{path}.schema_version must be {expected!r}")


def _require_object(d: Any, path: str, errors: List[str]) -> None:
    if not isinstance(d, dict):
        errors.append(f"{path} must be an object")


def _is_object(d: Any, path: str, errors: List[str]) -> bool:
    if isinstance(d, dict):
        return True
    errors.append(f"{path} must be an object")
    return False


def _require_string(d: Dict[str, Any], key: str, path: str, errors: List[str]) -> None:
    if key not in d:
        errors.append(f"{path}.{key} missing")
    elif not isinstance(d[key], str) or not d[key]:
        errors.append(f"{path}.{key} must be a non-empty string")


def _require_bool(d: Dict[str, Any], key: str, path: str, errors: List[str]) -> None:
    if key not in d:
        errors.append(f"{path}.{key} missing")
    elif not isinstance(d[key], bool):
        errors.append(f"{path}.{key} must be a boolean")


def _require_int(
    d: Dict[str, Any],
    key: str,
    path: str,
    errors: List[str],
    min_value: int = None,
) -> None:
    if key not in d:
        errors.append(f"{path}.{key} missing")
        return
    value = d[key]
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{path}.{key} must be an integer")
        return
    if min_value is not None and value < min_value:
        errors.append(f"{path}.{key} must be >= {min_value}")


def _require_number(
    d: Dict[str, Any],
    key: str,
    path: str,
    errors: List[str],
    min_value: float = None,
    max_value: float = None,
) -> None:
    if key not in d:
        errors.append(f"{path}.{key} missing")
        return
    value = d[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{path}.{key} must be a number")
        return
    if min_value is not None and value < min_value:
        errors.append(f"{path}.{key} must be >= {min_value}")
    if max_value is not None and value > max_value:
        errors.append(f"{path}.{key} must be <= {max_value}")


def _require_enum(
    d: Dict[str, Any],
    key: str,
    path: str,
    errors: List[str],
    allowed: Iterable[str],
) -> None:
    if key not in d:
        errors.append(f"{path}.{key} missing")
        return
    if d[key] not in allowed:
        errors.append(f"{path}.{key} must be one of {sorted(allowed)}")


def _require_list(
    d: Dict[str, Any],
    key: str,
    path: str,
    errors: List[str],
    min_items: int = 0,
) -> List[Any]:
    if key not in d:
        errors.append(f"{path}.{key} missing")
        return []
    value = d[key]
    if not isinstance(value, list):
        errors.append(f"{path}.{key} must be a list")
        return []
    if len(value) < min_items:
        errors.append(f"{path}.{key} must contain at least {min_items} item(s)")
    return value


def _require_string_list(
    d: Dict[str, Any],
    key: str,
    path: str,
    errors: List[str],
    min_items: int = 0,
    allow_empty: bool = False,
) -> None:
    values = _require_list(d, key, path, errors, min_items=min_items)
    if not values and allow_empty:
        return
    for idx, item in enumerate(values):
        if not isinstance(item, str) or (not item and not allow_empty):
            errors.append(f"{path}.{key}[{idx}] must be a string")
