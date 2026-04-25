#!/usr/bin/env python3
"""
MuchaNipo Eval Agent -- Council 결과 자동 채점
==============================================
Council 토론 결과를 program.md 기반 루브릭으로 자동 채점하고
PASS/UNCERTAIN/FAIL로 라우팅한다.

Usage:
    python eval-agent.py <council-report.json>
    python eval-agent.py <council-report.json> --rubric rubric.json
    python eval-agent.py <council-report.json> --dry-run
    python eval-agent.py <council-report.json> --verbose

Routing:
    total >= 28  -> PASS       -> vault 저장 진행
    total 20-27  -> UNCERTAIN  -> signoff-queue 대기
    total < 20   -> FAIL       -> 폐기 + 로그
"""

import argparse
import importlib
import importlib.util
import json
import os
import sys
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
SIGNOFF_QUEUE_DIR = SCRIPT_DIR / "signoff-queue"
RUBRIC_HISTORY_DIR = SCRIPT_DIR / "rubric-history"
LOGS_DIR = SCRIPT_DIR / "logs"
CONFIG_PATH = SCRIPT_DIR / "config.json"


# ---------------------------------------------------------------------------
# Lazy imports — citation_grounder + lockdown
# ---------------------------------------------------------------------------
def _load_citation_grounder():
    """citation_grounder 를 lazy import. 실패하면 None 반환 (graceful)."""
    try:
        spec = importlib.util.spec_from_file_location(
            "citation_grounder", SCRIPT_DIR / "citation_grounder.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    except Exception:  # noqa: BLE001
        return None


def _load_lockdown():
    """src/safety/lockdown 을 optional import. 실패 시 None."""
    try:
        src_root = SCRIPT_DIR.parent
        if str(src_root) not in sys.path:
            sys.path.insert(0, str(src_root))
        from safety import lockdown as _lockdown  # type: ignore

        return _lockdown
    except Exception:  # noqa: BLE001
        return None

# Default vault base (expanduser handled at runtime)
DEFAULT_VAULT_BASE = Path.home() / "Documents" / "Hyunjun"

# ---------------------------------------------------------------------------
# Thresholds (from program.md / config.json)
# ---------------------------------------------------------------------------
THRESHOLD_PASS = 28
THRESHOLD_UNCERTAIN = 20


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------
def load_config() -> Dict[str, Any]:
    """Load config.json if available, return empty dict otherwise."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_rubric(rubric_path: Optional[str]) -> Dict[str, Any]:
    """Load a custom rubric file, or return default rubric."""
    if rubric_path and Path(rubric_path).exists():
        with open(rubric_path, "r", encoding="utf-8") as f:
            return json.load(f)
    # Default rubric from program.md
    return {
        "axes": ["usefulness", "reliability", "novelty", "actionability"],
        "thresholds": {
            "pass": THRESHOLD_PASS,
            "uncertain": THRESHOLD_UNCERTAIN,
        },
        "max_per_axis": 10,
    }


# ---------------------------------------------------------------------------
# Scoring engine (rule-based)
# ---------------------------------------------------------------------------
def score_usefulness(report: Dict[str, Any]) -> Tuple[int, str]:
    """Score usefulness: 의사결정/제품 구축에 도움이 되는가?"""
    score = 5  # baseline
    reasons = []

    recommendations = report.get("recommendations", [])
    if len(recommendations) >= 3:
        score += 2
        reasons.append(f"recommendations {len(recommendations)}개 (>= 3): +2")
    elif len(recommendations) >= 1:
        score += 1
        reasons.append(f"recommendations {len(recommendations)}개 (>= 1): +1")
    else:
        score -= 1
        reasons.append("recommendations 없음: -1")

    consensus = report.get("consensus", "")
    if len(consensus) > 200:
        score += 1
        reasons.append("consensus 상세 (200자 이상): +1")

    confidence = report.get("confidence", 0)
    if confidence >= 0.8:
        score += 1
        reasons.append(f"confidence {confidence:.2f} (>= 0.8): +1")

    # Check for concrete keywords indicating practical value
    all_text = consensus + " ".join(recommendations)
    action_keywords = ["구현", "적용", "도입", "전략", "implement", "deploy", "adopt", "strategy"]
    matches = [kw for kw in action_keywords if kw in all_text.lower()]
    if len(matches) >= 2:
        score += 1
        reasons.append(f"실용 키워드 {len(matches)}개: +1")

    return max(0, min(10, score)), "; ".join(reasons)


def score_reliability(report: Dict[str, Any]) -> Tuple[int, str]:
    """Score reliability: 출처가 명확한가? 검증 가능한가?"""
    score = 5  # baseline
    reasons = []

    evidence = report.get("evidence", [])
    if len(evidence) >= 5:
        score += 2
        reasons.append(f"evidence {len(evidence)}개 (>= 5): +2")
    elif len(evidence) >= 3:
        score += 1
        reasons.append(f"evidence {len(evidence)}개 (>= 3): +1")
    elif len(evidence) == 0:
        score -= 2
        reasons.append("evidence 없음: -2")

    confidence = report.get("confidence", 0)
    if confidence >= 0.7:
        score += 2
        reasons.append(f"confidence {confidence:.2f} (>= 0.7): +2")
    elif confidence >= 0.5:
        score += 1
        reasons.append(f"confidence {confidence:.2f} (>= 0.5): +1")
    elif confidence < 0.3:
        score -= 1
        reasons.append(f"confidence {confidence:.2f} (< 0.3): -1")

    # Persona consensus strength
    personas = report.get("personas", [])
    if personas:
        avg_persona_conf = sum(p.get("confidence", 0) for p in personas) / len(personas)
        if avg_persona_conf >= 0.7:
            score += 1
            reasons.append(f"평균 페르소나 confidence {avg_persona_conf:.2f} (>= 0.7): +1")
        elif avg_persona_conf < 0.3:
            score -= 1
            reasons.append(f"평균 페르소나 confidence {avg_persona_conf:.2f} (< 0.3): -1")

    return max(0, min(10, score)), "; ".join(reasons)


def score_novelty(report: Dict[str, Any]) -> Tuple[int, str]:
    """Score novelty: vault에 없는 새로운 정보인가?"""
    score = 5  # baseline
    reasons = []

    dissent = report.get("dissent", "")
    if not dissent or dissent.strip() == "":
        score -= 1
        reasons.append("dissent 없음 (토론 없이 동의 = 뻔한 내용): -1")
    elif len(dissent) > 100:
        score += 1
        reasons.append("dissent 상세 (활발한 토론 = 흥미로운 주제): +1")

    # More personas with diverse confidence = more nuanced topic
    personas = report.get("personas", [])
    if personas:
        confidences = [p.get("confidence", 0) for p in personas]
        if len(confidences) >= 2:
            spread = max(confidences) - min(confidences)
            if spread >= 0.3:
                score += 1
                reasons.append(f"페르소나 의견 다양성 높음 (spread {spread:.2f}): +1")
            elif spread < 0.1:
                score -= 1
                reasons.append(f"페르소나 의견 획일적 (spread {spread:.2f}): -1")

    if len(personas) >= 5:
        score += 1
        reasons.append(f"페르소나 {len(personas)}명 (>= 5, 다각적 분석): +1")

    # Topic complexity proxy: longer consensus = more complex topic
    consensus = report.get("consensus", "")
    if len(consensus) > 500:
        score += 1
        reasons.append("consensus 500자 초과 (복잡한 주제): +1")

    evidence = report.get("evidence", [])
    if len(evidence) >= 8:
        score += 1
        reasons.append(f"evidence {len(evidence)}개 (>= 8, 광범위 조사): +1")

    return max(0, min(10, score)), "; ".join(reasons)


def score_actionability(report: Dict[str, Any]) -> Tuple[int, str]:
    """Score actionability: 구체적 다음 단계가 있는가?"""
    score = 5  # baseline
    reasons = []

    recommendations = report.get("recommendations", [])
    if len(recommendations) >= 3:
        score += 2
        reasons.append(f"recommendations {len(recommendations)}개 (>= 3): +2")
    elif len(recommendations) >= 1:
        score += 1
        reasons.append(f"recommendations {len(recommendations)}개 (>= 1): +1")
    else:
        score -= 2
        reasons.append("recommendations 없음: -2")

    # Check if recommendations are concrete (have sufficient detail)
    if recommendations:
        avg_len = sum(len(r) for r in recommendations) / len(recommendations)
        if avg_len > 50:
            score += 1
            reasons.append(f"recommendations 평균 {avg_len:.0f}자 (상세): +1")
        elif avg_len < 15:
            score -= 1
            reasons.append(f"recommendations 평균 {avg_len:.0f}자 (너무 짧음): -1")

    confidence = report.get("confidence", 0)
    if confidence >= 0.8:
        score += 1
        reasons.append(f"높은 confidence {confidence:.2f} → 실행 가능성 높음: +1")

    # Specific action verbs in recommendations
    action_verbs = ["테스트", "구현", "검증", "배포", "분석", "조사", "작성", "연락",
                     "test", "build", "verify", "deploy", "analyze", "contact", "write"]
    if recommendations:
        all_recs = " ".join(recommendations).lower()
        verb_matches = [v for v in action_verbs if v in all_recs]
        if len(verb_matches) >= 2:
            score += 1
            reasons.append(f"구체적 행동 동사 {len(verb_matches)}개: +1")

    return max(0, min(10, score)), "; ".join(reasons)


def score_completeness(report: Dict[str, Any]) -> Tuple[int, str]:
    """Score completeness: 주제의 모든 핵심 측면을 빠짐없이 다루는가?"""
    score = 5
    reasons = []

    consensus = report.get("consensus", "")
    dissent = report.get("dissent", "")
    recommendations = report.get("recommendations", [])

    # Longer consensus + dissent = more comprehensive
    combined_len = len(consensus) + len(dissent)
    if combined_len > 1000:
        score += 2
        reasons.append(f"합의+이견 {combined_len}자 (>= 1000, 포괄적): +2")
    elif combined_len > 500:
        score += 1
        reasons.append(f"합의+이견 {combined_len}자 (>= 500): +1")
    elif combined_len < 100:
        score -= 2
        reasons.append(f"합의+이견 {combined_len}자 (< 100, 불충분): -2")

    # Multiple recommendation areas
    if len(recommendations) >= 10:
        score += 2
        reasons.append(f"recommendations {len(recommendations)}개 (>= 10, 광범위): +2")
    elif len(recommendations) >= 5:
        score += 1
        reasons.append(f"recommendations {len(recommendations)}개 (>= 5): +1")

    # Web research adds completeness
    web_research = report.get("web_research", [])
    if len(web_research) >= 2:
        score += 1
        reasons.append(f"웹리서치 {len(web_research)}건 (보완 조사): +1")

    return max(0, min(10, score)), "; ".join(reasons)


def score_evidence_quality(report: Dict[str, Any]) -> Tuple[int, str]:
    """Score evidence quality: 인용 출처가 신뢰할 수 있고 다양한가?"""
    score = 5
    reasons = []

    evidence = report.get("evidence", [])
    if len(evidence) >= 10:
        score += 3
        reasons.append(f"evidence {len(evidence)}개 (>= 10, 매우 풍부): +3")
    elif len(evidence) >= 5:
        score += 2
        reasons.append(f"evidence {len(evidence)}개 (>= 5): +2")
    elif len(evidence) >= 3:
        score += 1
        reasons.append(f"evidence {len(evidence)}개 (>= 3): +1")
    elif len(evidence) == 0:
        score -= 3
        reasons.append("evidence 없음: -3")

    # Check for diverse source types (papers, patents, policies, etc.)
    # evidence 는 string 또는 dict 혼재 가능 — 안전 coerce
    def _ev_text(item: Any) -> str:
        if isinstance(item, dict):
            return " ".join(
                str(item.get(k) or "") for k in ("quote", "text", "source", "snippet")
            )
        return str(item)

    all_evidence = " ".join(_ev_text(e) for e in evidence).lower()
    source_types = ["논문", "특허", "patent", "pct", "법", "조사", "sci", "doi", "pmid"]
    type_matches = [s for s in source_types if s in all_evidence]
    if len(type_matches) >= 3:
        score += 1
        reasons.append(f"출처 유형 다양 ({len(type_matches)}종): +1")

    # Web research sources count
    web_research = report.get("web_research", [])
    total_web_sources = sum(r.get("sources", 0) for r in web_research)
    if total_web_sources >= 20:
        score += 1
        reasons.append(f"웹리서치 출처 {total_web_sources}개 (>= 20): +1")

    return max(0, min(10, score)), "; ".join(reasons)


def score_perspective_diversity(report: Dict[str, Any]) -> Tuple[int, str]:
    """Score perspective diversity: 다양한 이해관계자 관점이 반영되었는가?"""
    score = 5
    reasons = []

    personas = report.get("personas", [])
    active = [p for p in personas if p.get("confidence", 0) > 0]

    if len(active) >= 10:
        score += 3
        reasons.append(f"활성 페르소나 {len(active)}명 (>= 10): +3")
    elif len(active) >= 5:
        score += 2
        reasons.append(f"활성 페르소나 {len(active)}명 (>= 5): +2")
    elif len(active) >= 3:
        score += 1
        reasons.append(f"활성 페르소나 {len(active)}명 (>= 3): +1")

    # Layer diversity
    layers = set(p.get("layer", 1) for p in active)
    if len(layers) >= 3:
        score += 2
        reasons.append(f"Layer {len(layers)}개 (L1+L2+L3 다층): +2")
    elif len(layers) >= 2:
        score += 1
        reasons.append(f"Layer {len(layers)}개: +1")

    return max(0, min(10, score)), "; ".join(reasons)


def score_coherence(report: Dict[str, Any]) -> Tuple[int, str]:
    """Score coherence: 합의와 권고가 논리적으로 일관되는가?"""
    score = 5
    reasons = []

    consensus = report.get("consensus", "")
    recommendations = report.get("recommendations", [])

    # Consensus length as proxy for structured reasoning
    if len(consensus) >= 200:
        score += 1
        reasons.append(f"consensus {len(consensus)}자 (>= 200, 구조적): +1")

    # Recommendations that reference specific findings
    if recommendations:
        all_recs = " ".join(recommendations)
        reference_markers = ["R1", "R2", "C1", "C2", "Round", "발견", "분석"]
        refs = [m for m in reference_markers if m in all_recs]
        if len(refs) >= 2:
            score += 1
            reasons.append(f"권고가 발견사항 참조 ({len(refs)}건): +1")

    # Confidence level indicates internal agreement
    confidence = report.get("confidence", 0)
    if confidence >= 0.75:
        score += 2
        reasons.append(f"높은 합의 confidence {confidence:.2f}: +2")
    elif confidence >= 0.6:
        score += 1
        reasons.append(f"적정 합의 confidence {confidence:.2f}: +1")
    elif confidence < 0.4:
        score -= 1
        reasons.append(f"낮은 합의 confidence {confidence:.2f}: -1")

    # Dissent is explicitly captured (shows honest analysis)
    dissent = report.get("dissent", "")
    if len(dissent) > 200:
        score += 1
        reasons.append("이견 명시적 기록 (솔직한 분석): +1")

    return max(0, min(10, score)), "; ".join(reasons)


def score_depth(report: Dict[str, Any]) -> Tuple[int, str]:
    """Score depth: 피상적 분석이 아닌 근본 원인까지 파고드는 분석인가?"""
    score = 5
    reasons = []

    # Web research indicates deeper investigation
    web_research = report.get("web_research", [])
    if len(web_research) >= 3:
        score += 2
        reasons.append(f"웹리서치 {len(web_research)}건 (깊은 조사): +2")
    elif len(web_research) >= 1:
        score += 1
        reasons.append(f"웹리서치 {len(web_research)}건: +1")

    # Round number indicates iterative deepening
    round_num = report.get("round", 1)
    if round_num >= 2:
        score += 1
        reasons.append(f"Round {round_num} (반복 심화): +1")

    # Long dissent with structural markers
    dissent = report.get("dissent", "")
    structural = ["Critical", "Major", "Minor", "치명적", "핵심"]
    struct_matches = [s for s in structural if s in dissent]
    if len(struct_matches) >= 2:
        score += 1
        reasons.append(f"구조적 이견 분류 ({len(struct_matches)}단계): +1")

    # Many evidence items = deeper research
    evidence = report.get("evidence", [])
    if len(evidence) >= 10:
        score += 1
        reasons.append(f"evidence {len(evidence)}개 (심층 조사): +1")

    return max(0, min(10, score)), "; ".join(reasons)


def score_impact(report: Dict[str, Any]) -> Tuple[int, str]:
    """Score impact: 권고가 실행되면 실질적 변화를 만들 수 있는가?"""
    score = 5
    reasons = []

    recommendations = report.get("recommendations", [])
    if len(recommendations) >= 10:
        score += 2
        reasons.append(f"recommendations {len(recommendations)}개 (>= 10, 포괄적): +2")
    elif len(recommendations) >= 5:
        score += 1
        reasons.append(f"recommendations {len(recommendations)}개 (>= 5): +1")

    # Priority/urgency markers in recommendations
    if recommendations:
        all_recs = " ".join(recommendations)
        urgency = ["긴급", "즉시", "필수", "critical", "urgent", "must"]
        urg_matches = [u for u in urgency if u in all_recs.lower()]
        if len(urg_matches) >= 1:
            score += 1
            reasons.append(f"우선순위 표시 ({len(urg_matches)}건): +1")

        # Specific numbers/metrics in recommendations
        import re
        numbers = re.findall(r'\d+[%점건개명]', all_recs)
        if len(numbers) >= 3:
            score += 1
            reasons.append(f"정량적 권고 ({len(numbers)}건): +1")

    # High confidence = higher expected impact
    confidence = report.get("confidence", 0)
    if confidence >= 0.75:
        score += 1
        reasons.append(f"높은 confidence {confidence:.2f} → 실행 가치 높음: +1")

    return max(0, min(10, score)), "; ".join(reasons)


def _run_citation_grounding(report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """citation_grounder 가 있으면 ground_claims 결과 dict, 없으면 None."""
    grounder = _load_citation_grounder()
    if grounder is None:
        return None
    try:
        return grounder.ground_claims(
            consensus=report.get("consensus", ""),
            recommendations=report.get("recommendations", []),
            evidence=report.get("evidence", []),
            dissent=report.get("dissent", ""),
        )
    except Exception:  # noqa: BLE001
        return None


def _apply_grounding_gate(
    grounding: Dict[str, Any],
    rubric: Dict[str, Any],
    verdict: str,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """rubric.grounding_gate 설정에 따라 PASS 를 UNCERTAIN 으로 강등한다.

    Returns:
        (new_verdict, gate_decision_dict_or_None)
    """
    gate_cfg = rubric.get("grounding_gate") or {}
    if not gate_cfg.get("enabled"):
        return verdict, None
    if verdict != "PASS":
        return verdict, None

    grounder = _load_citation_grounder()
    if grounder is None:
        return verdict, None

    min_ratio = gate_cfg.get("min_verified_ratio", 0.8)
    max_crit = gate_cfg.get("max_critical_unsupported", 0)
    allow, reason = grounder.grounding_gate(
        grounding,
        min_verified_ratio=min_ratio,
        max_critical_unsupported=max_crit,
    )

    decision = {
        "enabled": True,
        "allow_pass": allow,
        "reason": reason,
        "min_verified_ratio": min_ratio,
        "max_critical_unsupported": max_crit,
    }

    if not allow and gate_cfg.get("demote_pass_to_uncertain"):
        decision["demoted"] = True
        return "UNCERTAIN", decision

    decision["demoted"] = False
    return verdict, decision


def _citation_fidelity_score(
    rubric: Dict[str, Any],
    grounding: Optional[Dict[str, Any]],
) -> Tuple[int, str]:
    """citation_fidelity 축 점수 계산.

    weight 0 → score 0 (점수 영향 없음, 측정 데이터로만 누적)
    weight > 0 → verified_claim_ratio × max 환산
    """
    axes = rubric.get("axes", {}) or {}
    if not isinstance(axes, dict):
        return 0, "axes config not dict — citation_fidelity skipped"
    cf = axes.get("citation_fidelity")
    if not isinstance(cf, dict):
        return 0, "citation_fidelity axis 미정의"

    weight = float(cf.get("weight", 0.0) or 0.0)
    max_score = int(cf.get("max", 10))

    if grounding is None:
        return 0, "grounding 미실행 (citation_grounder 부재 또는 실패)"

    ratio = float(grounding.get("verified_claim_ratio", 0.0) or 0.0)
    if weight <= 0.0:
        return 0, (
            f"weight=0.0 → 점수 영향 없음 (verified_ratio={ratio:.2f}, 측정 누적용)"
        )

    score = int(round(ratio * max_score))
    return max(0, min(max_score, score)), (
        f"verified_ratio={ratio:.2f} × max={max_score} → {score}"
    )


def evaluate(report: Dict[str, Any], rubric: Dict[str, Any]) -> Dict[str, Any]:
    """Run the full evaluation on a council report."""
    scorers = {
        "usefulness": score_usefulness,
        "reliability": score_reliability,
        "novelty": score_novelty,
        "actionability": score_actionability,
        "completeness": score_completeness,
        "evidence_quality": score_evidence_quality,
        "perspective_diversity": score_perspective_diversity,
        "coherence": score_coherence,
        "depth": score_depth,
        "impact": score_impact,
    }

    scores: Dict[str, int] = {}
    reasoning_parts = []

    for axis in rubric.get("axes", scorers.keys()):
        if axis in scorers:
            val, reason = scorers[axis](report)
            scores[axis] = val
            reasoning_parts.append(f"[{axis}={val}] {reason}")

    # citation grounding 패스 (verdict 계산 직후 게이트 적용 위해 미리 실행)
    grounding = _run_citation_grounding(report)

    # citation_fidelity 점수 (weight 0 → 0, > 0 → 환산)
    cf_score, cf_reason = _citation_fidelity_score(rubric, grounding)
    axes_cfg = rubric.get("axes", {})
    if isinstance(axes_cfg, dict) and "citation_fidelity" in axes_cfg:
        scores["citation_fidelity"] = cf_score
        reasoning_parts.append(f"[citation_fidelity={cf_score}] {cf_reason}")

    total = sum(scores.values())

    thresholds = rubric.get("thresholds", {})
    pass_threshold = thresholds.get("pass", THRESHOLD_PASS)
    uncertain_threshold = thresholds.get("uncertain", THRESHOLD_UNCERTAIN)

    if total >= pass_threshold:
        verdict = "PASS"
    elif total >= uncertain_threshold:
        verdict = "UNCERTAIN"
    else:
        verdict = "FAIL"

    # grounding gate — PASS 일 때만 적용, demote_pass_to_uncertain 가능
    new_verdict, gate_decision = _apply_grounding_gate(grounding or {}, rubric, verdict)
    if gate_decision is not None and new_verdict != verdict:
        reasoning_parts.append(
            f"[grounding_gate=demoted] {verdict} → {new_verdict} ({gate_decision.get('reason')})"
        )
    verdict = new_verdict

    # lockdown audit log (gate 결정 추적)
    if gate_decision is not None:
        lockdown = _load_lockdown()
        if lockdown is not None:
            try:
                lockdown.audit_log(
                    "grounding_gate",
                    {
                        "council_id": report.get("council_id", "unknown"),
                        "topic": report.get("topic", "unknown"),
                        "decision": gate_decision,
                    },
                )
            except Exception:  # noqa: BLE001
                pass

    return {
        "council_id": report.get("council_id", "unknown"),
        "topic": report.get("topic", "unknown"),
        "scores": scores,
        "total": total,
        "verdict": verdict,
        "reasoning": "\n".join(reasoning_parts),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rubric_version": rubric.get("version", "v1"),
        "grounding": grounding or {},
        "grounding_gate_decision": gate_decision or {},
    }


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
def resolve_vault_path(report: Dict[str, Any]) -> Path:
    """Determine the vault destination based on topic/interest axis."""
    config = load_config()
    axes = config.get("interest_axes", [])

    topic = report.get("topic", "").lower()

    for axis in axes:
        keywords = [kw.lower() for kw in axis.get("keywords", [])]
        if any(kw in topic for kw in keywords):
            vault_path = axis.get("vault_path", "")
            expanded = Path(os.path.expanduser(vault_path))
            if expanded.exists():
                return expanded

    # Default: Feed directory for uncategorized research
    feed_path = DEFAULT_VAULT_BASE / "Feed"
    feed_path.mkdir(parents=True, exist_ok=True)
    return feed_path


def route_pass(report: Dict[str, Any], eval_result: Dict[str, Any], dry_run: bool = False) -> str:
    """PASS -> prepare for vault storage."""
    vault_dir = resolve_vault_path(report)
    topic_slug = report.get("topic", "untitled").replace(" ", "-").lower()[:50]
    date_str = datetime.now().strftime("%Y-%m-%d")
    filename = f"{date_str}-{topic_slug}.json"
    dest = vault_dir / filename

    if dry_run:
        return f"[DRY-RUN] PASS: would save to {dest}"

    # Save council report + eval result together
    output = {
        "council_report": report,
        "eval_result": eval_result,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return f"PASS: saved to {dest}"


def route_uncertain(report: Dict[str, Any], eval_result: Dict[str, Any], dry_run: bool = False) -> str:
    """UNCERTAIN -> signoff-queue."""
    SIGNOFF_QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    sq_id = f"sq-{ts}"

    entry = {
        "id": sq_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "topic": report.get("topic", "unknown"),
        "council_id": report.get("council_id", "unknown"),
        "eval_result": eval_result,
        "council_report": report,
        "status": "pending",
    }

    if dry_run:
        return f"[DRY-RUN] UNCERTAIN: would queue as {sq_id}"

    dest = SIGNOFF_QUEUE_DIR / f"{sq_id}.json"
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)

    return f"UNCERTAIN: queued as {sq_id} -> {dest}"


def route_fail(report: Dict[str, Any], eval_result: Dict[str, Any], dry_run: bool = False) -> str:
    """FAIL -> discard + log."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = LOGS_DIR / f"eval-fail-{ts}.json"

    entry = {
        "council_id": report.get("council_id", "unknown"),
        "topic": report.get("topic", "unknown"),
        "eval_result": eval_result,
        "discarded_at": datetime.now(timezone.utc).isoformat(),
    }

    if dry_run:
        return f"[DRY-RUN] FAIL: would discard and log to {log_file}"

    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=2)

    return f"FAIL: discarded, logged to {log_file}"


