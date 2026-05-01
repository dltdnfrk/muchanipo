"""AutoResearch runner implementations.

Mock runner is preserved untouched — `tests/test_c31_research_evidence.py` keeps
passing. `WebResearchRunner` wires three real backends behind injectable
callables so tests can run without API keys:

  - `web_search`  — WebSearch / Anthropic web tool wrapper (callable injected)
  - `exa_search`  — exa MCP wrapper (callable injected)
  - `vault_search`— defaults to `src/search/insight-forge.py::_search_local_vault`,
                    loaded via importlib (filename has a hyphen)

The runner aggregates hits from whichever backends are wired and folds them
into `EvidenceRef` + `Finding` objects so downstream `EvidenceStore` and
`citation_grounder` integration get real source URLs and quotes.
"""
from __future__ import annotations

import hashlib
import importlib.util
import logging
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Union

from src.evidence.artifact import EvidenceRef, Finding
from src.evidence.provenance import Provenance

from .academic import sync_search as academic_sync_search
from .planner import ResearchPlan
from .synthesis import finding_from_query


SearchHit = Union[dict, EvidenceRef]
SearchFn = Callable[[str], Iterable[SearchHit]]
LOGGER = logging.getLogger(__name__)


class MockResearchRunner:
    """API-key-free runner used by tests and early pipeline wiring."""

    def run(self, plan: ResearchPlan) -> list[Finding]:
        self.last_backend_trace = [
            {
                "backend": "mock",
                "query": query,
                "status": "mock",
                "count": 1,
            }
            for query in (plan.queries or ["research question"])
        ]
        findings: list[Finding] = []
        for idx, query in enumerate(plan.queries or ["research question"], start=1):
            evidence = EvidenceRef(
                id=f"mock-evidence-{idx}",
                source_url=None,
                source_title="Mock research evidence",
                quote=query,
                source_grade="B",
                provenance=Provenance(kind="mock", metadata={"brief_id": plan.brief_id}).as_dict(),
            )
            findings.append(finding_from_query(query, evidence))
        return findings


