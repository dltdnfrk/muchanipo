from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable

Event = Dict[str, Any]

_TOPIC_DOMAIN_MARKERS = (
    "pathogen",
    "병원체",
    "molecular",
    "diagnostic",
    "diagnostics",
    "분자진단",
    "pcr",
    "lamp",
    "assay",
    "biosensor",
    "kit",
    "키트",
    "korea",
    "korean",
    "한국",
    "국내",
    "channel",
    "regulatory",
    "유통",
    "규제",
)

_GENERIC_ADOPTION_MARKERS = (
    "adoption",
    "cost",
    "compliance",
    "competition",
    "market",
    "willingness to pay",
    "pricing",
    "도입",
    "가격",
    "시장",
)

_SECRETS_RE = re.compile(
    r"(?i)(api[_-]?key|token|authorization|bearer|password|secret)\s*[:=]\s*[^\s,}]+"
)


def redact(text: Any) -> str:
    return _SECRETS_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", str(text))


def load_run_events(path: Path | str) -> list[Event]:
    artifact_path = Path(path)
    events: list[Event] = []
    for line in artifact_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _event_counts(events: Iterable[Event]) -> Counter[str]:
    return Counter(str(event.get("event")) for event in events)


def _accepted_source_events(events: Iterable[Event]) -> list[Event]:
    return [
        event
        for event in events
        if event.get("event") == "research_progress"
        and event.get("status") == "source_evaluated"
        and event.get("accepted") is True
    ]


def _source_evaluation_events(events: Iterable[Event]) -> list[Event]:
    return [
        event
        for event in events
        if event.get("event") == "research_progress" and event.get("status") == "source_evaluated"
    ]


def _rejected_source_events(events: Iterable[Event]) -> list[Event]:
    return [event for event in _source_evaluation_events(events) if event.get("accepted") is False]


def _source_text(event: Event) -> str:
    parts = [
        event.get("source_title"),
        event.get("source_url"),
        event.get("quote"),
        event.get("reason"),
        event.get("source_kind"),
    ]
    return " ".join(str(part or "") for part in parts).casefold()


def _looks_mock_or_generated_rejection(event: Event) -> bool:
    text = _source_text(event)
    return any(marker in text for marker in ("mock", "generated", "empty source", "not live evidence"))


def _looks_cross_domain_generic_adoption(event: Event) -> bool:
    facet_ids = {str(facet).casefold() for facet in event.get("facet_ids") or []}
    if not ({"market", "regional_adoption"} & facet_ids):
        return False
    text = _source_text(event)
    has_generic_adoption = any(marker in text for marker in _GENERIC_ADOPTION_MARKERS)
    has_topic_domain = any(marker in text for marker in _TOPIC_DOMAIN_MARKERS)
    return has_generic_adoption and not has_topic_domain


def _terminal_provider_route(event: Event) -> str:
    explicit = event.get("provider_route")
    if explicit:
        return redact(explicit)
    text = str(event.get("message") or event.get("error") or "")
    providers: list[str] = []
    for provider in ("mimo", "opencode"):
        if re.search(rf"\b{re.escape(provider)}\s*:", text, flags=re.IGNORECASE) and provider not in providers:
            providers.append(provider)
    return ", ".join(providers)


def _facet_summaries(events: Iterable[Event]) -> list[dict[str, Any]]:
    return [
        event.get("facets") or {}
        for event in events
        if event.get("event") == "research_progress" and event.get("status") == "facet_summary"
    ]


def _knowledge_gaps(events: Iterable[Event]) -> list[str]:
    gaps: list[str] = []
    for event in events:
        if event.get("event") == "research_progress" and event.get("status") == "knowledge_gap":
            gaps.append(str(event.get("facet_id") or event.get("gap") or event.get("message") or "unknown"))
    return gaps


def _council_event_key(event: Event) -> tuple[Any, Any, Any, Any]:
    return (
        event.get("round"),
        event.get("layer"),
        event.get("council_stage"),
        event.get("persona"),
    )


