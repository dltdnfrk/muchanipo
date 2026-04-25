#!/usr/bin/env python3
"""
MuchaNipo Rubric Learner -- 사용자 피드백 기반 채점 기준 자동 조정

Usage:
  python rubric-learner.py analyze                 # 현재 피드백 패턴 분석
  python rubric-learner.py evolve                  # rubric 업데이트 제안
  python rubric-learner.py apply                   # 제안된 변경 적용
  python rubric-learner.py history                 # rubric 변경 이력
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
RUBRIC_PATH = BASE_DIR / "rubric.json"
FEEDBACK_PATH = BASE_DIR / "rubric-feedback.jsonl"
HISTORY_DIR = BASE_DIR / "rubric-history"
PROPOSAL_PATH = BASE_DIR / "rubric-proposal.json"

AXES = ("usefulness", "reliability", "novelty", "actionability")


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_rubric() -> Dict[str, Any]:
    """rubric.json 로드. 없으면 에러."""
    if not RUBRIC_PATH.exists():
        print(f"ERROR: rubric 파일이 없습니다: {RUBRIC_PATH}")
        sys.exit(1)
    with open(RUBRIC_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_rubric(rubric: Dict[str, Any]) -> None:
    """rubric.json 저장."""
    with open(RUBRIC_PATH, "w", encoding="utf-8") as f:
        json.dump(rubric, f, indent=2, ensure_ascii=False)
        f.write("\n")


def load_feedback() -> List[Dict[str, Any]]:
    """rubric-feedback.jsonl 로드. 없거나 비어 있으면 빈 리스트 반환."""
    if not FEEDBACK_PATH.exists():
        return []
    entries: List[Dict[str, Any]] = []
    with open(FEEDBACK_PATH, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"WARNING: {FEEDBACK_PATH}:{lineno} 파싱 실패, 건너뜀")
    return entries


def save_proposal(proposal: Dict[str, Any]) -> None:
    """제안(proposal) 파일 저장."""
    with open(PROPOSAL_PATH, "w", encoding="utf-8") as f:
        json.dump(proposal, f, indent=2, ensure_ascii=False)
        f.write("\n")


def load_proposal() -> Optional[Dict[str, Any]]:
    """제안 파일 로드."""
    if not PROPOSAL_PATH.exists():
        return None
    with open(PROPOSAL_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def backup_rubric(rubric: Dict[str, Any]) -> Path:
    """현재 rubric을 rubric-history/에 타임스탬프 파일로 백업."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    version = rubric.get("version", "unknown")
    backup_path = HISTORY_DIR / f"rubric-{ts}-v{version}.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(rubric, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return backup_path


# ---------------------------------------------------------------------------
# classify: 점수 → 판정 (현재 rubric 기준)
# ---------------------------------------------------------------------------

def classify_score(total: float, rubric: Dict[str, Any]) -> str:
    """점수를 PASS/UNCERTAIN/FAIL로 분류."""
    thresholds = rubric["thresholds"]
    if total >= thresholds["pass"]:
        return "PASS"
    elif total >= thresholds["uncertain_min"]:
        return "UNCERTAIN"
    else:
        return "FAIL"


def compute_weighted_total(scores: Dict[str, float], rubric: Dict[str, Any]) -> float:
    """가중치 적용 총점 계산."""
    axes = rubric.get("axes", {})
    total = 0.0
    for axis_name in AXES:
        raw = scores.get(axis_name, 0.0)
        weight = axes.get(axis_name, {}).get("weight", 1.0)
        total += raw * weight
    return total


# ---------------------------------------------------------------------------
# analyze 명령
# ---------------------------------------------------------------------------