def route(report: Dict[str, Any], eval_result: Dict[str, Any], dry_run: bool = False) -> str:
    """Route eval result to the appropriate destination."""
    verdict = eval_result.get("verdict", "FAIL")
    routers = {
        "PASS": route_pass,
        "UNCERTAIN": route_uncertain,
        "FAIL": route_fail,
    }
    router = routers.get(verdict, route_fail)
    return router(report, eval_result, dry_run)


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------
def _extract_replay_report(item: Dict[str, Any]) -> Dict[str, Any]:
    """Accept plain council reports or wrapper JSONL rows from build-replay-set."""
    if isinstance(item.get("council_report"), dict):
        return item["council_report"]
    if isinstance(item.get("report"), dict):
        return item["report"]
    return item


def run_replay(
    replay_path: Path,
    rubric: Dict[str, Any],
    output_path: Path,
) -> Tuple[int, int]:
    """Re-evaluate council reports from JSONL and write a TSV summary."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    failed = 0

    with open(replay_path, "r", encoding="utf-8") as replay, open(
        output_path, "w", encoding="utf-8"
    ) as out:
        out.write("line\tcouncil_id\ttopic\ttotal\tverdict\terror\n")
        for line_no, line in enumerate(replay, 1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                item = json.loads(line)
                report = _extract_replay_report(item)
                result = evaluate(report, rubric)
                out.write(
                    "\t".join(
                        [
                            str(line_no),
                            str(result.get("council_id", "unknown")),
                            str(result.get("topic", "unknown")).replace("\t", " "),
                            str(result.get("total", 0)),
                            str(result.get("verdict", "FAIL")),
                            "",
                        ]
                    )
                    + "\n"
                )
            except Exception as exc:
                failed += 1
                out.write(
                    f"{line_no}\tunknown\tunknown\t0\tERROR\t{type(exc).__name__}: {exc}\n"
                )

    return total, failed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MuchaNipo Eval Agent -- Council 결과 자동 채점",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python eval-agent.py council-report.json
  python eval-agent.py council-report.json --rubric custom-rubric.json
  python eval-agent.py council-report.json --dry-run --verbose
  python eval-agent.py council-report.json --output-only
  python eval-agent.py --replay recent-N.jsonl
        """,
    )
    parser.add_argument(
        "report",
        nargs="?",
        help="Council report JSON file path",
    )
    parser.add_argument(
        "--rubric",
        default=None,
        help="Custom rubric JSON file (default: built-in from program.md)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate without routing (no file writes except eval result)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed scoring breakdown",
    )
    parser.add_argument(
        "--output-only",
        action="store_true",
        help="Print eval result JSON to stdout (no routing, no side effects)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Write eval result to this file path",
    )
    parser.add_argument(
        "--replay",
        default=None,
        help="Replay a JSONL file of council reports and write replay-summary.tsv",
    )
    parser.add_argument(
        "--replay-output",
        default="replay-summary.tsv",
        help="Replay summary TSV path (default: replay-summary.tsv)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    rubric = load_rubric(args.rubric)

    if args.replay:
        replay_path = Path(args.replay)
        if not replay_path.exists():
            print(f"ERROR: Replay file not found: {replay_path}", file=sys.stderr)
            return 1
        total, failed = run_replay(replay_path, rubric, Path(args.replay_output))
        print(
            f"Replay complete: {total} item(s), {failed} error(s) -> {args.replay_output}"
        )
        return 0 if failed == 0 else 2

    # Load council report
    if not args.report:
        parser.print_help()
        return 1

    report_path = Path(args.report)
    if not report_path.exists():
        print(f"ERROR: Council report not found: {report_path}", file=sys.stderr)
        return 1

    try:
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {report_path}: {e}", file=sys.stderr)
        return 1

    # Validate required fields
    required_fields = ["topic", "council_id", "consensus"]
    missing = [f for f in required_fields if f not in report]
    if missing:
        print(f"ERROR: Missing required fields in report: {missing}", file=sys.stderr)
        return 1

    # Evaluate
    eval_result = evaluate(report, rubric)

    # Output
    if args.verbose:
        print("=" * 60)
        print(f"  MuchaNipo Eval Agent -- {report.get('topic', 'unknown')}")
        print("=" * 60)
        print(f"  Council ID: {eval_result['council_id']}")
        print(f"  Timestamp:  {eval_result['timestamp']}")
        print("-" * 60)
        for axis, val in eval_result["scores"].items():
            print(f"  {axis:15s}: {val:2d}/10")
        print("-" * 60)
        max_score = sum(a.get("max", 10) for a in rubric.get("axes", {}).values()) if isinstance(rubric.get("axes"), dict) else len(rubric.get("axes", [])) * 10
        print(f"  {'TOTAL':15s}: {eval_result['total']:2d}/{max_score}")
        print(f"  {'VERDICT':15s}: {eval_result['verdict']}")
        print("-" * 60)
        print("  Reasoning:")
        for line in eval_result["reasoning"].split("\n"):
            print(f"    {line}")
        # citation grounding 결과 (있을 때만)
        grounding = eval_result.get("grounding") or {}
        if grounding:
            print("-" * 60)
            print("  Citation Grounding:")
            print(f"    total_claims         : {grounding.get('total_claims', 0)}")
            print(f"    supported            : {grounding.get('supported', 0)}")
            print(f"    partial              : {grounding.get('partial', 0)}")
            print(f"    unsupported          : {grounding.get('unsupported', 0)}")
            print(f"    verified_ratio       : {grounding.get('verified_claim_ratio', 0)}")
            print(f"    critical_unsupported : {grounding.get('unsupported_critical_claim_count', 0)}")
            print(f"    provenance_failures  : {grounding.get('provenance_failures', 0)}")
            decision = eval_result.get("grounding_gate_decision") or {}
            if decision:
                print(
                    f"    gate                 : allow={decision.get('allow_pass')} "
                    f"demoted={decision.get('demoted')} reason={decision.get('reason')}"
                )
        print("=" * 60)
    else:
        print(json.dumps(eval_result, ensure_ascii=False, indent=2))

    # Write eval result to file if requested
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(eval_result, f, ensure_ascii=False, indent=2)
        print(f"\nEval result saved to: {output_path}", file=sys.stderr)

    # Route (unless output-only or dry-run suppresses it)
    if args.output_only:
        return 0

    route_msg = route(report, eval_result, dry_run=args.dry_run)
    print(f"\n{route_msg}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