def _recovered_council_retry_keys(events: Iterable[Event]) -> set[tuple[Any, Any, Any, Any]]:
    return {
        _council_event_key(event)
        for event in events
        if event.get("event") == "council_provider_call_done"
        and event.get("retry") == "compact_council_prompt"
    }


def _failure_kind(event: Event) -> str:
    explicit = str(event.get("failure_kind") or "")
    if explicit:
        return explicit
    text = f"{event.get('error_class') or ''} {event.get('error') or ''}".casefold()
    if "empty or too-short" in text:
        return "empty_live_output"
    if "timed out" in text:
        return "provider_timeout"
    if any(marker in text for marker in ("401", "403", "unauthorized", "forbidden", "invalid_key")):
        return "auth_or_policy_failure"
    if "mock model result" in text or "placeholder model output" in text:
        return "mock_live_output"
    return "provider_error"


def build_incident_report(events: list[Event], *, artifact_path: Path | str) -> dict[str, Any]:
    counts = _event_counts(events)
    run_started = next((event for event in events if event.get("event") == "run_started"), {})
    terminal_errors = [event for event in events if event.get("event") == "terminal_run_error"]
    search_events = [
        event
        for event in events
        if event.get("event") == "research_progress" and event.get("status") == "searching"
    ]
    research_heartbeats = [
        event
        for event in events
        if event.get("event") == "pipeline_heartbeat"
        and event.get("stage") == "research"
        and event.get("detail") == "searching"
    ]
    last_research_elapsed_sec = max(
        (float(event.get("elapsed_sec") or 0) for event in research_heartbeats),
        default=0.0,
    )
    source_evaluations = _source_evaluation_events(events)
    accepted_sources = _accepted_source_events(events)
    rejected_sources = _rejected_source_events(events)
    council_provider_failures = [
        event
        for event in events
        if event.get("event") in {"council_provider_call_timeout", "council_provider_call_error"}
    ]
    recovered_retry_keys = _recovered_council_retry_keys(events)
    chairman_timeout_fallbacks = [
        event
        for event in events
        if event.get("event") == "council_chairman_timeout_fallback"
    ]
    mock_rejections = [source for source in rejected_sources if _looks_mock_or_generated_rejection(source)]
    suspicious = [source for source in accepted_sources if _looks_cross_domain_generic_adoption(source)]
    gaps = _knowledge_gaps(events)
    facet_summaries = _facet_summaries(events)
    facet_summary = (facet_summaries or [{}])[-1]
    terminal_done = next(
        (
            event
            for event in reversed(events)
            if event.get("event") == "terminal_run_done" and event.get("status") == "completed"
        ),
        {},
    )
    terminal_report_path = Path(str(terminal_done.get("report_path") or "")) if terminal_done else None
    terminal_report_exists = bool(terminal_report_path and terminal_report_path.exists())
    done = counts.get("done", 0) > 0 or bool(terminal_done)
    final_report = next((event for event in reversed(events) if event.get("event") == "final_report"), {})
    if not final_report and terminal_done and terminal_report_exists:
        final_report = terminal_done

    anomalies: list[dict[str, Any]] = []
    for error_event in terminal_errors:
        terminal_impact = (
            "The terminal run failed before emitting run_started/final_report; an aborted done event preserved completion state, but no product report evidence was generated."
            if done
            else "The run failed before emitting run_started/final_report/done, so no product verification evidence was generated."
        )
        anomalies.append(
            {
                "type": "terminal_run_error",
                "category": "runtime",
                "classification": redact(error_event.get("error_type") or "terminal_run_error"),
                "severity": "blocking_product_pass",
                "blocks_product_pass": True,
                "error_class": redact(error_event.get("error_type")),
                "error": redact(error_event.get("message")),
                "provider_route": _terminal_provider_route(error_event),
                "why_it_matters": terminal_impact,
                "next_step": "Repair the terminal blocker (for live verification, configure MIMO or OpenCode Go API live credentials under the routing policy) before retrying product PASS gates.",
            }
        )
    if search_events and not source_evaluations and not facet_summaries:
        anomalies.append(
            {
                "type": "source_search_timeout_or_stall",
                "category": "source_runtime",
                "classification": "search_events_without_source_evaluation_before_incomplete_run",
                "severity": "blocking_product_pass",
                "blocks_product_pass": True,
                "search_query_count": len(search_events),
                "last_research_elapsed_sec": last_research_elapsed_sec,
                "why_it_matters": "The run emitted research search queries but never emitted source_evaluated/facet_summary; failed or aborted completion events must not hide missing source evidence.",
                "next_step": "Add or tighten per-backend source-search timeout/progress guards, then rerun before debugging market/council quality.",
            }
        )
    if search_events and not source_evaluations and facet_summaries:
        anomalies.append(
            {
                "type": "zero_source_evaluations",
                "category": "evidence_coverage",
                "classification": "completed_research_without_source_evaluations",
                "severity": "blocking_product_pass",
                "blocks_product_pass": True,
                "search_query_count": len(search_events),
                "last_research_elapsed_sec": last_research_elapsed_sec,
                "why_it_matters": "Research returned far enough to emit a facet summary, but no run-scoped source_evaluated events were available for evidence gating.",
                "next_step": "Inspect backend traces and source filters; do not treat completed zero-evaluation research as product evidence.",
            }
        )
    if source_evaluations and not accepted_sources:
        all_rejections_are_mock = bool(rejected_sources) and len(mock_rejections) == len(rejected_sources)
        anomalies.append(
            {
                "type": "no_accepted_sources",
                "category": "evidence_coverage",
                "classification": "expected_strict_rejection_of_mock_sources"
                if all_rejections_are_mock
                else "zero_accepted_sources_needs_gate_or_channel_debugging",
                "severity": "blocking_product_pass",
                "blocks_product_pass": True,
                "source_evaluation_count": len(source_evaluations),
                "rejected_source_count": len(rejected_sources),
                "mock_rejection_count": len(mock_rejections),
                "why_it_matters": "No run-scoped accepted evidence sources were available for claim grounding; this blocks product PASS even when final_report/done are true.",
                "next_step": "For mock/offline smoke runs, treat zero accepted sources as expected strict-gate behavior and run a credentialed/live source-channel verification before product PASS; otherwise inspect rejection reasons and routing coverage.",
            }
        )
    for failure in council_provider_failures:
        event_type = str(failure.get("event") or "council_provider_call_error")
        is_timeout = event_type == "council_provider_call_timeout"
        failure_kind = _failure_kind(failure)
        recovered_empty_retry = (
            failure_kind == "empty_live_output"
            and failure.get("retry") == "compact_council_prompt"
            and _council_event_key(failure) in recovered_retry_keys
        )
        anomalies.append(
            {
                "type": event_type,
                "category": "council_runtime",
                "classification": "recovered_empty_output_retry"
                if recovered_empty_retry
                else "provider_call_timeout_during_council"
                if is_timeout
                else "provider_call_error_during_council",
                "severity": "diagnostic_recovered" if recovered_empty_retry else "blocking_product_pass",
                "blocks_product_pass": False if recovered_empty_retry else True,
                "failure_kind": failure_kind,
                "provider_route": redact(failure.get("provider_route")),
                "council_stage": failure.get("council_stage"),
                "round": failure.get("round"),
                "layer": failure.get("layer"),
                "persona": failure.get("persona"),
                "retry": failure.get("retry"),
                "retry_model": redact(failure.get("retry_model")),
                "timeout_sec": failure.get("timeout_sec"),
                "elapsed_sec": failure.get("elapsed_sec"),
                "error_class": redact(failure.get("error_class")),
                "error": redact(failure.get("error")),
                "why_it_matters": "The empty council response was recovered by a compact retry within the allowed provider family."
                if recovered_empty_retry
                else "The council reached a provider call but the call failed before producing any substantive council turn.",
                "next_step": "Keep the retry telemetry visible and continue to require final_report/done plus live provider outputs for product PASS."
                if recovered_empty_retry
                else "Keep MIMO/opencode-go-only routing, reduce council call scope or repair provider execution, then rerun until council_turn/council_round_done are emitted.",
            }
        )
    for fallback in chairman_timeout_fallbacks:
        anomalies.append(
            {
                "type": "council_chairman_timeout_fallback",
                "category": "council_runtime",
                "classification": "chairman_timeout_local_fallback",
                "severity": "blocking_product_pass",
                "blocks_product_pass": True,
                "provider_route": redact(fallback.get("provider") or fallback.get("provider_route")),
                "council_stage": fallback.get("council_stage"),
                "round": fallback.get("round"),
                "layer": fallback.get("layer"),
                "persona": fallback.get("persona"),
                "reason": redact(fallback.get("reason")),
                "why_it_matters": "The chairman synthesis used a deterministic local timeout fallback, so the requested live council provider did not produce the final synthesis.",
                "next_step": "Keep the fallback visible as a product-blocking signal, then rerun with a bounded provider repair or smaller chairman prompt until a live provider emits the chairman turn.",
            }
        )
    if source_evaluations and counts.get("council_turn", 0) == 0 and counts.get("council_round_done", 0) == 0 and not done:
        anomalies.append(
            {
                "type": "council_timeout_or_stall",
                "category": "council_runtime",
                "classification": "no_council_turns_before_incomplete_run",
                "severity": "blocking_product_pass",
                "blocks_product_pass": True,
                "source_evaluation_count": len(source_evaluations),
                "rejected_source_count": len(rejected_sources),
                "mock_rejection_count": len(mock_rejections),
                "why_it_matters": "Source collection emitted evaluations, but no council turns or rounds completed before the run ended without final_report/done.",
                "next_step": "Instrument provider-call timeout/progress and rerun; do not normalize council stall as product completion.",
            }
        )
    for source in suspicious:
        anomalies.append(
            {
                "type": "offtopic_accepted_source",
                "category": "source_gate",
                "classification": "cross_domain_generic_market_source_accepted",
                "severity": "blocking_product_pass",
                "blocks_product_pass": True,
                "source_title": redact(source.get("source_title")),
                "source_url": redact(source.get("source_url")),
                "source_kind": source.get("source_kind"),
                "facet_ids": list(source.get("facet_ids") or []),
                "relevance_score": source.get("relevance_score"),
                "reason": redact(source.get("reason")),
                "why_it_matters": "Generic adoption/cost/compliance wording was treated as market evidence even though the source lacks topic-domain overlap.",
                "next_step": "Keep/extend RED regression for source-side domain overlap before accepting market/adoption evidence.",
            }
        )
    for gap in gaps:
        anomalies.append(
            {
                "type": "knowledge_gap",
                "category": "evidence_coverage",
                "classification": "facet_under_covered_after_completion",
                "severity": "blocking_product_pass",
                "blocks_product_pass": True,
                "facet_id": gap,
                "why_it_matters": "The run completed while this required evidence facet remained under-covered.",
                "next_step": "Route this facet to appropriate source channels and rerun until run-scoped accepted sources satisfy the facet minimum.",
            }
        )
    if not final_report:
        anomalies.append(
            {
                "type": "missing_final_report",
                "category": "completion",
                "classification": "final_report_event_missing",
                "severity": "blocking_product_pass",
                "blocks_product_pass": True,
                "why_it_matters": "The run did not emit a final_report event, so REPORT.md generation cannot be verified from the stdout JSONL source of truth.",
                "next_step": "Debug run termination/report emission before evidence-quality claims.",
            }
        )
    if not done:
        anomalies.append(
            {
                "type": "missing_done",
                "category": "completion",
                "classification": "done_event_missing",
                "severity": "blocking_product_pass",
                "blocks_product_pass": True,
                "why_it_matters": "The run did not emit done, so completion/abort state cannot be treated as successful.",
                "next_step": "Debug run completion/abort state before evidence-quality claims.",
            }
        )

    blocking_anomaly = any(bool(item.get("blocks_product_pass")) for item in anomalies)
    verdict = "FAIL" if blocking_anomaly else "PARTIAL" if gaps else "PASS"
    hypotheses = [
        {
            "hypothesis": "The source gate over-weights generic market/adoption words from the query/provenance and does not require source-side domain overlap for market/adoption facets.",
            "status": "supported" if suspicious else "unproven",
            "evidence": [
                "Accepted market source lacks pathogen/diagnostic/Korea channel/regulatory markers.",
                "Facet summary still reports market/regional_adoption gaps after completion.",
            ],
        },
        {
            "hypothesis": "Academic APIs can satisfy scientific/field-validation evidence but are weak for Korea-specific WTP/channel/regulatory adoption evidence; a government/statistics/web channel may be needed.",
            "status": "supported" if "regional_adoption" in gaps else "unproven",
            "evidence": [f"knowledge_gaps={gaps}", f"facet_summary={facet_summary}"],
        },
    ]

    approach = [
        {
            "phase": "OBSERVE",
            "action": "Persist run-scoped stdout JSONL, then inspect run_started, search queries, source_evaluated, facet_summary, knowledge_gap, council, final_report, and done events.",
        },
        {
            "phase": "HYPOTHESIZE",
            "action": "Compare accepted source titles/facets/relevance scores against the original topic anchor to identify whether query budget, topic anchoring, source channels, or source gates are failing.",
        },
        {
            "phase": "RED",
            "action": "Encode the observed bad accepted source as a regression test before changing source relevance logic.",
        },
        {
            "phase": "GREEN",
            "action": "Tighten source-side market/adoption facet acceptance so generic adoption/cost/compliance sources cannot pass without topic-domain overlap.",
        },
        {
            "phase": "VERIFY",
            "action": "Run targeted tests, broader research tests, app build/Rust tests, then a new live run and compare the generated incident report.",
        },
    ]

    return {
        "artifact_path": str(artifact_path),
        "verdict": verdict,
        "run": {
            "topic": redact(run_started.get("topic") or (terminal_errors[-1].get("topic") if terminal_errors else None)),
            "app_run_id": run_started.get("app_run_id"),
            "backend_run_id": run_started.get("run_id"),
            "offline": run_started.get("offline"),
            "source_research": run_started.get("source_research"),
            "depth": run_started.get("depth"),
            "report_path": redact(final_report.get("report_path")),
        },
        "observations": {
            "event_count": len(events),
            "event_counts": dict(counts),
            "search_query_count": len(search_events),
            "last_research_elapsed_sec": last_research_elapsed_sec,
            "accepted_source_count": len(accepted_sources),
            "source_evaluation_count": len(source_evaluations),
            "rejected_source_count": len(rejected_sources),
            "mock_rejection_count": len(mock_rejections),
            "accepted_titles": [redact(source.get("source_title")) for source in accepted_sources],
            "facet_summary": facet_summary,
            "knowledge_gaps": gaps,
            "council_round_done": counts.get("council_round_done", 0),
            "council_turn": counts.get("council_turn", 0),
            "final_report": bool(final_report),
            "done": done,
        },
        "anomalies": anomalies,
        "hypotheses": hypotheses,
        "approach": approach,
        "next_actions": [
            "Add/adjust RED regression with the exact live artifact payload for the off-topic accepted source.",
            "Reject market/adoption facet sources that only match generic adoption/economics terms without source-side topic-domain overlap.",
            "Add an incident-report check to every goals loop so future runs submit evidence, hypotheses, and the next debugging step instead of only status counters.",
            "If Korea adoption remains a gap after source-gate fix, add or route to government/statistics/Korean market source channels rather than accepting unrelated market papers.",
        ],
    }


