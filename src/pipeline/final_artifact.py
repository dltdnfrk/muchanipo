"""Canonical GOALS artifact projection for the final HTML/YAML report stage."""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field, is_dataclass, asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.muchanipo.events import normalize_goals_event
from src.pipeline.goals_artifacts import build_goals_stage_artifact


FINAL_REPORT_STAGE_ID = "final_report_html_yaml"
FINAL_REPORT_ARTIFACT_CONTRACT = "final_report_html_yaml_stage_artifact.v1"
FINAL_REPORT_BUNDLE_CONTRACT = "final_report_html_yaml_bundle.v1"
FINAL_REPORT_RUBRIC_VERSION = "goals-loop2-final-report.v1"

FINAL_REPORT_UPSTREAM_STAGE_IDS: tuple[str, ...] = (
    "deep_research_max",
    "plannotator_review",
    "ontology_extraction",
    "persona_generation",
    "llm_council",
)

FINAL_REPORT_GATE_IDS: tuple[str, ...] = (
    "plan",
    "evidence",
    "report",
    "knowledge_write",
)

FINAL_REPORT_FAILURE_MODES: tuple[str, ...] = (
    "blocked_final_upstream_artifact_missing",
    "blocked_final_upstream_artifact_not_ready",
    "blocked_final_gate_pending",
    "blocked_final_report_gate_rejected",
    "blocked_final_live_synthetic_artifact",
    "blocked_final_council_not_ready",
    "blocked_final_no_central_claims",
    "blocked_final_artifact_rejected",
)


@dataclass(frozen=True)
class FinalReportArtifactInput:
    report_id: str
    title: str
    report_markdown: str
    output_dir: Path | str
    upstream_artifacts: Mapping[str, Any] = field(default_factory=dict)
    evidence_refs: Sequence[Any] = field(default_factory=tuple)
    open_gaps: Sequence[str] = field(default_factory=tuple)
    gates: Mapping[str, Any] = field(default_factory=dict)
    reference_runtime_artifacts: Mapping[str, Any] = field(default_factory=dict)
    require_live: bool = False
    obsidian_write_path: str = ""
    obsidian_write_attempted: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


