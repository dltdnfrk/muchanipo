"""Karpathy Autoresearch loop adapted for Muchanipo source collection.

The vendored upstream project is a tiny autonomous experiment loop: read
``program.md``, modify exactly one experiment surface, run a fixed evaluator,
record a TSV row, keep only metric improvements, and discard the rest.

Muchanipo cannot safely run upstream's git-reset loop against the user's repo,
and the ML target (``train.py`` / ``val_bpb``) is not the product's research
target. This module keeps the actual loop mechanics but adapts the experiment
surface to research-query candidates and the fixed metric to source-grounding
gap score. All writes go to an ignored scratch run directory.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from src.evidence.artifact import EvidenceRef, Finding

from .depth import ResearchDepthProfile
from .planner import ResearchPlan, source_route_for_query


UPSTREAM_REVISION = "228791fb499afffb54b46200aca536f79142f117"
RESULTS_HEADER = "commit\tval_bpb\tmemory_gb\tstatus\tdescription\n"
METRIC_NAME = "source_grounding_gap_score"
METRIC_DIRECTION = "lower_is_better"


class SourceAuditViolation(RuntimeError):
    """Raised when strict research depth refuses weak/off-topic sources."""


@dataclass(frozen=True)
class ResearchFacet:
    id: str
    label: str
    required_source_kinds: tuple[str, ...]
    min_accepted_sources: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "required_source_kinds": list(self.required_source_kinds),
            "min_accepted_sources": self.min_accepted_sources,
        }


@dataclass(frozen=True)
class SourceEvaluation:
    source_id: str
    source_title: str | None
    source_url: str | None
    source_grade: str
    source_kind: str
    accepted: bool
    facet_ids: tuple[str, ...]
    relevance_score: float
    reason: str
    relevance_basis: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_title": self.source_title,
            "source_url": self.source_url,
            "source_grade": self.source_grade,
            "source_kind": self.source_kind,
            "accepted": self.accepted,
            "facet_ids": list(self.facet_ids),
            "relevance_score": self.relevance_score,
            "reason": self.reason,
            "relevance_basis": dict(self.relevance_basis),
        }


@dataclass(frozen=True)
class KnowledgeGap:
    facet_id: str
    message: str
    required_source_kinds: tuple[str, ...]
    accepted_count: int
    min_accepted_sources: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "facet_id": self.facet_id,
            "message": self.message,
            "required_source_kinds": list(self.required_source_kinds),
            "accepted_count": self.accepted_count,
            "min_accepted_sources": self.min_accepted_sources,
        }


@dataclass(frozen=True)
class ResearchQualityAudit:
    facets: tuple[ResearchFacet, ...]
    source_evaluations: tuple[SourceEvaluation, ...]
    gaps: tuple[KnowledgeGap, ...]

    def to_dict(self) -> dict[str, Any]:
        accepted_by_facet = {
            facet.id: sum(1 for item in self.source_evaluations if item.accepted and facet.id in item.facet_ids)
            for facet in self.facets
        }
        return {
            "facets": {
                facet.id: {
                    **facet.to_dict(),
                    "accepted_count": accepted_by_facet.get(facet.id, 0),
                }
                for facet in self.facets
            },
            "source_evaluations": [item.to_dict() for item in self.source_evaluations],
            "gaps": [gap.to_dict() for gap in self.gaps],
        }


@dataclass(frozen=True)
class AutoresearchExperiment:
    iteration: int
    candidate_id: str
    metric: float
    evidence_count: int
    trusted_count: int
    status: str
    description: str
    query_count: int
    hypothesis: str = ""
    code_test_change: str = "research_plan_query_mutation"
    query_plan_mutation: dict[str, Any] = field(default_factory=dict)
    metrics_before: dict[str, Any] = field(default_factory=dict)
    metrics_after: dict[str, Any] = field(default_factory=dict)
    decision: str = ""
    next_slice: str = ""
    quality_audit: ResearchQualityAudit | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "iteration": self.iteration,
            "candidate_id": self.candidate_id,
            "metric": self.metric,
            "evidence_count": self.evidence_count,
            "trusted_count": self.trusted_count,
            "status": self.status,
            "description": self.description,
            "query_count": self.query_count,
            "hypothesis": self.hypothesis,
            "code_test_change": self.code_test_change,
            "query_plan_mutation": dict(self.query_plan_mutation),
            "metrics_before": dict(self.metrics_before),
            "metrics_after": dict(self.metrics_after),
            "decision": self.decision or self.status,
            "next_slice": self.next_slice,
        }
        if self.quality_audit is not None:
            payload["quality_audit"] = self.quality_audit.to_dict()
        if self.error:
            payload["error"] = self.error
        return payload


@dataclass(frozen=True)
class AutoresearchLoopResult:
    run_id: str
    work_dir: str
    program_path: str
    results_path: str
    metric_name: str
    metric_direction: str
    iteration_budget: int
    experiments: tuple[AutoresearchExperiment, ...]
    best_iteration: int
    retained_iteration_count: int
    discarded_iteration_count: int
    crashed_iteration_count: int
    source_revision: str = UPSTREAM_REVISION
    source_path: str = "third_party/karpathy-autoresearch"
    adaptation_boundary: str = "scratch_query_plan_loop_no_repo_git_reset"

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "work_dir": self.work_dir,
            "program_path": self.program_path,
            "results_path": self.results_path,
            "metric_name": self.metric_name,
            "metric_direction": self.metric_direction,
            "iteration_budget": self.iteration_budget,
            "experiments": [experiment.to_dict() for experiment in self.experiments],
            "best_iteration": self.best_iteration,
            "retained_iteration_count": self.retained_iteration_count,
            "discarded_iteration_count": self.discarded_iteration_count,
            "crashed_iteration_count": self.crashed_iteration_count,
            "source_revision": self.source_revision,
            "source_path": self.source_path,
            "adaptation_boundary": self.adaptation_boundary,
        }


@dataclass(frozen=True)
class _CandidatePlan:
    candidate_id: str
    description: str
    plan: ResearchPlan


def _experiment_hypothesis(candidate: _CandidatePlan) -> str:
    return (
        f"{candidate.description} will reduce {METRIC_NAME} "
        "by changing only the bounded research-plan query surface"
    )


def _query_plan_mutation(base_plan: ResearchPlan, candidate: _CandidatePlan) -> dict[str, Any]:
    base_queries = list(getattr(base_plan, "queries", ()) or ())
    candidate_queries = list(getattr(candidate.plan, "queries", ()) or ())
    changed = [query for query in candidate_queries if query not in base_queries]
    removed = [query for query in base_queries if query not in candidate_queries]
    mutation_type = "baseline" if not changed and not removed else "bounded_query_suffix_mutation"
    return {
        "surface": "research_plan.queries",
        "mutation_type": mutation_type,
        "candidate_id": candidate.candidate_id,
        "description": candidate.description,
        "base_query_count": len(base_queries),
        "candidate_query_count": len(candidate_queries),
        "changed_query_count": len(changed),
        "removed_query_count": len(removed),
    }


def _experiment_metrics_before(*, best_metric: float, best_iteration: int) -> dict[str, Any]:
    return {
        "metric_name": METRIC_NAME,
        "metric_direction": METRIC_DIRECTION,
        "best_metric": None if best_metric == float("inf") else best_metric,
        "best_iteration": best_iteration,
    }


def _experiment_metrics_after(
    *,
    metric: float,
    evidence_count: int,
    trusted_count: int,
    query_count: int,
    gap_count: int | None,
) -> dict[str, Any]:
    return {
        "metric_name": METRIC_NAME,
        "metric_direction": METRIC_DIRECTION,
        "metric": metric,
        "evidence_count": evidence_count,
        "trusted_count": trusted_count,
        "query_count": query_count,
        "gap_count": gap_count,
    }


def _next_slice_for_decision(status: str) -> str:
    if status == "keep":
        return "promote_candidate_and_continue_next_bounded_query_plan_mutation"
    if status == "discard":
        return "retain_previous_best_and_try_next_bounded_query_plan_mutation"
    return "discard_failed_candidate_and_try_next_bounded_query_plan_mutation"


class KarpathyAutoresearchRunner:
    """Run source research through a keep/discard experiment loop.

    The wrapped runner owns actual source collection. This class owns the
    autonomous experiment protocol and exposes the same ``run(plan)`` surface
    so existing pipeline code can keep calling a research runner.
    """

    def __init__(
        self,
        base_runner: Any,
        *,
        iteration_budget: int,
        work_root: Path | str | None = None,
        source_dir: Path | str | None = None,
        run_tag: str | None = None,
    ) -> None:
        self.base_runner = base_runner
        self.iteration_budget = max(1, int(iteration_budget))
        repo_root = Path(__file__).resolve().parents[2]
        self.source_dir = Path(source_dir) if source_dir is not None else repo_root / "third_party/karpathy-autoresearch"
        env_work_root = os.environ.get("MUCHANIPO_AUTORESEARCH_WORKDIR", "").strip()
        if work_root is None and env_work_root:
            work_root = env_work_root
        self.work_root = Path(work_root) if work_root is not None else repo_root / ".omc/autoresearch/runs"
        self.run_tag = run_tag
        self.last_backend_trace: list[dict[str, Any]] = []
        self.last_loop_result: AutoresearchLoopResult | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base_runner, name)

    def run(self, plan: ResearchPlan) -> list[Finding]:
        self.last_backend_trace = []
        self.last_loop_result = None
        run_id = self._run_id(plan)
        work_dir = self.work_root / run_id
        work_dir.mkdir(parents=True, exist_ok=True)
        program_path = self._write_program(work_dir, plan)
        results_path = work_dir / "results.tsv"
        if not results_path.exists():
            results_path.write_text(RESULTS_HEADER, encoding="utf-8")

        best_metric = float("inf")
        best_findings: list[Finding] = []
        best_iteration = 0
        experiments: list[AutoresearchExperiment] = []

        for iteration, candidate in enumerate(self._candidate_plans(plan), start=1):
            if iteration > self.iteration_budget:
                break
            metrics_before = _experiment_metrics_before(best_metric=best_metric, best_iteration=best_iteration)
            mutation = _query_plan_mutation(plan, candidate)
            try:
                findings = list(self.base_runner.run(candidate.plan))
                self._capture_backend_trace(iteration, candidate)
                quality_audit = build_research_quality_audit(findings, candidate.plan)
                metric = _source_grounding_gap_score(findings, plan=candidate.plan, audit=quality_audit)
                evidence_refs = _dedupe_evidence_refs([ref for finding in findings for ref in finding.support])
                trusted_count = sum(1 for ref in evidence_refs if ref.source_grade in {"A", "B"})
                improved = iteration == 1 or metric < best_metric
                status = "keep" if improved else "discard"
                if improved:
                    best_metric = metric
                    best_findings = findings
                    best_iteration = iteration
                    _mark_autoresearch_provenance(
                        best_findings,
                        iteration=iteration,
                        candidate_id=candidate.candidate_id,
                        metric=metric,
                    )
                experiment = AutoresearchExperiment(
                    iteration=iteration,
                    candidate_id=candidate.candidate_id,
                    metric=metric,
                    evidence_count=len(evidence_refs),
                    trusted_count=trusted_count,
                    status=status,
                    description=candidate.description,
                    query_count=len(candidate.plan.queries),
                    hypothesis=_experiment_hypothesis(candidate),
                    code_test_change="research_plan_query_mutation",
                    query_plan_mutation=mutation,
                    metrics_before=metrics_before,
                    metrics_after=_experiment_metrics_after(
                        metric=metric,
                        evidence_count=len(evidence_refs),
                        trusted_count=trusted_count,
                        query_count=len(candidate.plan.queries),
                        gap_count=len(quality_audit.gaps),
                    ),
                    decision=status,
                    next_slice=_next_slice_for_decision(status),
                    quality_audit=quality_audit,
                )
            except Exception as exc:  # noqa: BLE001
                self._capture_backend_trace(iteration, candidate)
                experiment = AutoresearchExperiment(
                    iteration=iteration,
                    candidate_id=candidate.candidate_id,
                    metric=1.0,
                    evidence_count=0,
                    trusted_count=0,
                    status="crash",
                    description=candidate.description,
                    query_count=len(candidate.plan.queries),
                    hypothesis=_experiment_hypothesis(candidate),
                    code_test_change="research_plan_query_mutation",
                    query_plan_mutation=mutation,
                    metrics_before=metrics_before,
                    metrics_after=_experiment_metrics_after(
                        metric=1.0,
                        evidence_count=0,
                        trusted_count=0,
                        query_count=len(candidate.plan.queries),
                        gap_count=None,
                    ),
                    decision="discard",
                    next_slice="discard_failed_candidate_and_try_next_bounded_query_plan_mutation",
                    error=str(exc).splitlines()[0][:240],
                )
                findings = []

            experiments.append(experiment)
            self._write_iteration_artifact(work_dir, experiment, candidate, findings)
            self._append_results_row(results_path, experiment)

        retained = sum(1 for item in experiments if item.status == "keep")
        discarded = sum(1 for item in experiments if item.status == "discard")
        crashed = sum(1 for item in experiments if item.status == "crash")
        self.last_loop_result = AutoresearchLoopResult(
            run_id=run_id,
            work_dir=str(work_dir),
            program_path=str(program_path),
            results_path=str(results_path),
            metric_name=METRIC_NAME,
            metric_direction=METRIC_DIRECTION,
            iteration_budget=self.iteration_budget,
            experiments=tuple(experiments),
            best_iteration=best_iteration,
            retained_iteration_count=retained,
            discarded_iteration_count=discarded,
            crashed_iteration_count=crashed,
            source_path=_display_source_path(self.source_dir),
        )
        return best_findings

    def _run_id(self, plan: ResearchPlan) -> str:
        if self.run_tag:
            return self.run_tag
        digest = hashlib.sha1("|".join(plan.queries).encode("utf-8")).hexdigest()[:10]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        brief = _safe_slug(plan.brief_id)[:36] or "brief"
        return f"{stamp}-{brief}-{digest}"

    def _write_program(self, work_dir: Path, plan: ResearchPlan) -> Path:
        upstream_program = self.source_dir / "program.md"
        upstream_text = upstream_program.read_text(encoding="utf-8") if upstream_program.exists() else ""
        adapted = "\n".join(
            [
                "# Muchanipo Karpathy Autoresearch Program",
                "",
                "This run is a faithful local adaptation of karpathy/autoresearch.",
                "The fixed experiment surface is the ResearchPlan query set, not train.py.",
                "The fixed evaluator is source_grounding_gap_score; lower is better.",
                "The loop writes results.tsv, keeps strict metric improvements, and discards non-improvements.",
                "Repository git reset/force-revert is intentionally replaced with scratch-run retention.",
                "",
                "## Brief",
                f"- brief_id: {plan.brief_id}",
                f"- query_count: {len(plan.queries)}",
                "",
                "## Starting Queries",
                *[f"- {query}" for query in plan.queries],
                "",
                "## Upstream program.md",
                upstream_text.rstrip(),
                "",
            ]
        )
        program_path = work_dir / "program.md"
        program_path.write_text(adapted, encoding="utf-8")
        return program_path

    def _candidate_plans(self, plan: ResearchPlan) -> list[_CandidatePlan]:
        candidates = [
            _CandidatePlan(
                candidate_id=_candidate_id("baseline", plan.queries),
                description="baseline source query plan",
                plan=plan,
            )
        ]
        variants = [
            ("source-grade hardening", "official statistics DOI peer reviewed source evidence"),
            ("counter-evidence hardening", "limitations constraints counter evidence failure cases"),
        ]
        query_text = " ".join(plan.queries).casefold()
        if _has_market_intent(query_text):
            market_suffix = "pricing adoption willingness to pay distribution"
            if "korea" in query_text or "한국" in query_text or "국내" in query_text:
                market_suffix = f"{market_suffix} Korea"
            variants.append(("adoption economics hardening", market_suffix))
        if _has_field_validation_intent(query_text):
            variants.append(("field-validation hardening", "field validation sensitivity specificity accuracy"))
        variants = tuple(variants)
        for description, suffix in variants:
            mutated_queries = [_mutate_query(query, suffix) for query in plan.queries]
            mutated = ResearchPlan(
                brief_id=plan.brief_id,
                queries=_dedupe_strings(mutated_queries),
                evidence_targets=list(plan.evidence_targets),
                expected_deliverables=list(plan.expected_deliverables),
                stop_conditions=list(plan.stop_conditions),
                risk_notes=list(plan.risk_notes),
                collection_rules=[
                    *plan.collection_rules,
                    "karpathy-autoresearch candidate: keep only if source_grounding_gap_score improves",
                ],
                topic_anchor=plan.topic_anchor,
                query_routes=[source_route_for_query(query) for query in _dedupe_strings(mutated_queries)],
            )
            candidates.append(
                _CandidatePlan(
                    candidate_id=_candidate_id(description, mutated.queries),
                    description=description,
                    plan=mutated,
                )
            )
        return candidates

    def _capture_backend_trace(self, iteration: int, candidate: _CandidatePlan) -> None:
        trace = getattr(self.base_runner, "last_backend_trace", []) or []
        for item in trace:
            if not isinstance(item, dict):
                continue
            self.last_backend_trace.append(
                {
                    **item,
                    "autoresearch_iteration": iteration,
                    "autoresearch_candidate_id": candidate.candidate_id,
                    "autoresearch_candidate_description": candidate.description,
                }
            )

    def _write_iteration_artifact(
        self,
        work_dir: Path,
        experiment: AutoresearchExperiment,
        candidate: _CandidatePlan,
        findings: list[Finding],
    ) -> None:
        payload = {
            "experiment": experiment.to_dict(),
            "queries": list(candidate.plan.queries),
            "finding_count": len(findings),
            "evidence_ids": [
                ref.id
                for finding in findings
                for ref in finding.support
            ],
        }
        path = work_dir / f"iteration-{experiment.iteration:03d}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _append_results_row(self, results_path: Path, experiment: AutoresearchExperiment) -> None:
        # Keep upstream TSV columns. ``val_bpb`` carries Muchanipo's adapted
        # lower-is-better source gap metric; memory is not meaningful here.
        row = (
            f"{experiment.candidate_id[:7]}\t"
            f"{experiment.metric:.6f}\t"
            "0.0\t"
            f"{experiment.status}\t"
            f"{_tsv_safe(experiment.description)}\n"
        )
        with results_path.open("a", encoding="utf-8") as handle:
            handle.write(row)


def iteration_budget_for_profile(profile: ResearchDepthProfile, *, source_research: bool = False) -> int:
    override = os.environ.get("MUCHANIPO_AUTORESEARCH_ITERATIONS", "").strip()
    if override:
        try:
            return max(1, min(8, int(override)))
        except ValueError:
            pass
    budget = {
        "shallow": 1,
        "deep": 2,
        "max": 4,
    }.get(profile.name, 2)
    if source_research:
        budget = max(2, budget)
    return budget


def enforce_source_audit_gate(audit: ResearchQualityAudit, *, depth: str) -> dict[str, Any]:
    """Enforce pre-council source quality for strict/max-depth research.

    `superdeep` is intentionally harsher than `max`: no facet gaps, no accepted
    generated/mock sources, and a high accepted-source floor. This prevents a
    large persona council from amplifying contaminated evidence.
    """

    normalized_depth = str(depth or "").casefold()
    strict = normalized_depth in {"max", "superdeep"}
    accepted = [item for item in audit.source_evaluations if item.accepted]
    rejected = [item for item in audit.source_evaluations if not item.accepted]
    generated_accepted = [
        item for item in accepted if item.source_kind in {"mock", "empty", "generated"}
    ]
    min_accepted = 6 if normalized_depth == "superdeep" else 3
    allowed_gaps = 0 if normalized_depth == "superdeep" else 1
    passed = True
    reasons: list[str] = []
    if len(accepted) < min_accepted:
        passed = False
        reasons.append(f"accepted_source_count {len(accepted)} < {min_accepted}")
    if len(audit.gaps) > allowed_gaps:
        passed = False
        reasons.append(f"gap_count {len(audit.gaps)} > {allowed_gaps}")
    if generated_accepted:
        passed = False
        reasons.append("generated/mock sources cannot be accepted")
    summary = {
        "passed": passed,
        "depth": normalized_depth,
        "accepted_source_count": len(accepted),
        "rejected_source_count": len(rejected),
        "gap_count": len(audit.gaps),
        "min_accepted_sources": min_accepted,
        "allowed_gap_count": allowed_gaps,
        "reasons": reasons,
    }
    if strict and not passed:
        raise SourceAuditViolation("source audit gate failed: " + "; ".join(reasons))
    return summary


def _source_grounding_gap_score(
    findings: list[Finding],
    *,
    plan: ResearchPlan | None = None,
    audit: ResearchQualityAudit | None = None,
) -> float:
    refs = _dedupe_evidence_refs([ref for finding in findings for ref in finding.support])
    if not findings or not refs:
        return 1.0
    if audit is None:
        audit = build_research_quality_audit(findings, plan)
    off_topic = sum(1 for item in audit.source_evaluations if not item.accepted)
    relevant_refs = [ref for ref in refs if _ref_is_relevant_to_plan(ref, plan)]
    trusted = sum(1 for ref in relevant_refs if ref.source_grade in {"A", "B"})
    weak = sum(1 for ref in relevant_refs if ref.source_grade in {"C", "D"})
    generated = sum(1 for ref in refs if _is_generated_ref(ref))
    unsupported = sum(1 for finding in findings if not finding.support)
    source_kinds = {
        evaluation.source_kind
        for evaluation in audit.source_evaluations
        if evaluation.accepted and evaluation.source_kind not in {"mock", "empty", "generated"}
    }
    target_trusted = min(6, max(3, len(findings)))
    facet_gap = sum(
        max(0, gap.min_accepted_sources - gap.accepted_count) / max(1, gap.min_accepted_sources)
        for gap in audit.gaps
    )
    coverage_gap = max(0, target_trusted - trusted) / target_trusted
    penalty = weak * 0.06 + generated * 0.25 + unsupported * 0.2 + off_topic * 0.35 + facet_gap * 0.08
    diversity_credit = min(0.18, max(0, len(source_kinds) - 1) * 0.06)
    return round(max(0.0, min(1.0, coverage_gap + penalty - diversity_credit)), 6)


def _mark_autoresearch_provenance(
    findings: list[Finding],
    *,
    iteration: int,
    candidate_id: str,
    metric: float,
) -> None:
    for finding in findings:
        for ref in finding.support:
            provenance = dict(ref.provenance or {})
            raw_metadata = provenance.get("metadata")
            metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
            metadata["karpathy_autoresearch"] = {
                "iteration": iteration,
                "candidate_id": candidate_id,
                "metric_name": METRIC_NAME,
                "metric": metric,
                "metric_direction": METRIC_DIRECTION,
                "source_revision": UPSTREAM_REVISION,
            }
            provenance["metadata"] = metadata
            ref.provenance = provenance


def build_research_quality_audit(findings: list[Finding], plan: ResearchPlan | None) -> ResearchQualityAudit:
    facets = _infer_research_facets(plan)
    refs = _dedupe_evidence_refs([ref for finding in findings for ref in finding.support])
    evaluations = tuple(_evaluate_source_ref(ref, facets=facets, plan=plan) for ref in refs)
    gaps: list[KnowledgeGap] = []
    for facet in facets:
        accepted_count = sum(
            1
            for item in evaluations
            if item.accepted and facet.id in item.facet_ids
        )
        if accepted_count < facet.min_accepted_sources:
            gaps.append(
                KnowledgeGap(
                    facet_id=facet.id,
                    message=_gap_message_for_facet(facet),
                    required_source_kinds=facet.required_source_kinds,
                    accepted_count=accepted_count,
                    min_accepted_sources=facet.min_accepted_sources,
                )
            )
    return ResearchQualityAudit(
        facets=tuple(facets),
        source_evaluations=evaluations,
        gaps=tuple(gaps),
    )


def _infer_research_facets(plan: ResearchPlan | None) -> list[ResearchFacet]:
    text = " ".join(getattr(plan, "queries", []) or []).casefold()
    facets: list[ResearchFacet] = []
    if _has_scientific_intent(text) or _has_field_validation_intent(text):
        facets.append(
            ResearchFacet(
                id="scientific",
                label="Scientific / technical evidence",
                required_source_kinds=("paper", "doi", "review", "academic"),
                min_accepted_sources=3,
            )
        )
    if _has_market_intent(text):
        facets.append(
            ResearchFacet(
                id="market",
                label="Market / pricing / adoption evidence",
                required_source_kinds=("statistics", "industry_report", "government", "pricing_page"),
                min_accepted_sources=3,
            )
        )
    if _has_regional_adoption_intent(text):
        facets.append(
            ResearchFacet(
                id="regional_adoption",
                label="Regional market / channel / regulatory adoption evidence",
                required_source_kinds=("government", "statistics", "industry_report", "field_study", "web"),
                min_accepted_sources=2,
            )
        )
    if _has_field_validation_intent(text):
        facets.append(
            ResearchFacet(
                id="field_validation",
                label="Field validation / performance evidence",
                required_source_kinds=("paper", "doi", "field_study", "trial", "benchmark"),
                min_accepted_sources=2,
            )
        )
    if not facets:
        facets.append(
            ResearchFacet(
                id="general",
                label="General topic evidence",
                required_source_kinds=("web", "paper", "doi", "review", "documentation"),
                min_accepted_sources=2,
            )
        )
    return facets


def _evaluate_source_ref(
    ref: EvidenceRef,
    *,
    facets: list[ResearchFacet],
    plan: ResearchPlan | None,
) -> SourceEvaluation:
    source_kind = _source_kind_for_ref(ref)
    relevance_basis = _source_relevance_basis(ref, plan)
    relevant = _source_meets_topic_relevance(ref, plan, relevance_basis=relevance_basis)
    generated = _is_generated_ref(ref)
    relevance_score = round(float(relevance_basis.get("relevance_score") or 0.0), 3)
    search_result_echo = _is_search_result_echo_ref(ref, plan)
    facet_ids = tuple(
        facet.id
        for facet in facets
        if not search_result_echo
        and _source_satisfies_facet(ref, facet, plan=plan, source_kind=source_kind, relevance_score=relevance_score)
    )
    accepted = bool(
        relevant
        and relevance_score >= _minimum_relevance_score(plan)
        and not generated
        and not search_result_echo
        and ref.source_grade in {"A", "B", "C"}
        and facet_ids
    )
    if generated:
        reason = "rejected: generated/mock/empty source is not live evidence"
    elif search_result_echo:
        reason = "rejected: search-result echo or landing page keyword match is not source evidence"
    elif not relevance_basis.get("topic_anchor_present", True):
        reason = "rejected: missing topic_anchor relevance basis"
    elif not relevant:
        reason = "rejected: source text does not overlap with topic-specific plan terms"
    elif relevance_score < _minimum_relevance_score(plan):
        reason = f"rejected: relevance score {relevance_score} below threshold {_minimum_relevance_score(plan)}"
    elif not facet_ids:
        reason = f"rejected: source kind {source_kind!r} does not satisfy any required facet"
    elif ref.source_grade not in {"A", "B", "C"}:
        reason = f"rejected: source grade {ref.source_grade} is below acceptance threshold"
    else:
        reason = f"accepted for facets: {', '.join(facet_ids)}"
    return SourceEvaluation(
        source_id=ref.id,
        source_title=ref.source_title,
        source_url=ref.source_url,
        source_grade=ref.source_grade,
        source_kind=source_kind,
        accepted=accepted,
        facet_ids=facet_ids,
        relevance_score=relevance_score,
        reason=reason,
        relevance_basis=relevance_basis,
    )


def _source_kind_for_ref(ref: EvidenceRef) -> str:
    provenance = ref.provenance or {}
    metadata = provenance.get("metadata") if isinstance(provenance.get("metadata"), dict) else {}
    raw_kind = str(provenance.get("kind") or metadata.get("kind") or "").casefold()
    url = str(ref.source_url or metadata.get("source") or "").casefold()
    title = str(ref.source_title or "").casefold()
    text = f"{raw_kind} {url} {title} {ref.quote or ''}".casefold()
    if raw_kind in {"mock", "empty", "generated", "synthetic"}:
        return "generated" if raw_kind == "synthetic" else raw_kind
    if "doi.org" in url or raw_kind == "doi":
        return "doi"
    if raw_kind in {"academic", "openalex", "crossref", "pubmed", "semantic_scholar"}:
        return "paper"
    if any(marker in text for marker in ("systematic review", "review", "mini review")):
        return "review"
    if any(marker in text for marker in ("statistics", "statista", "통계", "market size")):
        return "statistics"
    if any(marker in text for marker in ("government", ".gov", "ministry", "농림축산", "kosis")):
        return "government"
    if any(marker in text for marker in ("industry report", "market report", "gartner", "mordor", "marketsandmarkets")):
        return "industry_report"
    if any(marker in text for marker in ("price", "pricing", "shop", "catalog", "quote")):
        return "pricing_page"
    if raw_kind in {"mock", "empty"}:
        return raw_kind
    return raw_kind or "web"


def _is_search_result_echo_ref(ref: EvidenceRef, plan: ResearchPlan | None) -> bool:
    """Detect search/landing pages whose only topic match is the submitted query.

    Search-result pages can echo the user query in the URL/quote while the actual
    result title points to an unrelated dataset or article. Those echoes are not
    evidence and must not satisfy source facets.
    """

    provenance = ref.provenance or {}
    metadata = provenance.get("metadata") if isinstance(provenance.get("metadata"), dict) else {}
    access_status = str(ref.access_status or "").casefold()
    url = str(ref.source_url or metadata.get("source") or "").casefold()
    quote = str(ref.quote or metadata.get("source_text") or "").casefold()
    search_markers = (
        "selectdatasetlist",
        "keyword=",
        "search result page",
        "search-result page",
        "검색결과",
        "검색 결과",
    )
    echo_like = any(marker in url or marker in quote for marker in search_markers)
    landing_only = access_status in {"landing_page_only", "search_result", "search_result_only"}
    # Search/listing pages often echo the submitted topic in the title, URL, or
    # snippet. That anchor overlap must not rescue the record: a search results
    # page is not an item-level dataset, paper, statistic, or regulatory source.
    return bool(echo_like or landing_only)


def _source_satisfies_facet(
    ref: EvidenceRef,
    facet: ResearchFacet,
    *,
    plan: ResearchPlan | None,
    source_kind: str,
    relevance_score: float,
) -> bool:
    kind_satisfies = source_kind in facet.required_source_kinds
    text_satisfies = _source_matches_facet_text(ref, facet)
    topic_anchor_satisfies = _source_has_topic_domain_anchor(ref, plan)
    if facet.id in {"market", "regional_adoption"}:
        # Market/adoption facets are especially prone to false positives from
        # generic words such as adoption, cost, regulatory, detection, and
        # market. Require the source text itself to carry both facet evidence
        # and a non-generic topic-domain anchor; provenance query terms are not
        # evidence.
        return bool(
            text_satisfies
            and relevance_score >= _minimum_relevance_score(plan)
            and topic_anchor_satisfies
        )
    if facet.id in {"scientific", "field_validation"}:
        # Authority shape (DOI/arXiv/academic index) is only a carrier. It must
        # not satisfy scientific facets by itself: the source title/quote/item
        # metadata still needs both topic-domain anchors and facet evidence.
        return bool(
            relevance_score >= _minimum_relevance_score(plan)
            and topic_anchor_satisfies
            and text_satisfies
            and (kind_satisfies or source_kind in {"web", "paper", "doi", "academic"})
        )
    if plan is not None and kind_satisfies:
        return bool(topic_anchor_satisfies and (text_satisfies or relevance_score >= _minimum_relevance_score(plan)))
    return bool(text_satisfies or kind_satisfies)


def _source_matches_facet_text(ref: EvidenceRef, facet: ResearchFacet) -> bool:
    text = " ".join(str(value or "").casefold() for value in (ref.source_title, ref.quote, ref.source_url))
    if facet.id == "scientific":
        return any(marker in text for marker in ("paper", "journal", "doi", "pcr", "lamp", "assay", "metabolomics", "ontology"))
    if facet.id == "market":
        return any(marker in text for marker in ("market", "pricing", "adoption", "willingness", "consumer", "survey", "trend", "statistics", "farm", "farmer", "production area", "시장", "가격", "구매", "도입", "소비", "트렌드", "조사", "통계", "농가"))
    if facet.id == "field_validation":
        return any(marker in text for marker in ("field", "validation", "sensitivity", "specificity", "현장", "검증", "민감도", "특이도"))
    if facet.id == "regional_adoption":
        return any(marker in text for marker in ("korea", "korean", "japan", "china", "europe", "usa", "regulatory", "distribution", "channel", "한국", "국내", "규제", "유통", "도입", "가격"))
    if facet.id == "general":
        return True
    return False


def _source_relevance_score(ref: EvidenceRef, plan: ResearchPlan | None) -> float:
    return round(float(_source_relevance_basis(ref, plan).get("relevance_score") or 0.0), 3)


def _source_relevance_basis(ref: EvidenceRef, plan: ResearchPlan | None) -> dict[str, Any]:
    """Explain exactly which topic surface drove source relevance.

    When a topic anchor is present, it is the only relevance basis. Submitted
    queries are intentionally excluded because production search APIs can echo
    polluted query text next to unrelated high-authority records.
    """

    if plan is None:
        return {
            "basis": "no_plan",
            "topic_anchor_present": False,
            "query_terms_used": False,
            "fallback_query_used": False,
            "topic_anchor_terms": [],
            "matched_terms": [],
            "overlap_count": 0,
            "required_overlap": 0,
            "minimum_relevance_score": 0.0,
            "relevance_score": 1.0,
            "meets_anchor_overlap_floor": True,
        }

    topic_anchor = str(getattr(plan, "topic_anchor", "") or "").strip()
    canonical_terms = _source_canonical_topic_terms(plan)
    domain_terms = _source_required_topic_terms(plan)
    text_terms = _content_terms(_source_item_text(ref))
    matched_terms = sorted(domain_terms & text_terms)
    required_overlap = _topic_anchor_required_overlap(plan, canonical_terms or domain_terms)
    score_denominator = max(1, min(4, len(domain_terms)))
    relevance_score = 0.0 if not domain_terms else round(min(1.0, len(matched_terms) / score_denominator), 3)
    if not topic_anchor:
        basis = "topic_anchor_missing"
    elif not domain_terms:
        basis = "topic_anchor_empty_after_filtering"
    else:
        basis = "topic_anchor"

    return {
        "basis": basis,
        "topic_anchor_present": bool(topic_anchor),
        "query_terms_used": False,
        "fallback_query_used": False,
        "topic_anchor_excerpt": _compact_relevance_text(_topic_anchor_source_surface(topic_anchor)),
        "topic_anchor_canonical_terms": sorted(canonical_terms),
        "topic_anchor_terms": sorted(domain_terms),
        "matched_terms": matched_terms,
        "overlap_count": len(matched_terms),
        "required_overlap": required_overlap,
        "minimum_relevance_score": _minimum_relevance_score(plan),
        "relevance_score": relevance_score,
        "meets_anchor_overlap_floor": bool(domain_terms and len(matched_terms) >= required_overlap),
    }


def _source_meets_topic_relevance(
    ref: EvidenceRef,
    plan: ResearchPlan | None,
    *,
    relevance_basis: Mapping[str, Any] | None = None,
) -> bool:
    if plan is None:
        return True
    basis = dict(relevance_basis or _source_relevance_basis(ref, plan))
    return bool(
        basis.get("meets_anchor_overlap_floor")
        and float(basis.get("relevance_score") or 0.0) >= _minimum_relevance_score(plan)
    )


def _source_has_topic_domain_anchor(ref: EvidenceRef, plan: ResearchPlan | None) -> bool:
    """Return True when source text has non-generic domain overlap for fragile facets.

    Market/adoption searches often retrieve unrelated sources that happen to say
    "adoption", "cost", "regulatory", "detection", or "system". Those
    framework words are not enough: the source itself must mention a
    non-generic domain anchor from the original topic. Provenance query text is
    deliberately excluded.
    """

    if plan is None:
        return True
    anchor_terms = _topic_domain_anchor_terms(plan)
    if anchor_terms:
        return _source_meets_topic_relevance(ref, plan)

    return False


def _source_item_text(ref: EvidenceRef) -> str:
    """Text that belongs to the retrieved item, not to the submitted query.

    Source relevance must be earned by the title, quote, locator and item-level
    metadata. The provenance query is intentionally excluded because search APIs
    often echo the user's request next to unrelated DOI/arXiv records.
    """

    provenance = ref.provenance or {}
    metadata = provenance.get("metadata") if isinstance(provenance.get("metadata"), dict) else {}
    metadata_values: list[str] = []
    for key in (
        "title",
        "abstract",
        "snippet",
        "description",
        "source_text",
        "source",
        "authors",
        "journal",
        "venue",
    ):
        value = metadata.get(key) if isinstance(metadata, dict) else None
        if isinstance(value, (list, tuple)):
            metadata_values.extend(str(item or "") for item in value)
        else:
            metadata_values.append(str(value or ""))
    return " ".join(str(value or "") for value in (ref.source_url, ref.source_title, ref.quote, *metadata_values))


def _topic_anchor_required_overlap(plan: ResearchPlan | None, terms: set[str] | None = None) -> int:
    if plan is None:
        return 1
    if not terms:
        terms = _source_canonical_topic_terms(plan)
    if not terms:
        return 1
    return max(1, min(3, len(terms) // 2))


def _topic_domain_anchor_terms(plan: ResearchPlan | None) -> set[str]:
    """Extract source-required topic terms without channel/facet bridge words."""

    return _source_required_topic_terms(plan)


def _source_required_topic_terms(plan: ResearchPlan | None) -> set[str]:
    """Return source-side topic terms from the clean topic surface.

    Production query plans can accumulate bridge words, route suffixes, or even
    unrelated result-title pollution. A populated topic_anchor is therefore the
    only canonical current-topic surface. Query text is deliberately not used as
    a fallback: missing anchors fail closed so production-shaped query pollution
    cannot validate itself.
    """

    terms = _expand_research_terms(_source_canonical_topic_terms(plan))
    return {
        term
        for term in terms
        if not _is_generic_research_word(term)
        and not _is_framework_research_word(term)
        and not _is_channel_or_geography_research_word(term)
    }


def _source_canonical_topic_terms(plan: ResearchPlan | None) -> set[str]:
    if plan is None:
        return set()
    topic_anchor = str(getattr(plan, "topic_anchor", "") or "").strip()
    if not topic_anchor:
        return set()
    topic_surface = _topic_anchor_source_surface(topic_anchor)
    terms = _content_terms(topic_surface)
    return {
        term
        for term in terms
        if not _is_generic_research_word(term)
        and not _is_framework_research_word(term)
        and not _is_channel_or_geography_research_word(term)
    }


def _topic_anchor_source_surface(topic_anchor: str) -> str:
    """Trim prompt instruction tails from a stored topic anchor.

    Live runs may persist the full operator prompt as ``topic_anchor``. The
    source-relevance basis should be the user's current topic/research question,
    not quality-bar, provider-routing, or deliverable instructions that unrelated
    result pages can easily echo.
    """

    import re

    return re.split(
        r"\b(?:quality\s+bar|deliverable|provider\s+route|use\s+mimo|do\s+not\s+call)\b\s*: ?",
        str(topic_anchor or ""),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]


def _compact_relevance_text(text: str, *, limit: int = 240) -> str:
    compacted = " ".join(str(text or "").split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 3].rstrip() + "..."


def _minimum_relevance_score(plan: ResearchPlan | None) -> float:
    if plan is None:
        return 0.0
    return 0.35


def _gap_message_for_facet(facet: ResearchFacet) -> str:
    if facet.id == "market":
        return "Need market size, pricing, buyer adoption, government/statistics, or industry-report evidence"
    if facet.id == "regional_adoption":
        return "Need regional adoption, channel, regulatory, pricing, or public statistics evidence"
    if facet.id == "field_validation":
        return "Need field validation, sensitivity/specificity, trial, or benchmark evidence"
    return "Need additional scientific paper/DOI/review evidence for core claims"


def _ref_is_relevant_to_plan(ref: EvidenceRef, plan: ResearchPlan | None) -> bool:
    if plan is None:
        return True
    return _source_meets_topic_relevance(ref, plan)


def _has_scientific_intent(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "molecular",
            "pcr",
            "lamp",
            "assay",
            "diagnostic",
            "diagnostics",
            "diagnosis",
            "pathogen",
            "bacteria",
            "infection",
            "probe",
            "fluorescent",
            "fluorescence",
            "biosensor",
            "specificity",
            "selectivity",
            "진단",
            "분자진단",
            "병원체",
            "논문",
            "학술",
            "과학",
        )
    )


def _has_market_intent(text: str) -> bool:
    normalized = str(text or "").casefold()
    financial_market_markers = (
        "주식시장",
        "증권시장",
        "금융시장",
        "암호화폐 시장",
        "stock market",
        "financial market",
        "securities market",
        "crypto market",
    )
    if any(marker in normalized for marker in financial_market_markers):
        return False
    return any(
        marker in normalized
        for marker in (
            "시장성",
            "가격",
            "pricing",
            "adoption",
            "구매",
            "willingness",
            "사업성",
            "수익",
        )
    )


def _has_regional_adoption_intent(text: str) -> bool:
    """Detect regional market/adoption research intent from general markers.
    Deliberately domain-agnostic: no vertical-specific terms."""
    normalized = str(text or "").casefold()
    region_markers = ("한국", "국내", "korea", "korean", "japan", "china", "europe", "usa", "global")
    adoption_markers = ("도입", "유통", "채널", "규제", "인증", "가격", "시장성", "구매", "소비", "트렌드", "조사",
                        "adoption", "distribution", "channel", "regulatory", "pricing", "market")
    return any(marker in normalized for marker in region_markers) and any(
        marker in normalized for marker in adoption_markers
    )


def _has_field_validation_intent(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "diagnostic",
            "diagnostics",
            "diagnosis",
            "molecular",
            "pcr",
            "lamp",
            "probe",
            "fluorescent",
            "fluorescence",
            "biosensor",
            "specificity",
            "selectivity",
            "on-site",
            "onsite",
            "field applicability",
            "진단",
            "분자진단",
            "키트",
            "병해",
            "병원체",
            "field validation",
            "현장",
        )
    )


def _content_terms(text: str) -> set[str]:
    import re

    return {term.lower() for term in re.findall(r"[A-Za-z0-9]+|[가-힣]{2,}", str(text or ""))}


def _is_generic_research_word(word: str) -> bool:
    normalized = word.lower()
    if normalized.isdigit():
        return True
    if normalized.startswith("pmc") and normalized[3:].isdigit():
        return True
    if len(normalized) <= 1 and normalized.isascii():
        return True
    return normalized in {
        "doi",
        "source",
        "backed",
        "evidence",
        "official",
        "statistics",
        "peer",
        "reviewed",
        "constraints",
        "risk",
        "research",
        "deep",
        "council",
        "persona",
        "case",
        "cases",
        "studies",
        "examples",
        "definitions",
        "scope",
        "methods",
        "failure",
        "limitations",
        "counter",
        "review",
        "reviews",
        "recent",
        "advances",
        "protocol",
        "procedure",
        "procedures",
        "applicability",
        "site",
        "anchor",
        "pmcid",
        "turn",
        "on",
        "no",
        "topic",
        "question",
        "assess",
        "evaluate",
        "recall",
        "verify",
        "claim",
        "claims",
        "quality",
        "bar",
        "accepted",
        "authoritative",
        "relevant",
        "directly",
        "clearly",
        "contextual",
        "core",
        "explicit",
        "fixture",
        "benchmark",
        "metrics",
        "api",
        "gemini",
        "mimo",
        "opencode",
        "max",
        "go",
        "call",
        "use",
        "must",
        "not",
        "do",
        "or",
        "of",
        "be",
        "only",
        "against",
        "unless",
        "empty",
        "mock",
        "result",
        "listing",
        "search",
        "protocols",
        "star",
        "performance",
        "plant",
        "sample",
        "response",
        "limit",
        "companion",
        "to",
        "for",
        "with",
        "and",
        "the",
    }


def _is_framework_research_word(word: str) -> bool:
    return word.lower() in {
        "market",
        "adoption",
        "pricing",
        "willingness",
        "pay",
        "low",
        "cost",
        "distribution",
        "detection",
        "field",
        "validation",
        "accuracy",
        "sensitivity",
        "specificity",
        "시장성",
        "시장",
        "가격",
        "채널",
        "성능",
        "약점",
        "수집",
        "검증",
        "공식",
        "통계",
        "위험",
        "리스크",
    }


def _is_channel_or_geography_research_word(word: str) -> bool:
    return word.lower() in {
        "korea",
        "korean",
        "한국",
        "국내",
        "government",
        "ministry",
        "public",
        "regulatory",
        "regulation",
        "regulations",
        "policy",
        "channel",
        "channels",
        "distribution",
        "buyer",
        "buyers",
        "customer",
        "customers",
        "saas",
        "software",
        "platform",
        "정부",
        "공공",
        "규제",
        "정책",
        "유통",
        "채널",
    }


def _expand_research_terms(terms: set[str]) -> set[str]:
    """Expand terms with cross-language synonyms. Only general-purpose mappings
    that apply across domains are included; vertical-specific terms are left
    to the caller's topic_anchor so the system stays domain-agnostic."""
    expanded = set(terms)
    synonyms = {
        "농가": {"farm", "farms", "farmer", "farmers"},
        "farm": {"farms", "farmer", "farmers"},
        "farmer": {"farm", "farms", "farmers"},
        "저비용": {"low", "cost", "lowcost", "low-cost"},
        "분자진단": {"molecular", "diagnostic", "diagnostics"},
        "진단": {"diagnostic", "diagnostics"},
        "키트": {"kit", "kits"},
        "온톨로지": {"ontology", "ontologies"},
        "대사체": {"metabolomics", "metabolome"},
        "kit": {"키트", "assay", "test"},
    }
    for term in terms:
        expanded.update(synonyms.get(term, set()))
    return expanded


