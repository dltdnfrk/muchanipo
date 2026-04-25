#!/usr/bin/env python3
"""
MuchaNipo Citation Grounder — claim ↔ evidence 1:1 검증 패스
============================================================

Council Report의 consensus / recommendations / dissent 텍스트에서 원자적 claim을
뽑고, 각 claim을 evidence 풀에 대조해 supported / partial / unsupported 판정.

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


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def _content_terms(text: str) -> set:
    return {t for t in _tokenize(text) if len(t) >= 2}


# ---------------------------------------------------------------------------
# Evidence normalization
# ---------------------------------------------------------------------------
def _normalize_evidence(evidence: Iterable[Any]) -> List[Dict[str, str]]:
    """evidence는 문자열 또는 dict 혼재 가능 → 일관된 dict 리스트로."""
    out: List[Dict[str, str]] = []
    for idx, item in enumerate(evidence or []):
        if isinstance(item, str):
            out.append({"id": f"E{idx + 1}", "quote": item, "source": ""})
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
def _overlap_ratio(claim: str, evidence_text: str) -> float:
    """claim의 content-term 중 evidence에 등장하는 비율 (0~1)."""
    claim_terms = _content_terms(claim)
    if not claim_terms:
        return 0.0
    ev_terms = _content_terms(evidence_text)
    if not ev_terms:
        return 0.0
    return len(claim_terms & ev_terms) / len(claim_terms)


def _is_substring_quote(claim: str, evidence_text: str) -> bool:
    """claim이 evidence 안에 의미 있는 길이로 직접 인용된 경우 즉시 supported."""
    if not claim or not evidence_text:
        return False
    norm_claim = re.sub(r"\s+", " ", claim.strip().lower())
    norm_ev = re.sub(r"\s+", " ", evidence_text.lower())
    return len(norm_claim) >= 12 and norm_claim in norm_ev


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def ground_claims(
    consensus: str = "",
    recommendations: Optional[List[Any]] = None,
    evidence: Optional[List[Any]] = None,
    dissent: str = "",
    overlap_threshold: float = 0.6,
    partial_threshold: float = 0.4,
) -> Dict[str, Any]:
    """Council 결과의 claim들을 evidence 풀에 대조.

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
        }
    """
    rec_block = "\n".join(str(r) for r in (recommendations or []))
    raw_claims = extract_atomic_claims(consensus, rec_block, dissent)
    norm_evidence = _normalize_evidence(evidence or [])

    per_claim: List[Dict[str, Any]] = []
    supported = partial = unsupported = 0
    critical_unsupported = 0

    for claim in raw_claims:
        critical = is_critical_claim(claim)
        best_ratio = 0.0
        best_ids: List[str] = []

        # 직접 인용 우선
        substring_hit: Optional[str] = None
        for ev in norm_evidence:
            if _is_substring_quote(claim, ev["quote"]):
                substring_hit = ev["id"]
                break
        if substring_hit is not None:
            best_ratio = 1.0
            best_ids = [substring_hit]
        else:
            # term overlap
            for ev in norm_evidence:
                ratio = _overlap_ratio(claim, ev["quote"])
                if ratio > best_ratio + 1e-9:
                    best_ratio = ratio
                    best_ids = [ev["id"]]
                elif abs(ratio - best_ratio) < 1e-9 and ratio >= partial_threshold:
                    best_ids.append(ev["id"])

        if best_ratio >= overlap_threshold:
            status = "supported"
            supported += 1
        elif best_ratio >= partial_threshold:
            status = "partial"
            partial += 1
        else:
            status = "unsupported"
            unsupported += 1
            if critical:
                critical_unsupported += 1

        per_claim.append({
            "claim": claim,
            "status": status,
            "overlap_ratio": round(best_ratio, 3),
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
    p.add_argument("--threshold", type=float, default=0.6,
                   help="overlap ratio for 'supported' (default 0.6)")
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