def cmd_analyze(args: argparse.Namespace) -> None:
    """피드백 패턴 분석."""
    rubric = load_rubric()
    feedback = load_feedback()

    if not feedback:
        print("피드백 데이터가 없습니다.")
        print(f"  피드백 파일: {FEEDBACK_PATH}")
        print("  피드백 형식 (JSONL, 한 줄에 하나):")
        print('  {"action":"approve","total_score":25,"scores":{"usefulness":7,"reliability":6,"novelty":6,"actionability":6},"classification":"UNCERTAIN","topic":"AI agent","interest_axis":"ai_ml","reason":"","timestamp":"2026-04-09T12:00:00"}')
        return

    total = len(feedback)
    actions = defaultdict(int)
    scores_by_action: Dict[str, List[float]] = defaultdict(list)
    axis_scores_by_action: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    classification_actions: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    axis_reject_reasons: Dict[str, int] = defaultdict(int)
    interest_axis_reject: Dict[str, int] = defaultdict(int)
    interest_axis_total: Dict[str, int] = defaultdict(int)

    # 구간 정의 (FAIL: <20, UNCERTAIN: 20-27, PASS: 28+)
    score_bins = {"FAIL (<20)": (0, 20), "UNCERTAIN (20-27)": (20, 28), "PASS (28+)": (28, 100)}
    bin_actions: Dict[str, Dict[str, int]] = {
        b: defaultdict(int) for b in score_bins
    }

    for entry in feedback:
        action = entry.get("action", "unknown")
        actions[action] += 1

        t_score = entry.get("total_score", 0)
        scores_by_action[action].append(t_score)

        # 축별 점수
        scores = entry.get("scores", {})
        for axis in AXES:
            if axis in scores:
                axis_scores_by_action[action][axis].append(scores[axis])

        # 분류별 action 분포
        cls = entry.get("classification", classify_score(t_score, rubric))
        classification_actions[cls][action] += 1

        # 점수 구간별 action 분포
        for bin_name, (lo, hi) in score_bins.items():
            if lo <= t_score < hi:
                bin_actions[bin_name][action] += 1
                break

        # 관심축별 reject 비율
        ia = entry.get("interest_axis", "unknown")
        interest_axis_total[ia] += 1
        if action == "reject":
            interest_axis_reject[ia] += 1

        # reject 사유 키워드
        if action == "reject":
            reason = entry.get("reason", "")
            if reason:
                for kw in _extract_reason_keywords(reason):
                    axis_reject_reasons[kw] += 1

    # 출력
    print("=" * 60)
    print("  MuchaNipo Rubric Feedback Analysis")
    print("=" * 60)
    print(f"\n총 피드백 수: {total}")
    for act in ("approve", "reject", "modify"):
        cnt = actions.get(act, 0)
        pct = cnt / total * 100 if total else 0
        print(f"  {act:>8}: {cnt:>4} ({pct:.1f}%)")

    print(f"\n현재 rubric 버전: {rubric.get('version', '?')}")
    print(f"  PASS 임계값: {rubric['thresholds']['pass']}")
    print(f"  UNCERTAIN 하한: {rubric['thresholds']['uncertain_min']}")

    # 액션별 평균 점수
    print("\n--- 액션별 평균 점수 ---")
    for act in ("approve", "reject", "modify"):
        vals = scores_by_action.get(act, [])
        if vals:
            avg = sum(vals) / len(vals)
            mn, mx = min(vals), max(vals)
            print(f"  {act:>8}: avg={avg:.1f}  min={mn:.0f}  max={mx:.0f}  n={len(vals)}")

    # 축별 평균
    print("\n--- 축별 평균 점수 (approve vs reject) ---")
    header = f"  {'축':<16} {'approve avg':>12} {'reject avg':>12} {'차이':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for axis in AXES:
        app_vals = axis_scores_by_action.get("approve", {}).get(axis, [])
        rej_vals = axis_scores_by_action.get("reject", {}).get(axis, [])
        app_avg = sum(app_vals) / len(app_vals) if app_vals else 0
        rej_avg = sum(rej_vals) / len(rej_vals) if rej_vals else 0
        diff = app_avg - rej_avg
        print(f"  {axis:<16} {app_avg:>12.1f} {rej_avg:>12.1f} {diff:>+8.1f}")

    # 점수 구간별 분포
    print("\n--- 점수 구간별 approve/reject 분포 ---")
    for bin_name in score_bins:
        acts = bin_actions[bin_name]
        total_bin = sum(acts.values())
        if total_bin == 0:
            continue
        parts = []
        for a in ("approve", "reject", "modify"):
            c = acts.get(a, 0)
            parts.append(f"{a}={c}")
        print(f"  {bin_name:<22}: {', '.join(parts)}  (total={total_bin})")

    # 패턴 감지
    print("\n--- 감지된 패턴 ---")
    patterns = detect_patterns(feedback, rubric)
    if not patterns:
        print("  (뚜렷한 패턴 없음)")
    for p in patterns:
        print(f"  [{p['severity']}] {p['message']}")

    # 관심축별 reject 비율
    print("\n--- 관심축별 reject 비율 ---")
    for ia, cnt in sorted(interest_axis_total.items()):
        rej = interest_axis_reject.get(ia, 0)
        pct = rej / cnt * 100 if cnt else 0
        flag = " <<<" if pct > 40 else ""
        print(f"  {ia:<20}: {rej}/{cnt} ({pct:.0f}%){flag}")

    # reject 사유 키워드
    if axis_reject_reasons:
        print("\n--- reject 사유 빈출 키워드 ---")
        for kw, cnt in sorted(axis_reject_reasons.items(), key=lambda x: -x[1])[:10]:
            print(f"  {kw:<24}: {cnt}")