def _markdown_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- none"


def render_incident_report(report: dict[str, Any]) -> str:
    run = report["run"]
    observations = report["observations"]
    lines = [
        "# Muchanipo 장애 보고서",
        "",
        f"- Verdict: **{report['verdict']}**",
        f"- Topic: {run.get('topic')}",
        f"- Artifact: `{report['artifact_path']}`",
        f"- Report: `{run.get('report_path')}`",
        "",
        "## 관측 시스템",
        "",
        "이번 시스템은 run-scoped stdout JSONL을 단일 진실 공급원으로 삼아 다음 이벤트를 자동 관측한다.",
        "",
        "- `run_started`: topic/app_run_id/backend_run_id/source_research/offline/depth 확인",
        "- `research_progress`: searching/source_evaluated/facet_summary/knowledge_gap 확인",
        "- `council_*`: MiMo council round/turn/persona token 확인",
        "- `report_chunk`/`final_report`/`done`: 최종 산출물 생성 확인",
        "",
        "## 관측 결과",
        "",
        f"- event_count: {observations['event_count']}",
        f"- search_query_count: {observations.get('search_query_count', 0)}",
        f"- last_research_elapsed_sec: {observations.get('last_research_elapsed_sec', 0.0)}",
        f"- accepted_source_count: {observations['accepted_source_count']}",
        f"- source_evaluation_count: {observations.get('source_evaluation_count', 0)}",
        f"- rejected_source_count: {observations.get('rejected_source_count', 0)}",
        f"- mock_rejection_count: {observations.get('mock_rejection_count', 0)}",
        f"- council_round_done: {observations['council_round_done']}",
        f"- council_turn: {observations['council_turn']}",
        f"- final_report: {observations['final_report']}",
        f"- done: {observations['done']}",
        f"- knowledge_gaps: {', '.join(observations['knowledge_gaps']) or 'none'}",
        "",
        "### Accepted Sources",
        "",
        _markdown_list(observations["accepted_titles"]),
        "",
        "## 이상 징후",
        "",
    ]
    if report["anomalies"]:
        for anomaly in report["anomalies"]:
            lines.extend(
                [
                    f"### {anomaly['type']}",
                    "",
                    f"- category: {anomaly.get('category', '')}",
                    f"- classification: {anomaly.get('classification', '')}",
                    f"- severity: {anomaly.get('severity', '')}",
                    f"- blocks_product_pass: {anomaly.get('blocks_product_pass', '')}",
                    f"- source_title: {anomaly.get('source_title', '')}",
                    f"- source_url: {anomaly.get('source_url', '')}",
                    f"- facet_ids: {anomaly.get('facet_ids', anomaly.get('facet_id', ''))}",
                    f"- source_evaluation_count: {anomaly.get('source_evaluation_count', '')}",
                    f"- search_query_count: {anomaly.get('search_query_count', '')}",
                    f"- last_research_elapsed_sec: {anomaly.get('last_research_elapsed_sec', '')}",
                    f"- provider_route: {anomaly.get('provider_route', '')}",
                    f"- council_stage: {anomaly.get('council_stage', '')}",
                    f"- failure_kind: {anomaly.get('failure_kind', '')}",
                    f"- retry: {anomaly.get('retry', '')}",
                    f"- retry_model: {anomaly.get('retry_model', '')}",
                    f"- timeout_sec: {anomaly.get('timeout_sec', '')}",
                    f"- elapsed_sec: {anomaly.get('elapsed_sec', '')}",
                    f"- error_class: {anomaly.get('error_class', '')}",
                    f"- error: {anomaly.get('error', '')}",
                    f"- rejected_source_count: {anomaly.get('rejected_source_count', '')}",
                    f"- mock_rejection_count: {anomaly.get('mock_rejection_count', '')}",
                    f"- relevance_score: {anomaly.get('relevance_score', '')}",
                    f"- reason: {anomaly.get('reason', '')}",
                    f"- impact: {anomaly.get('why_it_matters', '')}",
                    f"- next_step: {anomaly.get('next_step', '')}",
                    "",
                ]
            )
    else:
        lines.extend(["- none", ""])

    lines.extend(["## 가설과 접근", ""])
    for item in report["hypotheses"]:
        lines.extend(
            [
                f"### {item['status']}: {item['hypothesis']}",
                "",
                _markdown_list([redact(evidence) for evidence in item.get("evidence", [])]),
                "",
            ]
        )

    lines.extend(["## 문제 해결 접근 로그", ""])
    for step in report["approach"]:
        lines.append(f"- **{step['phase']}**: {step['action']}")
    lines.extend(["", "## 다음 조치", "", _markdown_list(report["next_actions"]), ""])
    return "\n".join(lines)


def write_incident_report(report: dict[str, Any], output_path: Path | str) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_incident_report(report), encoding="utf-8")
    return path
