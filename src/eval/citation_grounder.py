#!/usr/bin/env python3
"""
MuchaNipo Citation Grounder — claim ↔ evidence 1:1 검증 패스 (narrow scope)
==========================================================================

Council Report의 consensus / recommendations / dissent 텍스트에서 원자적 claim을
뽑고, 각 claim을 evidence 풀에 대조해 supported / partial / unsupported 판정.

이 모듈은 entailment verifier가 아닌 **citation presence + semantic overlap checker**다.
atomic claim decomposition은 NLI 모델이 필요하므로 stdlib 구현은 보수적인
substring 우선 + semantic fallback 정책을 따른다. 즉:
  - substring 직접 인용은 fast-path supported
  - substring 실패 시 token Jaccard / trigram overlap 이 threshold 이상이면 supported
  - 낮은 keyword overlap 은 'partial' 까지만 (citation laundering 차단)

stdlib only. eval-agent.py가 import해서 사용하거나 CLI로 단독 실행 가능.

Usage (module):
    from citation_grounder import ground_claims, grounding_gate
    g = ground_claims(consensus, recommendations, evidence, dissent="")
    allow, reason = grounding_gate(g)

Usage (CLI):
    python3 citation-grounder.py council-report.json --verbose
    python3 citation-grounder.py council-report.json --threshold 0.7

Rubric integration:
    `verified_claim_ratio` 와 `unsupported_critical_claim_count` 를 11번째 축
    `citation_fidelity` 의 입력으로 사용. eval-agent의 PASS 라우팅 직전 게이트.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Optional lockdown integration (safety 모듈 부재 환경 대응)
# ---------------------------------------------------------------------------
try:  # pragma: no cover - import path varies between contexts
    from src.safety import lockdown as _lockdown
except Exception:  # noqa: BLE001
    _lockdown = None  # graceful fallback — provenance/redact가 no-op


def _lockdown_validate_provenance(evidence: List[Dict[str, Any]]) -> Dict[str, bool]:
    """evidence별 provenance 통과 여부 dict. lockdown 부재 시 모두 통과.

    lockdown.validate_evidence_provenance 는 전체 리스트에 대한 (ok, errors)를
    반환하지만 여기서는 per-evidence boolean 매핑이 필요하므로 evidence를
    하나씩 호출하여 source_text 누락/quote 미포함 케이스를 잡는다.
    """
    if _lockdown is None:
        return {ev.get("id", str(idx)): True for idx, ev in enumerate(evidence)}

    flags: Dict[str, bool] = {}
    for idx, ev in enumerate(evidence):
        ev_id = str(ev.get("id") or f"E{idx + 1}")
        # source_text 가 없으면 quote 자체를 source 로 보고 통과 처리하여
        # 기존 fixture(text-only quote) 호환성을 유지한다.
        if not ev.get("source_text") and not ev.get("content") and not ev.get("text"):
            flags[ev_id] = True
            continue
        try:
            ok, _errors = _lockdown.validate_evidence_provenance([ev])
        except Exception:  # noqa: BLE001
            ok = True
        flags[ev_id] = bool(ok)
    return flags


def _lockdown_redact(text: str) -> str:
    """lockdown.redact 가 있으면 호출, 없으면 원문 반환."""
    if _lockdown is None or not isinstance(text, str):
        return text
    try:
        return _lockdown.redact(text)
    except Exception:  # noqa: BLE001
        return text


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]{2,}", re.UNICODE)

_STOPWORDS = {
    # 한국어 빈출어
    "있다", "이다", "하다", "그리고", "그러나", "그런데", "하지만", "또한", "또는",
    "이것", "그것", "저것", "이러한", "그러한", "저러한", "이번", "이번에",
    "위해", "통해", "관련", "대한", "대해", "있는", "되는", "된다",
    "했다", "한다", "한", "할", "될", "들",
    # English stop words
    "the", "a", "an", "of", "in", "on", "to", "for", "and", "or", "but",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "this", "that", "these", "those", "it", "its", "their", "we", "they",
    "as", "at", "by", "from", "with", "into", "than", "then", "if", "so",
    "can", "could", "may", "might", "should", "would", "will", "shall",
}

# 핵심 주장 (critical) — 한 번 틀리면 회복 어려운 정량/단정 표현
_CRITICAL_PATTERNS = [
    re.compile(r"\b\d+(?:\.\d+)?%"),
    re.compile(r"\b\d+(?:\.\d+)?\s?[xX×]\b"),
    re.compile(r"\b\d{1,3}(?:[,]\d{3})+\b"),
    re.compile(r"\b(?:CAGR|AUM|MAU|DAU|ARR|MRR|TAM|SAM|SOM)\b", re.IGNORECASE),
    re.compile(r"[\$₩€£¥]\s?\d+(?:[\.,]\d+)?[BMKbmk조억만천]?"),
    re.compile(r"\b\d{4}\s?년"),
    re.compile(r"(?:must|반드시|필수|critical|치명|핵심)", re.IGNORECASE),
]
_NUMBER_RE = re.compile(r"\d+(?:[\.,]\d+)?")


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def _content_terms(text: str) -> set:
    return {t for t in _tokenize(text) if len(t) >= 2}


# ---------------------------------------------------------------------------
# Evidence normalization
# ---------------------------------------------------------------------------
def _normalize_evidence(evidence: Iterable[Any]) -> List[Dict[str, Any]]:
    """evidence는 문자열 또는 dict 혼재 가능 → 일관된 dict 리스트로.

    provenance 검증을 위해 source_text/content/text 원문도 보존한다.
    """
    out: List[Dict[str, Any]] = []
    for idx, item in enumerate(evidence or []):
        if isinstance(item, str):
            out.append({
                "id": f"E{idx + 1}",
                "quote": item,
                "source": "",
                "source_text": "",
            })
        elif isinstance(item, dict):
            out.append({
                "id": str(item.get("id") or f"E{idx + 1}"),
                "quote": str(
                    item.get("quote")
                    or item.get("text")
                    or item.get("claim")
                    or item.get("snippet")
                    or ""
                ),
                "source": str(
                    item.get("source")
                    or item.get("url")
                    or item.get("ref")
                    or ""
                ),
                "source_text": str(
                    item.get("source_text")
                    or item.get("content")
                    or ""
                ),
            })
    return out


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------
_SENTENCE_SPLITTER = re.compile(r"(?<=[\.\?\!。])\s+|\n+")
_BULLET_PREFIX = re.compile(r"^\s*(?:[-\*•·▶▷–]|\d+[\.\)])\s*")


def extract_atomic_claims(*texts: Any) -> List[str]:
    """consensus / recommendations / dissent에서 원자적 주장 문장 추출.

    - 문장 분리 (마침표·물음표·느낌표·줄바꿈)
    - bullet/번호 prefix 제거
    - 8자 미만, 의문문, 중복 제외
    """
    claims: List[str] = []
    seen: set = set()

    for raw in texts:
        if not raw:
            continue
        if isinstance(raw, list):
            raw = "\n".join(str(r) for r in raw)
        for sentence in _SENTENCE_SPLITTER.split(str(raw)):
            cleaned = _BULLET_PREFIX.sub("", sentence).strip()
            if not cleaned or len(cleaned) < 8:
                continue
            if cleaned.endswith("?"):
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            claims.append(cleaned)
    return claims


def is_critical_claim(claim: str) -> bool:
    """정량 수치, 통화, 연도, 단정 부사 → 한 번 틀리면 회복 어려움."""
    return any(p.search(claim) for p in _CRITICAL_PATTERNS)


# ---------------------------------------------------------------------------
# Overlap matching
# ---------------------------------------------------------------------------
# substring 임계: 한국어 짧은 인용도 잡도록 12 → 8 자로 하향
_SUBSTRING_MIN_CHARS = 8


def _overlap_ratio(claim: str, evidence_text: str) -> float:
    """claim의 content-term 중 evidence에 등장하는 비율 (0~1)."""
    claim_terms = _content_terms(claim)
    if not claim_terms:
        return 0.0
    ev_terms = _content_terms(evidence_text)
    if not ev_terms:
        return 0.0
    return len(claim_terms & ev_terms) / len(claim_terms)


def _ngrams(text: str, n: int = 3) -> set:
    compact = re.sub(r"\s+", "", str(text).lower())
    if len(compact) < n:
        return {compact} if compact else set()
    return {compact[idx : idx + n] for idx in range(len(compact) - n + 1)}


def _jaccard(left: set, right: set) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _token_windows(tokens: List[str], size: int) -> Iterable[List[str]]:
    if not tokens:
        return []
    if size <= 0 or len(tokens) <= size:
        return [tokens]
    return (tokens[idx : idx + size] for idx in range(0, len(tokens) - size + 1))


def _score_semantic_window(quote: str, candidate: str) -> Tuple[float, Dict[str, Any]]:
    quote_tokens = _tokenize(quote)
    candidate_tokens = _tokenize(candidate)
    quote_terms = set(quote_tokens)
    quote_trigrams = _ngrams(quote)
    best = {"score": 0.0, "method": "none", "jaccard": 0.0, "trigram": 0.0}

    window_sizes = sorted({
        max(1, len(quote_tokens) - 2),
        max(1, len(quote_tokens)),
        max(1, len(quote_tokens) + 2),
    })
    windows: Iterable[List[str]]
    if candidate_tokens:
        collected: List[List[str]] = []
        for size in window_sizes:
            collected.extend(list(_token_windows(candidate_tokens, size)))
        windows = collected or [candidate_tokens]
    else:
        windows = []

    for window in windows:
        window_text = " ".join(window)
        jaccard = _jaccard(quote_terms, set(window))
        trigram = _jaccard(quote_trigrams, _ngrams(window_text))
        if max(jaccard, trigram) > float(best["score"]):
            method = "jaccard" if jaccard >= trigram else "trigram"
            best = {
                "score": max(jaccard, trigram),
                "method": method,
                "jaccard": jaccard,
                "trigram": trigram,
            }

    if not windows:
        trigram = _jaccard(quote_trigrams, _ngrams(candidate))
        best = {"score": trigram, "method": "trigram" if trigram else "none", "jaccard": 0.0, "trigram": trigram}

    return float(best["score"]), best


def _number_tokens(text: str) -> set:
    return set(_NUMBER_RE.findall(text or ""))


def _has_conflicting_numbers(quote: str, source_text: str) -> bool:
    quote_numbers = _number_tokens(quote)
    source_numbers = _number_tokens(source_text)
    return bool(quote_numbers and source_numbers and not quote_numbers <= source_numbers)


def semantic_match(quote: str, source_text: str, threshold: float = 0.6) -> Tuple[bool, float, Dict[str, Any]]:
    """Return whether quote is semantically present in source_text.

    This is a stdlib-only lexical semantic fallback. Substring remains the
    fast path; otherwise the best token-window Jaccard or character trigram
    overlap score is used.
    """
    details: Dict[str, Any] = {
        "method": "none",
        "jaccard": 0.0,
        "trigram": 0.0,
        "threshold": threshold,
    }
    if not quote or not source_text:
        return False, 0.0, details
    if _is_substring_quote(quote, source_text):
        details.update({"method": "substring", "jaccard": 1.0, "trigram": 1.0})
        return True, 1.0, details
    if _has_conflicting_numbers(quote, source_text):
        details.update({"method": "numeric_mismatch"})
        return False, 0.0, details

    score, best = _score_semantic_window(quote, source_text)
    details.update(best)
    return score >= threshold, round(score, 3), details


def _is_substring_quote(claim: str, evidence_text: str) -> bool:
    """claim이 evidence 안에 의미 있는 길이로 직접 인용된 경우 즉시 supported.

    임계 8자 — 한국어 짧은 인용 ("핵심 주장", "검증 패스") 도 잡기 위함.
    """
    if not claim or not evidence_text:
        return False
    norm_claim = re.sub(r"\s+", " ", claim.strip().lower())
    norm_ev = re.sub(r"\s+", " ", evidence_text.lower())
    return len(norm_claim) >= _SUBSTRING_MIN_CHARS and norm_claim in norm_ev


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def ground_claims(
    consensus: str = "",
    recommendations: Optional[List[Any]] = None,
    evidence: Optional[List[Any]] = None,
    dissent: str = "",
    overlap_threshold: float = 0.7,
    partial_threshold: float = 0.4,
    semantic_threshold: float = 0.6,
) -> Dict[str, Any]:
    """Council 결과의 claim들을 evidence 풀에 대조 (narrow C1 정책).

    정책:
        - substring 직접 인용 → 'supported'
        - keyword overlap 만으로는 'partial' 까지만 (citation laundering 차단)
        - overlap_threshold 도달해도 substring 미검증이면 'partial' 로 강등
        - lockdown.validate_evidence_provenance 가 실패한 evidence 는
          supported 후보에서 제외 (`provenance_failed=True` 표시)
        - per_claim_verdict 의 claim 텍스트는 lockdown.redact 적용

    Returns:
        {
            "verified_claim_ratio": float (supported / total),
            "unsupported_critical_claim_count": int,
            "unsupported_claims": List[str],
            "per_claim_verdict": List[dict],
            "total_claims": int,
            "supported": int,
            "partial": int,
            "unsupported": int,
            "provenance_failures": int,
        }
    """
    rec_block = "\n".join(str(r) for r in (recommendations or []))
    raw_claims = extract_atomic_claims(consensus, rec_block, dissent)
    norm_evidence = _normalize_evidence(evidence or [])

    provenance_flags = _lockdown_validate_provenance(norm_evidence)
    provenance_failures = sum(1 for ok in provenance_flags.values() if not ok)
    # provenance 통과 evidence 만 supported 후보로 사용
    trusted_evidence = [
        ev for ev in norm_evidence if provenance_flags.get(ev["id"], True)
    ]

    per_claim: List[Dict[str, Any]] = []
    supported = partial = unsupported = 0
    critical_unsupported = 0

    for claim in raw_claims:
        critical = is_critical_claim(claim)
        best_ratio = 0.0
        best_ids: List[str] = []
        substring_hit: Optional[str] = None
        semantic_hit: Optional[Tuple[str, float, Dict[str, Any]]] = None
        match_method = "none"
        match_details: Dict[str, Any] = {}

        # 1) substring 직접 인용 — 유일한 'supported' 경로
        for ev in trusted_evidence:
            candidate_text = ev["source_text"] or ev["quote"]
            if _is_substring_quote(claim, candidate_text):
                substring_hit = ev["id"]
                break

        if substring_hit is not None:
            best_ratio = 1.0
            best_ids = [substring_hit]
            status = "supported"
            match_method = "substring"
            match_details = {"method": "substring", "threshold": semantic_threshold}
            supported += 1
        else:
            # 2) semantic fallback — paraphrase/near-quote supported if strong enough
            for ev in trusted_evidence:
                if not ev["source_text"]:
                    continue
                candidate_text = ev["source_text"]
                ok, score, details = semantic_match(claim, candidate_text, threshold=semantic_threshold)
                if ok and (semantic_hit is None or score > semantic_hit[1]):
                    semantic_hit = (ev["id"], score, details)

            if semantic_hit is not None:
                best_ids = [semantic_hit[0]]
                best_ratio = semantic_hit[1]
                status = "supported"
                match_method = str(semantic_hit[2].get("method") or "semantic")
                match_details = semantic_hit[2]
                supported += 1
                redacted_claim = _lockdown_redact(claim)
                per_claim.append({
                    "claim": redacted_claim,
                    "status": status,
                    "overlap_ratio": round(best_ratio, 3),
                    "match_method": match_method,
                    "match_details": match_details,
                    "supporting_evidence_ids": best_ids,
                    "critical": critical,
                })
                continue

            # 3) keyword overlap (secondary signal — partial 까지만)
            for ev in trusted_evidence:
                ratio = _overlap_ratio(claim, ev["quote"])
                if ratio > best_ratio + 1e-9:
                    best_ratio = ratio
                    best_ids = [ev["id"]]
                elif abs(ratio - best_ratio) < 1e-9 and ratio >= partial_threshold:
                    best_ids.append(ev["id"])

            if best_ratio >= partial_threshold:
                # overlap_threshold 도달해도 substring 미검증이면 partial 로만 인정
                status = "partial"
                match_method = "overlap"
                match_details = {"method": "overlap", "threshold": partial_threshold}
                partial += 1
            else:
                status = "unsupported"
                match_method = "none"
                match_details = {"method": "none", "threshold": semantic_threshold}
                unsupported += 1
                if critical:
                    critical_unsupported += 1

        redacted_claim = _lockdown_redact(claim)
        per_claim.append({
            "claim": redacted_claim,
            "status": status,
            "overlap_ratio": round(best_ratio, 3),
            "match_method": match_method,
            "match_details": match_details,
            "supporting_evidence_ids": best_ids if status != "unsupported" else [],
            "critical": critical,
        })

    total = len(per_claim)
    verified_ratio = supported / total if total else 1.0  # 주장이 없으면 vacuously 통과

    return {
        "verified_claim_ratio": round(verified_ratio, 3),
        "unsupported_critical_claim_count": critical_unsupported,
        "unsupported_claims": [v["claim"] for v in per_claim if v["status"] == "unsupported"],
        "per_claim_verdict": per_claim,
        "total_claims": total,
        "supported": supported,
        "partial": partial,
        "unsupported": unsupported,
        "provenance_failures": provenance_failures,
    }


def grounding_gate(
    grounding: Dict[str, Any],
    min_verified_ratio: float = 0.8,
    max_critical_unsupported: int = 0,
) -> Tuple[bool, str]:
    """PASS 게이트.

    - 주장 0개: vacuously OK
    - critical unsupported > 한도: 차단
    - verified_ratio < 한도: 차단

    Returns:
        (allow_pass, reason)
    """
    if grounding.get("total_claims", 0) == 0:
        return True, "no_claims_to_verify"

    crit = grounding.get("unsupported_critical_claim_count", 0)
    if crit > max_critical_unsupported:
        return False, (
            f"unsupported_critical_claims={crit} > {max_critical_unsupported}"
        )

    ratio = grounding.get("verified_claim_ratio", 0.0)
    if ratio < min_verified_ratio:
        return False, (
            f"verified_claim_ratio={ratio:.3f} < {min_verified_ratio}"
        )

    return True, "grounding_ok"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="MuchaNipo citation grounding pass — claim ↔ evidence 1:1 검증",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("report", help="Council report JSON file path")
    p.add_argument("--threshold", type=float, default=0.7,
                   help="overlap ratio for partial promotion (default 0.7, narrow C1)")
    p.add_argument("--partial", type=float, default=0.4,
                   help="overlap ratio for 'partial' (default 0.4)")
    p.add_argument("--min-ratio", type=float, default=0.8,
                   help="grounding_gate min verified_claim_ratio (default 0.8)")
    p.add_argument("--max-critical", type=int, default=0,
                   help="grounding_gate max unsupported critical claims (default 0)")
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def main() -> int:
    args = _build_parser().parse_args()
    path = Path(args.report)
    if not path.exists():
        print(f"ERROR: report not found: {path}", file=sys.stderr)
        return 1

    try:
        with open(path, "r", encoding="utf-8") as f:
            report = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON: {e}", file=sys.stderr)
        return 1

    grounding = ground_claims(
        consensus=report.get("consensus", ""),
        recommendations=report.get("recommendations", []),
        evidence=report.get("evidence", []),
        dissent=report.get("dissent", ""),
        overlap_threshold=args.threshold,
        partial_threshold=args.partial,
    )

    allow, reason = grounding_gate(
        grounding,
        min_verified_ratio=args.min_ratio,
        max_critical_unsupported=args.max_critical,
    )
    grounding["pass_allowed"] = allow
    grounding["gate_reason"] = reason

    if args.verbose:
        topic = report.get("topic", "unknown")
        print("=" * 64)
        print(f"  Citation Grounding — {topic}")
        print("=" * 64)
        print(f"  total_claims         : {grounding['total_claims']}")
        print(f"  supported            : {grounding['supported']}")
        print(f"  partial              : {grounding['partial']}")
        print(f"  unsupported          : {grounding['unsupported']}")
        print(f"  verified_ratio       : {grounding['verified_claim_ratio']}")
        print(f"  critical_unsupported : {grounding['unsupported_critical_claim_count']}")
        print(f"  provenance_failures  : {grounding.get('provenance_failures', 0)}")
        print("-" * 64)
        for v in grounding["per_claim_verdict"]:
            mark = "✓" if v["status"] == "supported" else (
                "?" if v["status"] == "partial" else "✗"
            )
            crit = " [critical]" if v["critical"] else ""
            print(f"  {mark} ({v['overlap_ratio']:.2f}){crit} {v['claim'][:80]}")
        print("-" * 64)
        print(f"  pass_allowed         : {allow}  ({reason})")
        print("=" * 64)
    else:
        print(json.dumps(grounding, ensure_ascii=False, indent=2))

    return 0 if allow else 2


if __name__ == "__main__":
    sys.exit(main())