def _extract_reason_keywords(reason: str) -> List[str]:
    """reject 사유에서 핵심 키워드 추출 (간단한 규칙 기반)."""
    keywords = []
    # 한국어 + 영어 키워드 매핑
    keyword_map = {
        "출처": "source_unreliable",
        "부정확": "source_unreliable",
        "source": "source_unreliable",
        "unreliable": "source_unreliable",
        "이미 알고": "not_novel",
        "already known": "not_novel",
        "novelty": "not_novel",
        "새롭지": "not_novel",
        "중복": "not_novel",
        "실행": "not_actionable",
        "actionable": "not_actionable",
        "구체적": "not_actionable",
        "vague": "not_actionable",
        "모호": "not_actionable",
        "유용": "not_useful",
        "useful": "not_useful",
        "관련 없": "not_useful",
        "irrelevant": "not_useful",
        "오래된": "outdated",
        "outdated": "outdated",
        "old": "outdated",
    }
    reason_lower = reason.lower()
    seen = set()
    for trigger, kw in keyword_map.items():
        if trigger.lower() in reason_lower and kw not in seen:
            keywords.append(kw)
            seen.add(kw)
    return keywords if keywords else ["unclassified"]


# ---------------------------------------------------------------------------
# 패턴 감지
# ---------------------------------------------------------------------------