def build_final_report_stage_artifact(
    artifact_input: FinalReportArtifactInput,
) -> dict[str, Any]:
    """Build and persist the final report bundle under the public GOALS contract."""

    output_paths = _output_paths(artifact_input)
    upstream_records = _upstream_records(artifact_input.upstream_artifacts)
    review_records = _review_records(artifact_input.upstream_artifacts.get("plannotator_review"))
    gate_records = _gate_records(artifact_input.gates, review_records=review_records)
    council_payload = _council_payload(artifact_input.upstream_artifacts.get("llm_council"))
    evidence_records = [_evidence_payload(ref) for ref in artifact_input.evidence_refs]
    blockers = _final_blockers(
        artifact_input=artifact_input,
        upstream_records=upstream_records,
        gate_records=gate_records,
        council_payload=council_payload,
    )
    blocker_codes = [str(blocker["code"]) for blocker in blockers]
    central_claims = _central_claims_from_council(council_payload)
    if not central_claims:
        blockers.append(
            {
                "code": "blocked_final_no_central_claims",
                "message": "Final report requires central claims from the llm_council artifact.",
                "severity": "blocker",
                "recoverable": True,
                "required_action": "rerun_or_repair_llm_council_claim_outputs",
                "human_decision_required": False,
            }
        )
        blocker_codes = [str(blocker["code"]) for blocker in blockers]

    gate_statuses = _manifest_gate_statuses(
        gate_records,
        blockers=blockers,
        obsidian_write_path=artifact_input.obsidian_write_path,
        obsidian_write_attempted=artifact_input.obsidian_write_attempted,
    )
    obsidian_write_status = _obsidian_write_status(
        blockers=blockers,
        obsidian_write_path=artifact_input.obsidian_write_path,
        obsidian_write_attempted=artifact_input.obsidian_write_attempted,
    )
    gbrain_record = _gbrain_record(
        artifact_input.reference_runtime_artifacts,
        report_id=artifact_input.report_id,
    )
    gbrain_record_status = (
        "runtime_record_written" if gbrain_record["runtime_present"] else "skipped_unavailable"
    )
    manifest = {
        "html_path": str(output_paths["html"]),
        "yaml_path": str(output_paths["yaml"]),
        "evidence_bundle_path": str(output_paths["evidence_bundle"]),
        "gbrain_record_path": str(output_paths["gbrain_record"]),
        "gbrain_record_status": gbrain_record_status,
        "obsidian_write_status": obsidian_write_status,
        "obsidian_write_path": str(artifact_input.obsidian_write_path or ""),
        "gate_statuses": gate_statuses,
    }
    bundle = {
        "schema_version": 1,
        "contract": FINAL_REPORT_BUNDLE_CONTRACT,
        "report_id": str(artifact_input.report_id or ""),
        "title": str(artifact_input.title or ""),
        "verdict": "BLOCKED" if blockers else "PASS",
        "central_claims": central_claims,
        "source_ids": _source_ids(evidence_records, council_payload),
        "evidence_ids": _evidence_ids(evidence_records, council_payload),
        "open_gaps": _open_gaps(artifact_input, council_payload),
        "blockers": blockers,
    }
    parity = _bundle_parity(bundle, bundle)
    payload = {
        "schema_version": 1,
        "artifact_id": FINAL_REPORT_STAGE_ID,
        "contract": FINAL_REPORT_ARTIFACT_CONTRACT,
        "artifact_manifest": manifest,
        "bundle": bundle,
        "upstream_artifacts": upstream_records,
        "plannotator_review_records": review_records,
        "gates": list(gate_records.values()),
        "html_yaml_parity": parity,
        "gbrain_record": gbrain_record,
        "mode_honesty": {
            "require_live": bool(artifact_input.require_live),
            "synthetic_artifact_present": _contains_synthetic(artifact_input.upstream_artifacts)
            or _contains_synthetic(artifact_input.gates),
        },
        "downstream_consumability": {
            "knowledge_write_ready": not bool(blockers),
            "reasons": blocker_codes,
        },
    }
    _write_outputs(
        output_paths,
        payload=payload,
        report_markdown=artifact_input.report_markdown,
    )

    status = "blocked" if blockers else "completed"
    return build_goals_stage_artifact(
        FINAL_REPORT_STAGE_ID,
        status=status,
        inputs=[
            {
                "artifact_id": "upstream_artifacts",
                "required_stage_ids": list(FINAL_REPORT_UPSTREAM_STAGE_IDS),
                "records": upstream_records,
            },
            {
                "artifact_id": "approved_gates",
                "gate_ids": ["plan", "evidence", "report"],
                "records": list(gate_records.values()),
            },
        ],
        outputs=[
            {
                "artifact_id": FINAL_REPORT_STAGE_ID,
                "contract": FINAL_REPORT_ARTIFACT_CONTRACT,
                "present": True,
                "payload": payload,
            },
            {
                "artifact_id": "artifact_manifest",
                "present": True,
                "payload": manifest,
            },
            {
                "artifact_id": "html_yaml_parity",
                "present": True,
                "payload": parity,
            },
            {
                "artifact_id": "knowledge_write_gate",
                "present": True,
                "payload": {
                    "gate_id": "knowledge_write",
                    "status": gate_statuses["knowledge_write"],
                    "obsidian_write_status": obsidian_write_status,
                    "gbrain_record_status": gbrain_record_status,
                },
            },
        ],
        blockers=blockers,
        gates=[
            {"gate_id": gate_id, "status": status_value}
            for gate_id, status_value in gate_statuses.items()
        ],
        human_decision={
            "required": bool(blockers),
            "status": "pending" if blockers else "not_required",
            "mode": "review_final_report_html_yaml" if blockers else "",
            "rationale": "; ".join(blocker_codes),
            "required_action": _required_action(blocker_codes[0] if blocker_codes else ""),
        },
        evidence_refs=bundle["evidence_ids"],
        source_refs=bundle["source_ids"],
        metrics={
            "central_claim_count": len(bundle["central_claims"]),
            "source_id_count": len(bundle["source_ids"]),
            "evidence_id_count": len(bundle["evidence_ids"]),
            "open_gap_count": len(bundle["open_gaps"]),
            "blocker_count": len(blockers),
            "gate_count": len(gate_statuses),
            "html_yaml_parity": parity["matched"],
            "obsidian_write_status": obsidian_write_status,
            "gbrain_record_status": gbrain_record_status,
        },
        progress_percent=100.0 if not blockers else 85.0,
        legacy_subactivity={
            "legacy_stage_ids": ["report", "vault", "done"],
            "subactivity": "final_report_html_yaml_bundle",
        },
        hermes_scoring={
            "score": 5.0 if not blockers else 2.0,
            "readiness": "ready" if not blockers else "blocked",
            "confidence": _council_confidence(council_payload),
            "rubric_version": FINAL_REPORT_RUBRIC_VERSION,
            "issues": blocker_codes,
        },
        retry={
            "retryable": bool(blockers),
            "next_action": _required_action(blocker_codes[0] if blocker_codes else ""),
        },
        failure_semantics={
            "code": blocker_codes[0] if blocker_codes else "",
            "terminal": False,
            "retryable": bool(blockers),
            "failure_modes": list(FINAL_REPORT_FAILURE_MODES),
        },
        metadata={
            "specific_contract": FINAL_REPORT_ARTIFACT_CONTRACT,
            "claim_boundary": (
                "Final report claims are projected from canonical upstream artifacts, "
                "especially llm_council round digests and explicit evidence ids. "
                "Topic text is display context, not a hidden reconstruction source."
            ),
            **dict(artifact_input.metadata),
        },
    )


