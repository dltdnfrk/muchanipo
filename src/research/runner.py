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
import re
import queue
import threading
from pathlib import Path
from typing import Any, Callable, Iterable, Union

from src.evidence.artifact import EvidenceRef, Finding
from src.evidence.provenance import Provenance
from src.runtime.live_mode import live_requested_from_env, source_research_requested_from_env

from .academic import sync_search as academic_sync_search
from . import public_web
from .planner import ResearchPlan
from .synthesis import finding_from_query


SearchHit = Union[dict, EvidenceRef]
SearchFn = Callable[[str], Iterable[SearchHit]]
LOGGER = logging.getLogger(__name__)


class ResearchBackendTimeout(TimeoutError):
    """Raised when a single source-research backend exceeds its wall clock budget."""


def _backend_timeout_seconds() -> float:
    raw = os.environ.get("MUCHANIPO_RESEARCH_BACKEND_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0


def _call_backend_with_timeout(backend: SearchFn, query: str, kind: str) -> list[SearchHit]:
    """Call a sync source-channel adapter with a hard wall-clock budget.

    Verification-19 full/deep attempts exposed heartbeat-only stalls before any
    `source_evaluated` events. Lower-level HTTP timeouts are useful, but this
    outer guard also bounds DNS/connect hangs and arbitrary injected adapters.
    A daemon worker is used instead of SIGALRM so the guard works from both the
    main thread and worker-thread runtimes.
    """

    timeout = _backend_timeout_seconds()
    if timeout <= 0:
        return list(backend(query) or [])

    result_q: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

    def _worker() -> None:
        try:
            result_q.put(("ok", list(backend(query) or [])))
        except Exception as exc:  # noqa: BLE001
            result_q.put(("error", exc))

    thread = threading.Thread(target=_worker, name=f"muchanipo-research-{kind}-watchdog", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise ResearchBackendTimeout(f"research backend {kind} timed out after {timeout:.2f}s")
    try:
        status, payload = result_q.get_nowait()
    except queue.Empty as exc:
        raise ResearchBackendTimeout(f"research backend {kind} returned no result after {timeout:.2f}s") from exc
    if status == "error":
        raise payload
    return list(payload or [])


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
            if _is_unsafe_research_hit(source=source, text=text):
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


def _infer_access_status_from_hit(hit: dict) -> str | None:
    """Deterministic access_status from raw hit metadata."""
    if hit.get("access_status"):
        return str(hit["access_status"])
    if hit.get("pdf_url") or hit.get("download_url") or hit.get("full_text_url"):
        return "full_text_available"
    if hit.get("is_oa") or hit.get("open_access"):
        return "oa_copy_found"
    if hit.get("text") or hit.get("snippet"):
        return "abstract_only"
    return "blocked"


def _is_unsafe_research_hit(*, source: str = "", text: str = "") -> bool:
    """Exclude generated/internal artifacts that would recycle prior mock reports.

    Local vault search is useful, but Muchanipo's own development notes and
    mock reports are not market evidence. Keeping them out here prevents
    downstream council/report stages from citing the product's previous output
    as if it were an external source.
    """
    haystack = f"{source}\n{text}".lower()
    if any(
        marker in haystack
        for marker in (
            "mock-evidence-",
            "mock research evidence",
            "not source-backed",
            "offline 실행은 흐름 검증용",
            "trusted evidence: 0",
            "verified claim ratio: 0.0",
        )
    ):
        return True

    normalized_source = source.replace("\\", "/").lower()
    generated_paths = (
        ".omx/",
        "projects/muchanipo/",
        "product/with-agent/muchanipo-p5int/",
        "council/",
        "raw/brief-",
        "wiki/brief-",
    )
    if any(marker in normalized_source for marker in generated_paths) and "muchanipo" in haystack:
        return True
    return False


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
        emit_empty_fallback: bool = True,
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
        self.emit_empty_fallback = emit_empty_fallback
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
                raw = _call_backend_with_timeout(backend, query, kind)
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
                    _attach_query_metadata(item, query)
                    source = " ".join(
                        part
                        for part in (
                            str(getattr(item, "source_url", "") or ""),
                            str(getattr(item, "source_title", "") or ""),
                        )
                        if part
                    )
                    text = str(getattr(item, "quote", "") or "")
                    haystack = f"{source} {text}"
                    if (
                        _is_unsafe_research_hit(source=source, text=text)
                        or not _has_query_overlap(query, haystack)
                        or not _has_required_domain_concepts(query, haystack)
                    ):
                        continue
                    score = 0.55 if kind == "academic" and _is_local_source_channel_query(query) else 1.0
                    hits.append({"kind": kind, "score": score, "evidence_ref": item})
                    continue
                if not isinstance(item, dict):
                    continue
                item.setdefault("kind", kind)
                source = str(item.get("source") or item.get("url") or item.get("source_url") or "")
                text = str(item.get("text") or item.get("snippet") or item.get("quote") or "")
                haystack = f"{source} {text}"
                if (
                    _is_unsafe_research_hit(source=source, text=text)
                    or not _has_query_overlap(query, haystack)
                    or not _has_required_domain_concepts(query, haystack)
                ):
                    continue
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
        access_status = _infer_access_status_from_hit(hit)
        return EvidenceRef(
            id=f"{kind}-{idx}-{sub_idx}-{digest}",
            source_url=source_url,
            source_title=hit.get("title") or source,
            quote=(hit.get("text") or hit.get("snippet") or query)[:280],
            source_grade=_grade_for(hit),
            provenance=provenance,
            access_status=access_status,
        )

    def run(self, plan: ResearchPlan) -> list[Finding]:
        self.last_backend_trace = []
        findings: list[Finding] = []
        queries = plan.queries or ["research question"]
        for idx, query in enumerate(queries, start=1):
            hits = self._gather(query)
            if not hits:
                if not self.emit_empty_fallback:
                    continue
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
                claim=_claim_from_evidence(top, query),
                support=evidence_refs,
                confidence=min(0.95, 0.5 + 0.1 * len(evidence_refs)),
                limitations=[]
                if any(ev.source_grade in {"A", "B"} for ev in evidence_refs)
                else ["all sources graded C/D — needs higher-grade follow-up"],
            )
            findings.append(finding)
        return findings


def _claim_from_evidence(ref: EvidenceRef, query: str) -> str:
    quote = " ".join(str(ref.quote or "").split())
    if len(quote) >= 24:
        return quote[:240]
    title = " ".join(str(ref.source_title or "").split())
    if len(title) >= 12:
        return title[:180]
    return f"Source-backed evidence collected for: {query}"


def _attach_query_metadata(ref: EvidenceRef, query: str) -> None:
    provenance = dict(ref.provenance or {})
    metadata = provenance.get("metadata") if isinstance(provenance.get("metadata"), dict) else {}
    metadata = dict(metadata)
    metadata.setdefault("query", query)
    provenance["metadata"] = metadata
    ref.provenance = provenance


def _is_local_source_channel_query(query: str) -> bool:
    text = str(query or "").casefold()
    return any(marker in text for marker in ("kosis", "농촌진흥청", "공식 통계", "공공데이터", "통계청")) and any(
        marker in text for marker in ("시장", "시장성", "가격", "구매", "소비", "도입", "유통", "adoption", "pricing")
    )


def _has_query_overlap(query: str, text: str) -> bool:
    query_terms = _expand_query_terms(
        {term for term in _content_terms(query) if not _is_generic_query_word(term)}
    )
    if not query_terms:
        return True
    text_terms = _content_terms(text)
    domain_terms = {term for term in query_terms if not _is_framework_query_word(term)}
    if domain_terms and not (domain_terms & text_terms):
        return False
    return bool(query_terms & text_terms)


def _has_required_domain_concepts(query: str, text: str) -> bool:
    """Require narrow diagnostic concepts when the query is explicitly diagnostic.

    A broad market query may legitimately match consumer/value sources,
    but a "molecular diagnostic kit" query must not be satisfied by generic
    post-harvest value or unrelated willingness-to-pay papers.
    """
    query_terms = _expand_query_terms(_content_terms(query))
    text_terms = _content_terms(text)
    text_blob = str(text or "").lower()
    diagnostic_query_terms = {
        "diagnostic",
        "diagnostics",
        "molecular",
        "pcr",
        "lamp",
        "pathogen",
        "disease",
        "detection",
        "진단",
        "분자진단",
        "병해",
        "병원체",
        "키트",
    }
    if not (query_terms & diagnostic_query_terms):
        return True
    if _is_market_source_channel_match(query_terms=query_terms, text_terms=text_terms, text_blob=text_blob):
        return True
    diagnostic_hit_terms = {
        "diagnostic",
        "diagnostics",
        "molecular",
        "pcr",
        "lamp",
        "pathogen",
        "disease",
        "detection",
        "biosensor",
        "poc",
        "probe",
        "진단",
        "분자진단",
        "병해",
        "병원체",
        "바이오센싱",
        "형광",
        "프로브",
        "키트",
    }
    if text_terms & diagnostic_hit_terms:
        return True
    return any(marker in text_blob for marker in ("plant diagnostics", "plant disease", "poc", "biosensor"))


def _is_market_source_channel_match(*, query_terms: set[str], text_terms: set[str], text_blob: str) -> bool:
    """Allow public market/adoption sources to support market facets.

    A market-channel query may preserve the user's diagnostic/product words for
    topic anchoring, while the source itself is a government/statistics/pricing
    page about the customer/channel rather than an assay paper. Keep this
    gate procedural: require both source-channel intent and source-side topical
    overlap before bypassing the diagnostic-method requirement.
    """

    market_query_terms = {
        "market",
        "adoption",
        "pricing",
        "price",
        "willingness",
        "pay",
        "distribution",
        "channel",
        "시장",
        "시장성",
        "가격",
        "구매",
        "소비",
        "도입",
        "유통",
        "통계",
        "정부",
        "공공데이터",
    }
    if not (query_terms & market_query_terms):
        return False
    # Topical overlap: source must share non-generic domain terms with the query
    framework_terms = {"market", "adoption", "pricing", "price", "willingness", "pay", "distribution",
                       "channel", "시장", "시장성", "가격", "구매", "소비", "도입", "유통", "통계",
                       "정부", "공공데이터", "official", "statistics", "peer", "reviewed"}
    topical_overlap = (query_terms & text_terms) - framework_terms
    if not topical_overlap:
        return False
    return any(
        marker in text_blob
        for marker in (
            "government",
            "statistics",
            "public data",
            "price",
            "pricing",
            "market",
            "adoption",
            "distribution",
            "통계",
            "공공데이터",
            "가격",
            "구매",
            "소비",
            "유통",
            "시장",
        )
    )


def _content_terms(text: str) -> set[str]:
    terms = {term.lower() for term in re.findall(r"[A-Za-z0-9]+|[가-힣]{2,}", str(text or ""))}
    return {term for term in terms if not re.fullmatch(r"\d+[a-z]?", term)}


def _is_generic_query_word(word: str) -> bool:
    return word.lower() in {
        "source",
        "backed",
        "evidence",
        "official",
        "statistics",
        "peer",
        "reviewed",
        "constraints",
        "risk",
        "to",
    }


def _is_framework_query_word(word: str) -> bool:
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


def _expand_query_terms(terms: set[str]) -> set[str]:
    """Expand query terms with general-purpose cross-language synonyms.
    Vertical-specific mappings are intentionally excluded."""
    expanded = set(terms)
    synonyms = {
        "저비용": {"low", "cost", "lowcost", "low-cost"},
        "분자진단": {"molecular", "diagnostic", "diagnostics"},
        "진단": {"diagnostic", "diagnostics"},
        "키트": {"kit", "kits"},
    }
    for term in terms:
        expanded.update(synonyms.get(term, set()))
    return expanded


def build_runner(use_real: bool = False, **kwargs: Any) -> MockResearchRunner | WebResearchRunner:
    """Factory that swaps mock ↔ real keeping the same interface."""
    if not use_real:
        return MockResearchRunner()
    if "web_search" not in kwargs:
        kwargs["web_search"] = public_web.search
    if "academic_search" not in kwargs:
        kwargs["academic_search"] = academic_sync_search.search
    if "insight_forge_search" not in kwargs and "enable_default_insight_forge" not in kwargs:
        kwargs["enable_default_insight_forge"] = True
    if "emit_empty_fallback" not in kwargs:
        kwargs["emit_empty_fallback"] = not (live_requested_from_env() or source_research_requested_from_env())
    return WebResearchRunner(**kwargs)