def detect_patterns(
    feedback: List[Dict[str, Any]], rubric: Dict[str, Any]
) -> List[Dict[str, str]]:
    """피드백에서 rubric 조정이 필요한 패턴 감지."""
    patterns: List[Dict[str, str]] = []
    thresholds = rubric["thresholds"]
    pass_th = thresholds["pass"]
    uncertain_min = thresholds["uncertain_min"]

    # 분류별 그룹
    uncertain_approved = []
    uncertain_rejected = []
    pass_rejected = []
    fail_approved = []

    for entry in feedback:
        action = entry.get("action", "")
        t_score = entry.get("total_score", 0)
        cls = classify_score(t_score, rubric)

        if cls == "UNCERTAIN" and action == "approve":
            uncertain_approved.append(entry)
        elif cls == "UNCERTAIN" and action == "reject":
            uncertain_rejected.append(entry)
        elif cls == "PASS" and action == "reject":
            pass_rejected.append(entry)
        elif cls == "FAIL" and action == "approve":
            fail_approved.append(entry)

    total_uncertain = len(uncertain_approved) + len(uncertain_rejected)

    # 패턴 1: UNCERTAIN 중 approve 비율이 높으면 → 임계값 하향
    if total_uncertain >= 5:
        approve_rate = len(uncertain_approved) / total_uncertain
        if approve_rate >= 0.7:
            patterns.append({
                "severity": "HIGH",
                "message": (
                    f"UNCERTAIN({uncertain_min}-{pass_th - 1}) 구간에서 "
                    f"{approve_rate:.0%} approve됨 (n={total_uncertain}). "
                    f"pass 임계값을 낮추는 것을 권장합니다."
                ),
                "type": "lower_pass_threshold",
                "data": json.dumps({
                    "approve_rate": round(approve_rate, 3),
                    "n": total_uncertain,
                }),
            })

    # 패턴 2: PASS인데 reject된 항목이 있으면 → 채점 기준 느슨
    if len(pass_rejected) >= 2:
        patterns.append({
            "severity": "HIGH",
            "message": (
                f"PASS({pass_th}+) 항목 중 {len(pass_rejected)}건 reject됨. "
                f"채점 기준이 너무 느슨합니다. 임계값 상향 또는 가중치 조정을 권장합니다."
            ),
            "type": "raise_pass_threshold",
            "data": json.dumps({"n_rejected": len(pass_rejected)}),
        })

    # 패턴 3: FAIL인데 approve된 항목이 있으면 → 임계값 너무 높음
    if len(fail_approved) >= 2:
        patterns.append({
            "severity": "MEDIUM",
            "message": (
                f"FAIL(<{uncertain_min}) 항목 중 {len(fail_approved)}건 approve됨. "
                f"임계값이 과도하게 높을 수 있습니다."
            ),
            "type": "lower_uncertain_threshold",
            "data": json.dumps({"n_approved": len(fail_approved)}),
        })

    # 패턴 4: 특정 관심축에서 reject 비율이 높으면
    ia_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "reject": 0})
    for entry in feedback:
        ia = entry.get("interest_axis", "unknown")
        ia_stats[ia]["total"] += 1
        if entry.get("action") == "reject":
            ia_stats[ia]["reject"] += 1

    for ia, stats in ia_stats.items():
        if stats["total"] >= 5:
            reject_rate = stats["reject"] / stats["total"]
            if reject_rate >= 0.5:
                patterns.append({
                    "severity": "MEDIUM",
                    "message": (
                        f"관심축 '{ia}'에서 reject 비율 {reject_rate:.0%} "
                        f"(n={stats['total']}). 해당 축의 가중치 조정을 권장합니다."
                    ),
                    "type": "axis_weight_adjustment",
                    "data": json.dumps({
                        "interest_axis": ia,
                        "reject_rate": round(reject_rate, 3),
                    }),
                })

    # 패턴 5: reject 사유에서 특정 축이 빈출
    reason_axis_counts: Dict[str, int] = defaultdict(int)
    for entry in feedback:
        if entry.get("action") == "reject":
            reason = entry.get("reason", "")
            for kw in _extract_reason_keywords(reason):
                reason_axis_counts[kw] += 1

    total_rejects = sum(1 for e in feedback if e.get("action") == "reject")
    if total_rejects >= 5:
        for kw, cnt in reason_axis_counts.items():
            rate = cnt / total_rejects
            if rate >= 0.4 and kw != "unclassified":
                axis_hint = _reason_to_axis(kw)
                patterns.append({
                    "severity": "MEDIUM",
                    "message": (
                        f"reject 사유에 '{kw}' 빈출 ({cnt}/{total_rejects}, {rate:.0%}). "
                        f"'{axis_hint}' 축 가중치 상향을 권장합니다."
                    ),
                    "type": "axis_weight_by_reason",
                    "data": json.dumps({
                        "reason_keyword": kw,
                        "axis": axis_hint,
                        "rate": round(rate, 3),
                    }),
                })

    return patterns


