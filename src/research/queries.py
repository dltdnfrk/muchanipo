"""Query helpers for AutoResearch.

The goal is to keep Stage 3 from becoming a vague "search the web" step.
Each query expansion states a distinct evidence intent so runners can collect
coverage across primary evidence, constraints, and counter-signals.
"""
from __future__ import annotations


def expand_query(
    query: str,
    *,
    context: str = "",
    quality_bar: str = "",
    max_queries: int = 5,
) -> list[str]:
    query = query.strip()
    if not query:
        return []

    # Keep query expansion topic-anchored and domain-neutral. Muchanipo is a
    # general-purpose research tool: Korean topics should not be rewritten into
    # hardcoded vertical presets such as AgTech, diagnostics, pricing, or a
    # standalone "Korea" bridge query. Search backends may still receive the
    # original Korean topic plus generic evidence intents.
    candidates = [
        query,
        f"{query} official statistics peer reviewed evidence",
        f"{query} definitions scope methods constraints",
        f"{query} source-backed examples case studies",
        f"{query} counter evidence limitations failure cases",
    ]
    if context.strip():
        candidates.append(f"{query} {context.strip()} source evidence")
    if quality_bar.strip():
        candidates.append(f"{query} {quality_bar.strip()} source quality")

    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = " ".join(candidate.split())
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        out.append(normalized)
        if len(out) >= max(1, max_queries):
            break
    return out


def translated_topic_queries(query: str) -> list[str]:
    """Add topic-anchored bridge queries without injecting a vertical preset.

    Muchanipo is a general-purpose research tool. The planner may add generic
    source-channel probes (official statistics, adoption, limitations, methods),
    but domain specialization must come from the user's topic, interview answers,
    or targeting map — not from keyword-triggered AgTech/diagnostics/etc. presets.
    """
    query = " ".join(query.split())
    if not query:
        return []
    lowered = query.casefold()

    # Suppress product-market source-channel probes for financial-asset market
    # questions, but do not treat every "forecast/예측" as an asset-market query:
    # product adoption forecasts still need government/statistics/WTP evidence.
    financial_asset_market_intent = any(
        marker in query or marker in lowered
        for marker in (
            "주식",
            "증권",
            "암호화폐",
            "가상자산",
            "선물",
            "옵션",
            "채권",
            "외환",
            "stock market",
            "financial market",
            "equity market",
            "crypto market",
            "cryptocurrency",
            "bitcoin",
            "bond market",
            "forex",
            "fx market",
            "futures",
            "options market",
            "derivatives",
            "commodity market",
        )
    )
    source_channel_intent = (not financial_asset_market_intent) and any(
        marker in query or marker in lowered
        for marker in (
            "시장성",
            "가격",
            "채택",
            "도입",
            "구매",
            "지불의사",
            "규제",
            "유통",
            "통계",
            "market",
            "pricing",
            "adoption",
            "willingness to pay",
            "regulatory adoption",
            "distribution channel",
        )
    )
    if not source_channel_intent:
        return []

    # Use the topic itself as the bridge base. Do not translate selected tokens
    # into a hardcoded domain lexicon here; the deep interview/targeting map is
    # responsible for adding domain-specific search language when needed.
    base = query
    queries = [base]
    local_query = _local_language_source_channel_query(query)
    if local_query:
        queries.append(local_query)
    queries.extend(
        [
            f"{base} government statistics willingness to pay adoption market adoption pricing government statistics market adoption pricing willingness to pay",
            f"{base} empirical evidence methods validation limitations",
            f"{base} distribution channel regulatory adoption case studies",
        ]
    )
    if _scientific_validation_intent(query):
        queries.append(f"{base} peer reviewed assay field validation sensitivity specificity")
    return queries


def _scientific_validation_intent(query: str) -> bool:
    lowered = " ".join(query.casefold().split())
    return any(
        marker in lowered
        for marker in (
            "diagnostic",
            "diagnostics",
            "molecular",
            "assay",
            "field validation",
            "detection kit",
            "진단",
            "검출",
            "분자",
        )
    )


def _local_language_source_channel_query(query: str) -> str:
    """Build a concise local-language source-channel query when possible.

    Market/adoption evidence often lives in local government/statistics pages,
    while long translated technical queries can return no web hits. Keep this
    procedural and domain-neutral: retain local topic nouns, drop scientific
    method terms that would force a diagnostic evidence gate, and add generic
    channel/facet words.
    """

    import re

    if not re.search(r"[가-힣]", query):
        return ""
    terms = re.findall(r"[가-힣A-Za-z0-9]+", query)
    excluded = {
        "source",
        "backed",
        "deep",
        "research",
        "council",
        "persona",
        "검증",
    }
    kept: list[str] = []
    for term in terms:
        key = term.casefold()
        if key in excluded or term in excluded:
            continue
        if term.isdigit() or re.fullmatch(r"\d+[a-z]?", key):
            continue
        if term not in kept:
            kept.append(term)
    if not kept:
        return ""
    suffix = ["공식", "통계", "가격", "도입", "유통", "규제"]
    return " ".join(kept[:6] + suffix)
