"""Pipeline runner facade for server.py and Tauri smoke flows."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Callable, Dict

from src.execution.models import ModelGateway
from src.execution.providers.mock import MockProvider
from src.hitl.plannotator_adapter import HITLAdapter
from src.pipeline.idea_to_council import IdeaToCouncilPipeline, IdeaToCouncilResult
from src.report.chapter_mapper import RoundDigest


ProgressCallback = Callable[[Dict[str, Any]], None]

LAYER_SEQUENCE: tuple[tuple[str, str], ...] = (
    ("L1_market_sizing", "시장 규모"),
    ("L2_competition", "경쟁 환경"),
    ("L3_jtbd", "JTBD"),
    ("L4_finance", "재무 모델"),
    ("L5_risk", "리스크"),
    ("L6_roadmap", "실행 로드맵"),
    ("L7_governance", "거버넌스"),
    ("L8_kpi", "KPI 트리"),
    ("L9_dissent", "반론"),
    ("L10_executive_synthesis", "Executive Synthesis"),
)

STAGE_MAP = {
    "idea_dump": "intake",
    "interview": "interview",
    "targeting": "targeting",
    "research": "research",
    "evidence": "evidence",
    "council": "council",
    "report": "report",
    "vault": "finalize",
    "done": "finalize",
}


def round_result_to_digest(
    round_result: Any,
    layer_id: str,
    chapter_title: str,
) -> RoundDigest:
    """Convert a CouncilSession round record into a report RoundDigest."""
    record = _as_mapping(round_result)
    results = _as_list(record.get("results"))
    first = _as_mapping(results[0]) if results else {}

    key_claim = _first_text(
        record.get("consensus"),
        first.get("analysis"),
        first.get("updated_analysis"),
        first.get("key_points"),
        f"{chapter_title} synthesis",
    )
    body_claims = _body_claims(results, key_claim)
    evidence_ref_ids = _evidence_ref_ids(results)
    confidence = _confidence(record, results)
    framework = _first_text(first.get("framework"), first.get("framework_name"), default="")

    return RoundDigest(
        layer_id=layer_id,
        chapter_title=chapter_title,
        key_claim=key_claim,
        body_claims=body_claims,
        evidence_ref_ids=evidence_ref_ids,
        confidence=confidence,
        framework=framework or None,
    )


def run_pipeline(
    topic: str,
    *,
    progress_callback: ProgressCallback | None = None,
    offline: bool = True,
) -> dict[str, Any]:
    """Run idea -> research -> council -> report -> vault and return report inputs."""
    scratch = Path(tempfile.mkdtemp(prefix="muchanipo-pipeline-"))
    emitted_stages: set[str] = set()

    def handle_progress(event: dict[str, Any]) -> None:
        raw_stage = str(event.get("stage") or "")
        stage = STAGE_MAP.get(raw_stage)
        if stage is None or stage in emitted_stages:
            return
        emitted_stages.add(stage)
        if progress_callback is not None:
            payload = {**event, "stage": stage}
            progress_callback({"event": "stage_started", **payload})
            progress_callback({"event": "stage_completed", **payload})

    provider = MockProvider(response=f"mock council critique for: {topic}")
    pipeline = IdeaToCouncilPipeline(
        hitl_adapter=HITLAdapter(mode="auto_approve" if offline else "markdown"),
        model_gateway=ModelGateway(provider=provider),
        vault_dir=scratch / "vault" / "insights",
        council_log_dir=scratch / "council",
        progress_callback=handle_progress,
    )
    result = pipeline.run(topic)

    rounds = _digests_from_result(result)
    return {
        "rounds": rounds,
        "report_md": result.report_md,
        "report_path": result.vault_path,
        "brief": result.brief,
        "vault_path": result.vault_path,
        "pipeline_result": result,
    }


def _digests_from_result(result: IdeaToCouncilResult) -> list[RoundDigest]:
    rounds = []
    for idx, (layer_id, chapter_title) in enumerate(LAYER_SEQUENCE):
        round_record = result.council.rounds[idx] if idx < len(result.council.rounds) else {}
        rounds.append(round_result_to_digest(round_record, layer_id, chapter_title))
    return rounds


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value is None:
        return []
    return [value]


def _first_text(*values: Any, default: str = "") -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
                if isinstance(item, dict):
                    text = _first_text(item.get("claim"), item.get("text"), item.get("analysis"))
                    if text:
                        return text
    return default


def _body_claims(results: list[Any], key_claim: str) -> list[str]:
    claims: list[str] = []
    seen = {key_claim}
    for raw_result in results:
        result = _as_mapping(raw_result)
        candidates: list[Any] = []
        candidates.extend(_as_list(result.get("key_points")))
        candidates.extend(_as_list(result.get("concerns")))
        candidates.extend(_as_list(result.get("remaining_concerns")))
        candidates.append(result.get("analysis"))
        for candidate in candidates:
            text = _first_text(candidate)
            if text and text not in seen:
                seen.add(text)
                claims.append(text)
    return claims or [key_claim]


def _evidence_ref_ids(results: list[Any]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for raw_result in results:
        result = _as_mapping(raw_result)
        for item in _as_list(result.get("evidence")):
            if isinstance(item, str):
                evidence_id = item
            else:
                ev = _as_mapping(item)
                evidence_id = _first_text(ev.get("id"), ev.get("ref"), ev.get("source"), default="")
            if evidence_id and evidence_id not in seen:
                seen.add(evidence_id)
                ids.append(evidence_id)
    return ids


def _confidence(record: dict[str, Any], results: list[Any]) -> float:
    convergence = _as_mapping(record.get("convergence"))
    for value in (convergence.get("consensus_score"), record.get("confidence")):
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            pass
    values: list[float] = []
    for raw_result in results:
        value = _as_mapping(raw_result).get("confidence")
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            pass
    return sum(values) / len(values) if values else 0.0