def _reason_to_axis(keyword: str) -> str:
    """reject 사유 키워드 → rubric 축 매핑."""
    mapping = {
        "source_unreliable": "reliability",
        "not_novel": "novelty",
        "not_actionable": "actionability",
        "not_useful": "usefulness",
        "outdated": "reliability",
    }
    return mapping.get(keyword, "reliability")


# ---------------------------------------------------------------------------
# evolve 명령
# ---------------------------------------------------------------------------

def cmd_evolve(args: argparse.Namespace) -> None:
    """피드백 패턴에 기반한 rubric 조정 제안 생성."""
    rubric = load_rubric()
    feedback = load_feedback()

    min_fb = rubric.get("min_feedback_for_evolution", 20)
    n = len(feedback)

    if n < min_fb:
        print(f"WARNING: 피드백 {n}건 — 최소 {min_fb}건 필요합니다.")
        print(f"  현재 파일: {FEEDBACK_PATH}")
        print(f"  {min_fb - n}건 더 수집 후 다시 실행하세요.")
        return

    patterns = detect_patterns(feedback, rubric)
    if not patterns:
        print("분석 완료: 현재 rubric에 조정이 필요한 패턴이 없습니다.")
        return

    proposed_changes: List[Dict[str, Any]] = []
    thresholds = rubric["thresholds"]

    for p in patterns:
        ptype = p["type"]
        data = json.loads(p.get("data", "{}"))

        if ptype == "lower_pass_threshold":
            # UNCERTAIN에서 approve가 많으면 pass 임계값 하향
            approve_rate = data.get("approve_rate", 0)
            current = thresholds["pass"]
            # approve율에 비례하여 1-3점 하향
            delta = min(3, max(1, round((approve_rate - 0.6) * 5)))
            proposed = max(thresholds["uncertain_min"] + 2, current - delta)
            if proposed != current:
                proposed_changes.append({
                    "field": "thresholds.pass",
                    "current": current,
                    "proposed": proposed,
                    "reason": (
                        f"UNCERTAIN 구간에서 {approve_rate:.0%} approve됨 "
                        f"(n={data.get('n', '?')})"
                    ),
                })

        elif ptype == "raise_pass_threshold":
            # PASS인데 reject 많으면 임계값 상향
            current = thresholds["pass"]
            n_rej = data.get("n_rejected", 0)
            delta = min(3, max(1, n_rej))
            proposed = min(35, current + delta)
            if proposed != current:
                proposed_changes.append({
                    "field": "thresholds.pass",
                    "current": current,
                    "proposed": proposed,
                    "reason": f"PASS 항목 중 {n_rej}건 reject됨",
                })

        elif ptype == "lower_uncertain_threshold":
            current = thresholds["uncertain_min"]
            proposed = max(10, current - 2)
            if proposed != current:
                proposed_changes.append({
                    "field": "thresholds.uncertain_min",
                    "current": current,
                    "proposed": proposed,
                    "reason": (
                        f"FAIL 구간에서 {data.get('n_approved', '?')}건 approve됨"
                    ),
                })

        elif ptype == "axis_weight_by_reason":
            axis = data.get("axis", "")
            kw = data.get("reason_keyword", "")
            rate = data.get("rate", 0)
            if axis in rubric.get("axes", {}):
                current_w = rubric["axes"][axis]["weight"]
                # 비율에 비례하여 0.1-0.3 상향
                delta = round(min(0.3, max(0.1, rate * 0.5)), 2)
                proposed_w = round(min(2.0, current_w + delta), 2)
                if proposed_w != current_w:
                    proposed_changes.append({
                        "field": f"axes.{axis}.weight",
                        "current": current_w,
                        "proposed": proposed_w,
                        "reason": f"reject 사유에 '{kw}' 빈출 ({rate:.0%})",
                    })

        elif ptype == "axis_weight_adjustment":
            # 특정 관심축에서 reject이 많을 때 — 전체 축 가중치 점검
            # 이 경우 reject된 항목의 축별 평균 점수를 비교하여 낮은 축 가중치 상향
            ia = data.get("interest_axis", "")
            ia_rejects = [
                e for e in feedback
                if e.get("interest_axis") == ia and e.get("action") == "reject"
            ]
            if ia_rejects:
                axis_avgs: Dict[str, float] = {}
                for axis in AXES:
                    vals = [e.get("scores", {}).get(axis, 0) for e in ia_rejects]
                    axis_avgs[axis] = sum(vals) / len(vals) if vals else 0

                # 가장 낮은 축의 가중치를 올림
                lowest_axis = min(axis_avgs, key=lambda a: axis_avgs[a])
                if lowest_axis in rubric.get("axes", {}):
                    current_w = rubric["axes"][lowest_axis]["weight"]
                    proposed_w = round(min(2.0, current_w + 0.2), 2)
                    if proposed_w != current_w:
                        proposed_changes.append({
                            "field": f"axes.{lowest_axis}.weight",
                            "current": current_w,
                            "proposed": proposed_w,
                            "reason": (
                                f"관심축 '{ia}'에서 reject 빈출, "
                                f"'{lowest_axis}' 평균 {axis_avgs[lowest_axis]:.1f}로 최저"
                            ),
                        })

    # 중복 제거 (같은 field에 대한 변경은 가장 큰 delta만)
    proposed_changes = _deduplicate_proposals(proposed_changes)

    if not proposed_changes:
        print("패턴이 감지되었으나 현재 rubric에서 변경할 수 있는 항목이 없습니다.")
        return

    # 신뢰도 계산: 피드백 수와 패턴 일관성에 기반
    confidence = _compute_confidence(n, patterns, proposed_changes)

    proposal = {
        "generated_at": datetime.now().isoformat(),
        "based_on_n": n,
        "current_rubric_version": rubric.get("version", "?"),
        "confidence": confidence,
        "proposed_changes": proposed_changes,
        "detected_patterns": [
            {"severity": p["severity"], "message": p["message"], "type": p["type"]}
            for p in patterns
        ],
    }

    save_proposal(proposal)

    print("=" * 60)
    print("  MuchaNipo Rubric Evolution Proposal")
    print("=" * 60)
    print(f"\n피드백 기반: {n}건")
    print(f"신뢰도: {confidence:.2f}")
    print(f"현재 rubric 버전: {rubric.get('version', '?')}")
    print(f"\n제안된 변경 ({len(proposed_changes)}건):")
    for i, ch in enumerate(proposed_changes, 1):
        print(f"\n  [{i}] {ch['field']}")
        print(f"      현재: {ch['current']}  ->  제안: {ch['proposed']}")
        print(f"      사유: {ch['reason']}")

    print(f"\n제안 파일 저장: {PROPOSAL_PATH}")
    print("적용하려면: python rubric-learner.py apply")