def build_final_report_stage_event(
    artifact_input: FinalReportArtifactInput,
) -> dict[str, Any]:
    artifact = build_final_report_stage_artifact(artifact_input)
    event_name = "stage_completed" if artifact["status"] == "completed" else "stage_blocked"
    return normalize_goals_event(
        {
            "event": event_name,
            "stage": FINAL_REPORT_STAGE_ID,
            "status": artifact["status"],
            **final_report_event_metadata(artifact),
        }
    )


def final_report_event_metadata(final_artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Project final-report artifact fields needed by event/progress consumers."""

    payload = final_report_payload_from_stage_artifact(final_artifact)
    raw_manifest = payload.get("artifact_manifest")
    manifest = raw_manifest if isinstance(raw_manifest, Mapping) else {}
    raw_downstream = payload.get("downstream_consumability")
    downstream = raw_downstream if isinstance(raw_downstream, Mapping) else {}
    raw_bundle = payload.get("bundle")
    bundle = raw_bundle if isinstance(raw_bundle, Mapping) else {}
    raw_gate_statuses = manifest.get("gate_statuses")
    gate_statuses = (
        {str(key): str(value or "") for key, value in raw_gate_statuses.items()}
        if isinstance(raw_gate_statuses, Mapping)
        else {}
    )
    blocker_codes = _event_blocker_codes(
        final_artifact=final_artifact,
        payload=payload,
        downstream=downstream,
    )
    central_claims = _string_list(bundle.get("central_claims"))
    knowledge_write_ready = bool(downstream.get("knowledge_write_ready"))
    return {
        "artifact_ref": "state:final_report_html_yaml_artifact",
        "html_path": str(manifest.get("html_path") or ""),
        "yaml_path": str(manifest.get("yaml_path") or ""),
        "obsidian_write_status": str(manifest.get("obsidian_write_status") or ""),
        "evidence_bundle_path": str(manifest.get("evidence_bundle_path") or ""),
        "gbrain_record_path": str(manifest.get("gbrain_record_path") or ""),
        "gbrain_record_status": str(manifest.get("gbrain_record_status") or ""),
        "blockers": blocker_codes,
        "blocker_codes": blocker_codes,
        "blocker_count": len(blocker_codes),
        "final_report_ready": knowledge_write_ready,
        "knowledge_write_ready": knowledge_write_ready,
        "gate_statuses": gate_statuses,
        "central_claim_count": len(central_claims),
    }


def assert_final_report_artifact_ready_for_knowledge_write(
    final_artifact: Mapping[str, Any],
) -> None:
    payload = final_report_payload_from_stage_artifact(final_artifact)
    downstream = payload.get("downstream_consumability") or {}
    if downstream.get("knowledge_write_ready"):
        return
    reasons = _string_list(downstream.get("reasons"))
    blocker_code = reasons[0] if reasons else "blocked_final_upstream_artifact_not_ready"
    raise ValueError(f"{blocker_code}: {', '.join(reasons)}")


def final_report_payload_from_stage_artifact(
    final_artifact: Mapping[str, Any],
) -> dict[str, Any]:
    if final_artifact.get("artifact_id") == FINAL_REPORT_STAGE_ID:
        return dict(final_artifact)
    for output in final_artifact.get("outputs", []) or []:
        if isinstance(output, Mapping) and output.get("artifact_id") == FINAL_REPORT_STAGE_ID:
            payload = output.get("payload")
            if isinstance(payload, Mapping):
                return dict(payload)
    return dict(final_artifact)


def _event_blocker_codes(
    *,
    final_artifact: Mapping[str, Any],
    payload: Mapping[str, Any],
    downstream: Mapping[str, Any],
) -> list[str]:
    codes: list[str] = []
    for source in (final_artifact.get("blockers"), payload.get("blockers")):
        for blocker in source or []:
            if isinstance(blocker, Mapping):
                codes.append(str(blocker.get("code") or ""))
            else:
                codes.append(str(blocker or ""))

    raw_bundle = payload.get("bundle")
    if isinstance(raw_bundle, Mapping):
        for blocker in raw_bundle.get("blockers", []) or []:
            if isinstance(blocker, Mapping):
                codes.append(str(blocker.get("code") or ""))
            else:
                codes.append(str(blocker or ""))

    codes.extend(_string_list(downstream.get("reasons")))
    return _dedupe_strings(codes)


def final_report_stage_artifact_contract_report() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract": FINAL_REPORT_ARTIFACT_CONTRACT,
        "stage_id": FINAL_REPORT_STAGE_ID,
        "builder": "build_final_report_stage_artifact",
        "event_builder": "build_final_report_stage_event",
        "required_inputs": list(FINAL_REPORT_UPSTREAM_STAGE_IDS),
        "required_outputs": [
            "artifact_manifest",
            "final_report_html_yaml.bundle",
            "html_path",
            "yaml_path",
            "evidence_bundle_path",
            "gbrain_record_path",
            "knowledge_write_gate",
            "html_yaml_parity",
        ],
        "manifest_fields": [
            "html_path",
            "yaml_path",
            "evidence_bundle_path",
            "gbrain_record_path",
            "gbrain_record_status",
            "obsidian_write_status",
            "gate_statuses",
        ],
        "gate_ids": list(FINAL_REPORT_GATE_IDS),
        "failure_modes": list(FINAL_REPORT_FAILURE_MODES),
        "knowledge_write_rule": (
            "Knowledge write is allowed only after upstream artifacts are ready, "
            "plan/evidence/report gates are approved, live mode has no synthetic "
            "artifact fallback, and the final artifact is not rejected."
        ),
        "honesty_rule": (
            "GBrain and Obsidian write status records available runtime/path evidence. "
            "No adapter or path is reported as skipped_unavailable rather than success."
        ),
        "fixture_isolation": (
            "Central claims come from upstream artifact payloads. Topic text is not "
            "used to rebuild claims, ontology, personas, council conclusions, or "
            "benchmark-specific assertions."
        ),
        "compatibility": (
            "Legacy report, vault, and done substeps project to the canonical "
            "final_report_html_yaml public stage."
        ),
    }


def _output_paths(artifact_input: FinalReportArtifactInput) -> dict[str, Path]:
    output_dir = Path(artifact_input.output_dir)
    stem = _safe_stem(artifact_input.report_id or artifact_input.title or FINAL_REPORT_STAGE_ID)
    return {
        "html": output_dir / f"{stem}-final-report.html",
        "yaml": output_dir / f"{stem}-final-report.yaml",
        "evidence_bundle": output_dir / f"{stem}-evidence-bundle.json",
        "gbrain_record": output_dir / f"{stem}-gbrain-record.json",
    }


def _write_outputs(
    output_paths: Mapping[str, Path],
    *,
    payload: Mapping[str, Any],
    report_markdown: str,
) -> None:
    for path in output_paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    bundle = dict(payload["bundle"])
    output_paths["html"].write_text(
        _render_html_bundle(bundle, report_markdown=report_markdown),
        encoding="utf-8",
    )
    # JSON is valid YAML 1.2 and preserves exact parity without an added parser dependency.
    output_paths["yaml"].write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output_paths["evidence_bundle"].write_text(
        json.dumps(
            {
                "schema_version": 1,
                "contract": "final_report_evidence_bundle.v1",
                "bundle": bundle,
                "upstream_artifacts": payload["upstream_artifacts"],
                "gates": payload["gates"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    output_paths["gbrain_record"].write_text(
        json.dumps(
            payload["gbrain_record"],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def _render_html_bundle(bundle: Mapping[str, Any], *, report_markdown: str) -> str:
    json_payload = json.dumps(bundle, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    claims = "\n".join(
        f"<li>{html.escape(str(claim))}</li>" for claim in bundle.get("central_claims", []) or []
    )
    evidence = "\n".join(
        f"<li>{html.escape(str(evidence_id))}</li>"
        for evidence_id in bundle.get("evidence_ids", []) or []
    )
    gaps = "\n".join(
        f"<li>{html.escape(str(gap))}</li>" for gap in bundle.get("open_gaps", []) or []
    )
    blockers = "\n".join(
        f"<li>{html.escape(str((blocker or {}).get('code') or blocker))}</li>"
        for blocker in bundle.get("blockers", []) or []
    )
    return (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        f"  <title>{html.escape(str(bundle.get('title') or 'Final report'))}</title>\n"
        "</head>\n"
        "<body>\n"
        f"  <h1>{html.escape(str(bundle.get('title') or 'Final report'))}</h1>\n"
        f"  <p data-verdict>{html.escape(str(bundle.get('verdict') or ''))}</p>\n"
        "  <section id=\"central-claims\"><h2>Central Claims</h2><ul>\n"
        f"{claims}\n"
        "  </ul></section>\n"
        "  <section id=\"evidence\"><h2>Evidence IDs</h2><ul>\n"
        f"{evidence}\n"
        "  </ul></section>\n"
        "  <section id=\"open-gaps\"><h2>Open Gaps</h2><ul>\n"
        f"{gaps}\n"
        "  </ul></section>\n"
        "  <section id=\"blockers\"><h2>Blockers</h2><ul>\n"
        f"{blockers}\n"
        "  </ul></section>\n"
        "  <section id=\"report-markdown\"><h2>Report Markdown</h2><pre>"
        f"{html.escape(str(report_markdown or ''))}</pre></section>\n"
        f"  <script type=\"application/json\" id=\"final-report-bundle\">{json_payload}</script>\n"
        "</body>\n"
        "</html>\n"
    )


def _upstream_records(upstream_artifacts: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for stage_id in FINAL_REPORT_UPSTREAM_STAGE_IDS:
        raw = upstream_artifacts.get(stage_id)
        items = _as_sequence(raw)
        statuses = [_stage_status(item) for item in items]
        blockers = [
            dict(blocker)
            for item in items
            for blocker in _artifact_blockers(item)
            if isinstance(blocker, Mapping)
        ]
        metadata_records = [
            _artifact_metadata(item)
            for item in items
            if _artifact_metadata(item)
        ]
        if not items:
            status = "missing"
        elif any(status in {"blocked", "failed"} for status in statuses):
            status = "blocked"
        elif all(status == "completed" for status in statuses):
            status = "completed"
        else:
            status = "pending"
        records[stage_id] = {
            "stage_id": stage_id,
            "present": bool(items),
            "status": status,
            "artifact_count": len(items),
            "contracts": _dedupe_strings(_artifact_contract(item) for item in items),
            "blockers": blockers,
            "synthetic": _contains_synthetic(raw),
            "offline_nonblocking": any(
                bool(metadata.get("offline_mock_continuation"))
                for metadata in metadata_records
            ),
        }
    return records


def _review_records(raw_reviews: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in _as_sequence(raw_reviews):
        review_target = _output_by_id(item, "review_decision")
        annotation_parse = _output_by_id(item, "annotation_parse")
        gate_name = ""
        for input_item in item.get("inputs", []) if isinstance(item, Mapping) else []:
            if isinstance(input_item, Mapping) and input_item.get("artifact_id") == "review_target":
                gate_name = str(input_item.get("gate_name") or "")
                break
        records.append(
            {
                "stage_id": "plannotator_review",
                "gate_name": gate_name,
                "gate_id": str(review_target.get("gate_id") or gate_name),
                "status": str(review_target.get("review_state") or _stage_status(item)),
                "session_path": str(review_target.get("session_path") or ""),
                "mode": str(review_target.get("mode") or ""),
                "synthetic": bool(review_target.get("synthetic")),
                "annotation_count": int(annotation_parse.get("annotation_count") or 0),
            }
        )
    return records


def _gate_records(
    gates: Mapping[str, Any],
    *,
    review_records: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for gate_id in ("plan", "evidence", "report"):
        raw = gates.get(gate_id)
        review = next(
            (
                item
                for item in review_records
                if str(item.get("gate_name") or item.get("gate_id") or "").startswith(gate_id)
            ),
            {},
        )
        status = _gate_status(raw) or str(review.get("status") or "pending")
        records[gate_id] = {
            "gate_id": gate_id,
            "status": status,
            "approved": status in {"approved", "passed", "completed"},
            "synthetic": _gate_synthetic(raw) or bool(review.get("synthetic")),
            "path": _gate_path(raw) or str(review.get("session_path") or ""),
        }
    return records


def _final_blockers(
    *,
    artifact_input: FinalReportArtifactInput,
    upstream_records: Mapping[str, Mapping[str, Any]],
    gate_records: Mapping[str, Mapping[str, Any]],
    council_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for stage_id in FINAL_REPORT_UPSTREAM_STAGE_IDS:
        record = upstream_records.get(stage_id) or {}
        if not record.get("present"):
            blockers.append(_blocker("blocked_final_upstream_artifact_missing", stage_id=stage_id))
        elif record.get("status") != "completed":
            if record.get("offline_nonblocking") and not artifact_input.require_live:
                continue
            blockers.append(_blocker("blocked_final_upstream_artifact_not_ready", stage_id=stage_id))

    for gate_id in ("plan", "evidence", "report"):
        record = gate_records.get(gate_id) or {}
        status = str(record.get("status") or "pending")
        if status in {"pending", "human_review_pending", ""}:
            blockers.append(_blocker("blocked_final_gate_pending", gate_id=gate_id))
        elif status not in {"approved", "passed", "completed"}:
            blockers.append(_blocker("blocked_final_report_gate_rejected", gate_id=gate_id))

    downstream = council_payload.get("downstream_consumability")
    if isinstance(downstream, Mapping) and not downstream.get("final_report_ready"):
        blockers.append(_blocker("blocked_final_council_not_ready", stage_id="llm_council"))

    if artifact_input.require_live:
        if _contains_synthetic(artifact_input.upstream_artifacts) or _contains_synthetic(artifact_input.gates):
            blockers.append(_blocker("blocked_final_live_synthetic_artifact"))

    if bool(artifact_input.metadata.get("final_artifact_rejected")):
        blockers.append(_blocker("blocked_final_artifact_rejected"))

    return _dedupe_blockers(blockers)


def _blocker(code: str, **context: Any) -> dict[str, Any]:
    return {
        "code": code,
        "message": _blocker_message(code),
        "severity": "blocker",
        "recoverable": code != "blocked_final_artifact_rejected",
        "required_action": _required_action(code),
        "human_decision_required": code
        in {"blocked_final_gate_pending", "blocked_final_report_gate_rejected", "blocked_final_artifact_rejected"},
        **context,
    }


def _blocker_message(code: str) -> str:
    messages = {
        "blocked_final_upstream_artifact_missing": "A required upstream GOALS artifact is missing.",
        "blocked_final_upstream_artifact_not_ready": "A required upstream GOALS artifact is not completed.",
        "blocked_final_gate_pending": "A required plan/evidence/report review gate is still pending.",
        "blocked_final_report_gate_rejected": "A required plan/evidence/report review gate rejected or requested changes.",
        "blocked_final_live_synthetic_artifact": "Live final report delivery cannot use synthetic upstream artifacts or HITL approvals.",
        "blocked_final_council_not_ready": "The LLM council artifact does not allow final report generation.",
        "blocked_final_no_central_claims": "The final report has no central claims from the LLM council artifact.",
        "blocked_final_artifact_rejected": "The final report artifact was explicitly rejected.",
    }
    return messages.get(code, "Final report artifact is blocked.")


def _required_action(code: str) -> str:
    actions = {
        "blocked_final_upstream_artifact_missing": "produce_required_upstream_stage_artifact",
        "blocked_final_upstream_artifact_not_ready": "repair_upstream_artifact_before_final_report",
        "blocked_final_gate_pending": "wait_for_required_review_gate",
        "blocked_final_report_gate_rejected": "revise_final_report_or_gate_target_before_resubmission",
        "blocked_final_live_synthetic_artifact": "rerun_with_real_live_artifacts_and_human_review",
        "blocked_final_council_not_ready": "repair_llm_council_final_report_readiness",
        "blocked_final_no_central_claims": "rerun_or_repair_llm_council_claim_outputs",
        "blocked_final_artifact_rejected": "revise_final_report_artifact_before_delivery",
    }
    return actions.get(code, "resolve_final_report_blocker")


def _manifest_gate_statuses(
    gate_records: Mapping[str, Mapping[str, Any]],
    *,
    blockers: Sequence[Mapping[str, Any]],
    obsidian_write_path: str,
    obsidian_write_attempted: bool,
) -> dict[str, str]:
    statuses = {
        gate_id: str((gate_records.get(gate_id) or {}).get("status") or "pending")
        for gate_id in ("plan", "evidence", "report")
    }
    if blockers:
        statuses["knowledge_write"] = "blocked"
    elif obsidian_write_attempted and str(obsidian_write_path).strip():
        statuses["knowledge_write"] = "passed"
    else:
        statuses["knowledge_write"] = "skipped_unavailable"
    return statuses


def _obsidian_write_status(
    *,
    blockers: Sequence[Mapping[str, Any]],
    obsidian_write_path: str,
    obsidian_write_attempted: bool,
) -> str:
    if blockers:
        return "blocked"
    if obsidian_write_attempted and str(obsidian_write_path).strip():
        return "written"
    if str(obsidian_write_path).strip():
        return "available_not_written"
    return "skipped_unavailable"


def _gbrain_record(reference_runtime_artifacts: Mapping[str, Any], *, report_id: str) -> dict[str, Any]:
    gbrain = reference_runtime_artifacts.get("gbrain")
    if not isinstance(gbrain, Mapping):
        return {
            "schema_version": 1,
            "contract": "final_report_gbrain_record.v1",
            "report_id": str(report_id or ""),
            "runtime_present": False,
            "write_status": "skipped_unavailable",
            "reason": "no_gbrain_runtime_record",
        }
    runtime = gbrain.get("gbrain_runtime")
    return {
        "schema_version": 1,
        "contract": "final_report_gbrain_record.v1",
        "report_id": str(report_id or ""),
        "runtime_present": isinstance(runtime, Mapping),
        "write_status": "runtime_record_written" if isinstance(runtime, Mapping) else "skipped_unavailable",
        "content_hash": str(gbrain.get("content_hash") or ""),
        "runtime": dict(runtime) if isinstance(runtime, Mapping) else {},
        "external_adapter_write": "not_attempted",
    }


def _bundle_parity(html_bundle: Mapping[str, Any], yaml_bundle: Mapping[str, Any]) -> dict[str, Any]:
    fields = ("central_claims", "source_ids", "evidence_ids", "verdict", "open_gaps", "blockers")
    mismatches = [field for field in fields if html_bundle.get(field) != yaml_bundle.get(field)]
    return {
        "matched": not mismatches,
        "fields": list(fields),
        "mismatches": mismatches,
    }


def _central_claims_from_council(council_payload: Mapping[str, Any]) -> list[str]:
    claims: list[str] = []
    for round_record in council_payload.get("round_digests", []) or []:
        if not isinstance(round_record, Mapping):
            continue
        claims.append(str(round_record.get("key_claim") or ""))
        claims.extend(_string_list(round_record.get("body_claims")))
    return _dedupe_strings(claim for claim in claims if str(claim).strip())


def _evidence_ids(
    evidence_records: Sequence[Mapping[str, Any]],
    council_payload: Mapping[str, Any],
) -> list[str]:
    ids = [str(record.get("id") or "") for record in evidence_records]
    for round_record in council_payload.get("round_digests", []) or []:
        if isinstance(round_record, Mapping):
            ids.extend(_string_list(round_record.get("evidence_ref_ids")))
    for record in council_payload.get("evidence_refs", []) or []:
        if isinstance(record, Mapping):
            ids.append(str(record.get("id") or ""))
    return _dedupe_strings(item for item in ids if item)


def _source_ids(
    evidence_records: Sequence[Mapping[str, Any]],
    council_payload: Mapping[str, Any],
) -> list[str]:
    ids = [
        str(record.get("source_url") or record.get("source") or record.get("source_title") or "")
        for record in evidence_records
    ]
    for record in council_payload.get("evidence_refs", []) or []:
        if isinstance(record, Mapping):
            ids.append(str(record.get("source_url") or record.get("source") or record.get("source_title") or ""))
    return _dedupe_strings(item for item in ids if item)


def _open_gaps(
    artifact_input: FinalReportArtifactInput,
    council_payload: Mapping[str, Any],
) -> list[str]:
    gaps = [str(item) for item in artifact_input.open_gaps if str(item).strip()]
    for round_record in council_payload.get("round_digests", []) or []:
        if isinstance(round_record, Mapping):
            gaps.extend(_string_list(round_record.get("next_actions")))
            gaps.extend(_string_list(round_record.get("disagreements")))
    return _dedupe_strings(gaps)


def _council_payload(raw_artifact: Any) -> dict[str, Any]:
    for item in _as_sequence(raw_artifact):
        if isinstance(item, Mapping) and item.get("artifact_id") == "llm_council":
            return dict(item)
        output_payload = _output_by_id(item, "llm_council")
        if output_payload:
            payload = output_payload.get("payload")
            if isinstance(payload, Mapping):
                return dict(payload)
    return {}


def _output_by_id(artifact: Any, artifact_id: str) -> dict[str, Any]:
    if not isinstance(artifact, Mapping):
        return {}
    for output in artifact.get("outputs", []) or []:
        if isinstance(output, Mapping) and output.get("artifact_id") == artifact_id:
            return dict(output)
    return {}


def _artifact_contract(artifact: Any) -> str:
    if not isinstance(artifact, Mapping):
        return ""
    metadata = artifact.get("metadata")
    if isinstance(metadata, Mapping) and metadata.get("specific_contract"):
        return str(metadata.get("specific_contract") or "")
    return str(artifact.get("contract") or "")


def _artifact_metadata(artifact: Any) -> dict[str, Any]:
    if isinstance(artifact, Mapping) and isinstance(artifact.get("metadata"), Mapping):
        return dict(artifact.get("metadata") or {})
    return {}


def _stage_status(artifact: Any) -> str:
    if not isinstance(artifact, Mapping):
        return "missing"
    status = str(artifact.get("status") or "").strip()
    if status:
        return status
    if artifact.get("artifact_id") or artifact.get("outputs"):
        return "completed"
    return "pending"


def _artifact_blockers(artifact: Any) -> list[Any]:
    if isinstance(artifact, Mapping):
        return list(artifact.get("blockers", []) or [])
    return []


def _gate_status(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, Mapping):
        return str(raw.get("status") or raw.get("review_state") or "")
    return str(getattr(raw, "status", "") or "")


def _gate_synthetic(raw: Any) -> bool:
    if raw is None:
        return False
    if isinstance(raw, Mapping):
        return bool(raw.get("synthetic"))
    return bool(getattr(raw, "synthetic", False))


def _gate_path(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, Mapping):
        return str(raw.get("path") or raw.get("session_path") or "")
    return str(getattr(raw, "path", "") or "")


def _as_sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _evidence_payload(ref: Any) -> dict[str, Any]:
    if isinstance(ref, Mapping):
        return dict(ref)
    if is_dataclass(ref):
        return asdict(ref)
    return {
        "id": str(getattr(ref, "id", "") or ""),
        "source_url": str(getattr(ref, "source_url", "") or ""),
        "source_title": str(getattr(ref, "source_title", "") or ""),
        "quote": str(getattr(ref, "quote", "") or ""),
        "source_grade": str(getattr(ref, "source_grade", "") or ""),
    }


def _contains_synthetic(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            if key_text in {"synthetic", "synthetic_fallback"} and bool(item):
                return True
            if key_text == "evidence_association" and str(item) == "synthetic_aggregate":
                return True
            if _contains_synthetic(item):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_contains_synthetic(item) for item in value)
    return False


def _council_confidence(council_payload: Mapping[str, Any]) -> float:
    consensus = council_payload.get("consensus_status")
    if isinstance(consensus, Mapping):
        return float(consensus.get("average_confidence") or 0.0)
    confidences = [
        float(round_record.get("confidence") or 0.0)
        for round_record in council_payload.get("round_digests", []) or []
        if isinstance(round_record, Mapping)
    ]
    if not confidences:
        return 0.0
    return round(sum(confidences) / len(confidences), 3)


def _dedupe_blockers(blockers: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for blocker in blockers:
        code = str(blocker.get("code") or "")
        stage_id = str(blocker.get("stage_id") or "")
        gate_id = str(blocker.get("gate_id") or "")
        key = (code, stage_id, gate_id)
        if not code or key in seen:
            continue
        seen.add(key)
        out.append(dict(blocker))
    return out


def _dedupe_strings(values: Sequence[Any] | Any) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _safe_stem(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip("-")
    return text[:96] or FINAL_REPORT_STAGE_ID