def _dedupe_evidence_refs(refs: list[EvidenceRef]) -> list[EvidenceRef]:
    out: list[EvidenceRef] = []
    seen: set[str] = set()
    for ref in refs:
        if ref.id in seen:
            continue
        seen.add(ref.id)
        out.append(ref)
    return out


def _is_generated_ref(ref: EvidenceRef) -> bool:
    haystack = " ".join(
        str(value or "").lower()
        for value in (
            ref.id,
            ref.source_title,
            ref.quote,
            (ref.provenance or {}).get("kind"),
        )
    )
    generated_markers = ("generated", "synthetic", "mock", "empty")
    provenance = ref.provenance or {}
    metadata = provenance.get("metadata") if isinstance(provenance.get("metadata"), dict) else {}
    if str(provenance.get("kind") or metadata.get("kind") or "").casefold().strip() in generated_markers:
        return True
    return any(marker in haystack for marker in ("mock-evidence", "empty-evidence", "mock research", "synthetic generated"))


def _mutate_query(query: str, suffix: str) -> str:
    normalized = " ".join(str(query).split())
    if suffix.casefold() in normalized.casefold():
        return normalized
    return f"{normalized} {suffix}".strip()


def _candidate_id(description: str, queries: list[str]) -> str:
    key = f"{description}|{'|'.join(queries)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _safe_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(value)).strip("-")


def _dedupe_strings(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(str(value).split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        out.append(normalized)
    return out


def _tsv_safe(value: str) -> str:
    return " ".join(str(value).replace("\t", " ").split())


def _display_source_path(path: Path) -> str:
    if not path.is_absolute():
        return str(path)
    repo_root = Path(__file__).resolve().parents[2]
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)