def _deduplicate_proposals(
    proposals: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """같은 field에 대한 중복 제안 제거 (가장 큰 변경폭 우선)."""
    by_field: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for p in proposals:
        by_field[p["field"]].append(p)

    result: List[Dict[str, Any]] = []
    for field, items in by_field.items():
        if len(items) == 1:
            result.append(items[0])
        else:
            # 변경폭이 가장 큰 것 선택
            best = max(
                items,
                key=lambda x: abs(x["proposed"] - x["current"]),
            )
            result.append(best)
    return result


def _compute_confidence(
    n_feedback: int,
    patterns: List[Dict[str, str]],
    proposals: List[Dict[str, Any]],
) -> float:
    """제안 신뢰도 계산 (0.0 ~ 1.0)."""
    # 기본: 피드백 수에 따라
    # 20건 → 0.5, 50건 → 0.75, 100건+ → 0.9
    base = min(0.9, 0.5 + (n_feedback - 20) * 0.005)

    # HIGH severity 패턴이 많으면 보너스
    high_count = sum(1 for p in patterns if p.get("severity") == "HIGH")
    bonus = min(0.1, high_count * 0.05)

    # 변경 항목이 너무 많으면 신뢰도 감소
    penalty = max(0, (len(proposals) - 3) * 0.05)

    return round(max(0.3, min(1.0, base + bonus - penalty)), 2)


# ---------------------------------------------------------------------------
# apply 명령
# ---------------------------------------------------------------------------

def cmd_apply(args: argparse.Namespace) -> None:
    """제안된 변경 적용."""
    proposal = load_proposal()
    if proposal is None:
        print("ERROR: 적용할 제안이 없습니다.")
        print("먼저 실행: python rubric-learner.py evolve")
        return

    rubric = load_rubric()
    changes = proposal.get("proposed_changes", [])

    if not changes:
        print("제안에 변경 항목이 없습니다.")
        return

    # 확인
    print(f"제안 생성일시: {proposal.get('generated_at', '?')}")
    print(f"피드백 기반: {proposal.get('based_on_n', '?')}건")
    print(f"신뢰도: {proposal.get('confidence', '?')}")
    print(f"\n적용할 변경 ({len(changes)}건):")
    for ch in changes:
        print(f"  {ch['field']}: {ch['current']} -> {ch['proposed']}")

    if not args.yes:
        answer = input("\n적용하시겠습니까? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("취소됨.")
            return

    # 백업
    backup_path = backup_rubric(rubric)
    print(f"\n이전 rubric 백업: {backup_path}")

    # 변경 적용
    for ch in changes:
        field = ch["field"]
        value = ch["proposed"]
        _set_nested(rubric, field, value)

    # 버전 업
    old_version = rubric.get("version", "1.0.0")
    rubric["version"] = _bump_version(old_version)
    rubric["last_evolved"] = datetime.now().isoformat()
    rubric["evolution_source"] = {
        "based_on_n": proposal.get("based_on_n", 0),
        "confidence": proposal.get("confidence", 0),
        "applied_at": datetime.now().isoformat(),
    }

    save_rubric(rubric)

    # 제안 파일 정리
    applied_path = PROPOSAL_PATH.with_suffix(".applied.json")
    proposal["applied_at"] = datetime.now().isoformat()
    with open(applied_path, "w", encoding="utf-8") as f:
        json.dump(proposal, f, indent=2, ensure_ascii=False)
        f.write("\n")
    PROPOSAL_PATH.unlink(missing_ok=True)

    print(f"\n새 rubric 저장 완료 (v{rubric['version']})")
    print(f"  파일: {RUBRIC_PATH}")


def _set_nested(obj: Dict, dotted_key: str, value: Any) -> None:
    """점(.) 구분 키로 중첩 dict 값 설정. 예: 'thresholds.pass' → obj['thresholds']['pass']."""
    keys = dotted_key.split(".")
    for k in keys[:-1]:
        obj = obj.setdefault(k, {})
    obj[keys[-1]] = value


def _bump_version(version: str) -> str:
    """시맨틱 버전 minor 자동 증가. 예: '1.0.0' → '1.1.0'."""
    parts = version.split(".")
    if len(parts) == 3:
        try:
            major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
            return f"{major}.{minor + 1}.{patch}"
        except ValueError:
            pass
    return version + ".1"


# ---------------------------------------------------------------------------
# history 명령
# ---------------------------------------------------------------------------

def cmd_history(args: argparse.Namespace) -> None:
    """rubric 변경 이력 출력."""
    if not HISTORY_DIR.exists():
        print("변경 이력이 없습니다.")
        print(f"  이력 디렉토리: {HISTORY_DIR}")
        return

    files = sorted(HISTORY_DIR.glob("rubric-*.json"))
    if not files:
        print("변경 이력이 없습니다.")
        return

    print("=" * 60)
    print("  MuchaNipo Rubric Version History")
    print("=" * 60)

    versions: List[Tuple[Path, Dict[str, Any]]] = []
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            versions.append((fp, data))
        except (json.JSONDecodeError, OSError):
            print(f"  WARNING: {fp.name} 파싱 실패")

    # 현재 rubric도 포함
    current = load_rubric()
    print(f"\n현재 rubric: v{current.get('version', '?')}")

    if not versions:
        print("  (이전 버전 없음)")
        return

    print(f"이력 파일 수: {len(versions)}\n")

    for i, (fp, data) in enumerate(versions):
        v = data.get("version", "?")
        created = data.get("created", "?")
        evolved = data.get("last_evolved", "")
        pass_th = data.get("thresholds", {}).get("pass", "?")
        uncertain = data.get("thresholds", {}).get("uncertain_min", "?")
        print(f"  [{i + 1}] v{v}  |  pass={pass_th}  uncertain_min={uncertain}")
        print(f"       파일: {fp.name}")
        if evolved:
            print(f"       진화일시: {evolved}")

        # 다음 버전과 diff
        if i < len(versions) - 1:
            next_data = versions[i + 1][1]
            diffs = _diff_rubrics(data, next_data)
            if diffs:
                for d in diffs:
                    print(f"       -> {d}")
        elif i == len(versions) - 1:
            # 마지막 이력 vs 현재
            diffs = _diff_rubrics(data, current)
            if diffs:
                print("       -> (현재 rubric과의 차이):")
                for d in diffs:
                    print(f"          {d}")

    print()


def _diff_rubrics(old: Dict, new: Dict) -> List[str]:
    """두 rubric 간 주요 차이 요약."""
    diffs: List[str] = []
    # 버전
    ov, nv = old.get("version", "?"), new.get("version", "?")
    if ov != nv:
        diffs.append(f"version: {ov} -> {nv}")
    # 임계값
    for key in ("pass", "uncertain_min", "fail_max"):
        o = old.get("thresholds", {}).get(key)
        n = new.get("thresholds", {}).get(key)
        if o is not None and n is not None and o != n:
            diffs.append(f"thresholds.{key}: {o} -> {n}")
    # 축 가중치
    for axis in AXES:
        ow = old.get("axes", {}).get(axis, {}).get("weight")
        nw = new.get("axes", {}).get(axis, {}).get("weight")
        if ow is not None and nw is not None and ow != nw:
            diffs.append(f"axes.{axis}.weight: {ow} -> {nw}")
    return diffs


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MuchaNipo Rubric Learner — 사용자 피드백 기반 채점 기준 자동 조정",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예시:\n"
            "  python rubric-learner.py analyze       # 피드백 패턴 분석\n"
            "  python rubric-learner.py evolve         # rubric 업데이트 제안\n"
            "  python rubric-learner.py apply          # 제안된 변경 적용\n"
            "  python rubric-learner.py apply --yes    # 확인 없이 적용\n"
            "  python rubric-learner.py history        # rubric 변경 이력\n"
        ),
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("analyze", help="현재 피드백 패턴 분석")
    sub.add_parser("evolve", help="rubric 업데이트 제안 생성")

    apply_p = sub.add_parser("apply", help="제안된 변경 적용")
    apply_p.add_argument(
        "--yes", "-y", action="store_true", help="확인 없이 바로 적용"
    )

    sub.add_parser("history", help="rubric 변경 이력 조회")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "analyze": cmd_analyze,
        "evolve": cmd_evolve,
        "apply": cmd_apply,
        "history": cmd_history,
    }

    handler = dispatch.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