def _load_default_vault_search() -> SearchFn | None:
    """Lazily load `_search_local_vault` from src/search/insight-forge.py.

    The file has a hyphen so plain `import` does not work — we use
    importlib's spec_from_file_location. Returns None if the file is missing
    so test environments without the vault module still operate.
    """
    src_path = Path(__file__).resolve().parent.parent / "search" / "insight-forge.py"
    if not src_path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("muchanipo_insight_forge", src_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 — graceful import failure
        return None
    fn = getattr(module, "_search_local_vault", None)
    if not callable(fn):
        return None
    return lambda query: fn(query, limit=3)


def _load_default_insight_forge_search() -> SearchFn | None:
    """Load InsightForge's full RRF/GBrain search path behind an env gate."""
    depth = os.environ.get("MUCHANIPO_INSIGHT_FORGE_DEPTH", "light").strip().lower()
    if depth in {"", "disabled", "off", "0", "no", "false"}:
        return None
    if depth not in {"light", "deep"}:
        depth = "light"

    src_path = Path(__file__).resolve().parent.parent / "search" / "insight-forge.py"
    if not src_path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("muchanipo_insight_forge_full", src_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("insight_forge import failed: %s", exc)
        return None
    forge = getattr(module, "insight_forge", None)
    if not callable(forge):
        return None

    def _search(query: str) -> list[dict[str, Any]]:
        try:
            payload = forge(query=query, depth=depth)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("insight_forge backend failed for query %r: %s", query, exc)
            return []
        hits: list[dict[str, Any]] = []
        for item in payload.get("results", []) or []:
            text = item.get("text") or ""
            source = item.get("source") or ""
            if not text and not source:
                continue
            hits.append(
                {
                    "kind": "insight_forge",
                    "text": text,
                    "source": source,
                    "title": source or "InsightForge result",
                    "score": float(item.get("rrf_score") or item.get("score") or 0.0),
                    "matched_questions": list(item.get("matched_questions") or []),
                }
            )
        return hits

    return _search


def _grade_for(hit: dict) -> str:
    """Heuristic source grade: vault hits → B, web → C unless score>=0.8."""
    score = float(hit.get("score") or 0.0)
    kind = (hit.get("kind") or "").lower()
    if kind in {"vault", "obsidian", "insight_forge"} or hit.get("source", "").endswith(".md"):
        return "B"
    if score >= 0.8:
        return "B"
    return "C"


class WebResearchRunner:
    """Real-wire runner. All network access is delegated to injected callables
    so tests can exercise the integration with stubs and zero API usage."""

    def __init__(
        self,
        web_search: SearchFn | None = None,
        exa_search: SearchFn | None = None,
        vault_search: SearchFn | None = None,
        academic_search: SearchFn | None = None,
        insight_forge_search: SearchFn | None = None,
        enable_default_insight_forge: bool | None = None,
        per_query_cap: int = 4,
    ) -> None:
        self.web_search = web_search
        self.exa_search = exa_search
        self.academic_search = academic_search
        if enable_default_insight_forge is None:
            enable_default_insight_forge = not any(
                backend is not None for backend in (web_search, exa_search, vault_search, academic_search)
            )
        self.insight_forge_search = (
            _load_default_insight_forge_search()
            if insight_forge_search is None and enable_default_insight_forge
            else insight_forge_search
        )
        # vault default loaded lazily; allow explicit None to disable
        if vault_search is None:
            self.vault_search = _load_default_vault_search()
        else:
            self.vault_search = vault_search
        self.per_query_cap = max(1, per_query_cap)
        self.last_backend_trace: list[dict[str, Any]] = []

    def _gather(self, query: str) -> list[dict]:
        hits: list[dict] = []
        for backend, kind in (
            (self.insight_forge_search, "insight_forge"),
            (self.vault_search, "vault"),
            (self.academic_search, "academic"),
            (self.web_search, "web"),
            (self.exa_search, "exa"),
        ):
            if backend is None:
                continue
            try:
                raw = list(backend(query) or [])
            except Exception as exc:  # noqa: BLE001 — never fail the whole run
                LOGGER.warning("research backend %s failed for query %r: %s", kind, query, exc)
                self.last_backend_trace.append(
                    {
                        "backend": kind,
                        "query": query,
                        "status": "error",
                        "count": 0,
                        "error": str(exc).splitlines()[0][:160],
                    }
                )
                continue
            self.last_backend_trace.append(
                {
                    "backend": kind,
                    "query": query,
                    "status": "ok",
                    "count": len(raw),
                }
            )
            for item in raw:
                if isinstance(item, EvidenceRef):
                    hits.append({"kind": kind, "score": 1.0, "evidence_ref": item})
                    continue
                if not isinstance(item, dict):
                    continue
                item.setdefault("kind", kind)
                hits.append(item)
        # Stable sort: highest score first; cap per query
        hits.sort(key=lambda h: float(h.get("score") or 0.0), reverse=True)
        return hits[: self.per_query_cap]

    def _to_evidence(self, hit: dict, query: str, idx: int, sub_idx: int, plan: ResearchPlan) -> EvidenceRef:
        existing = hit.get("evidence_ref")
        if isinstance(existing, EvidenceRef):
            return existing
        kind = hit.get("kind") or "web"
        source_url = hit.get("url") or hit.get("source_url")
        source = hit.get("source") or source_url or "unknown"
        provenance = Provenance(
            kind=kind,
            metadata={
                "brief_id": plan.brief_id,
                "query": query,
                "score": float(hit.get("score") or 0.0),
                "source": source,
                "source_text": (hit.get("text") or "")[:280],
            },
        ).as_dict()
        stable_key = "|".join(
            [
                str(kind),
                str(source_url or ""),
                str(source),
                str(hit.get("title") or ""),
                query,
                str(sub_idx),
            ]
        )
        digest = hashlib.sha1(stable_key.encode("utf-8")).hexdigest()[:10]
        return EvidenceRef(
            id=f"{kind}-{idx}-{sub_idx}-{digest}",
            source_url=source_url,
            source_title=hit.get("title") or source,
            quote=(hit.get("text") or hit.get("snippet") or query)[:280],
            source_grade=_grade_for(hit),
            provenance=provenance,
        )

    def run(self, plan: ResearchPlan) -> list[Finding]:
        self.last_backend_trace = []
        findings: list[Finding] = []
        queries = plan.queries or ["research question"]
        for idx, query in enumerate(queries, start=1):
            hits = self._gather(query)
            if not hits:
                # Mirror MockResearchRunner shape so downstream code stays robust.
                evidence = EvidenceRef(
                    id=f"empty-evidence-{idx}",
                    source_url=None,
                    source_title="No live evidence — graceful fallback",
                    quote=query,
                    source_grade="D",
                    provenance=Provenance(
                        kind="empty",
                        metadata={"brief_id": plan.brief_id, "query": query},
                    ).as_dict(),
                )
                findings.append(finding_from_query(query, evidence))
                continue
            evidence_refs = [
                self._to_evidence(hit, query, idx, sub_idx, plan)
                for sub_idx, hit in enumerate(hits, start=1)
            ]
            top = evidence_refs[0]
            finding = Finding(
                claim=f"Initial research direction for: {query}",
                support=evidence_refs,
                confidence=min(0.95, 0.5 + 0.1 * len(evidence_refs)),
                limitations=[]
                if any(ev.source_grade in {"A", "B"} for ev in evidence_refs)
                else ["all sources graded C/D — needs higher-grade follow-up"],
            )
            findings.append(finding)
        return findings


def build_runner(use_real: bool = False, **kwargs: Any) -> MockResearchRunner | WebResearchRunner:
    """Factory that swaps mock ↔ real keeping the same interface."""
    if not use_real:
        return MockResearchRunner()
    if "academic_search" not in kwargs:
        kwargs["academic_search"] = academic_sync_search.search
    if "insight_forge_search" not in kwargs and "enable_default_insight_forge" not in kwargs:
        kwargs["enable_default_insight_forge"] = True
    return WebResearchRunner(**kwargs)
