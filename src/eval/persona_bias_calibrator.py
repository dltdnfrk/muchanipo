#!/usr/bin/env python3
"""Persona-Bias calibrator for MuchaNipo eval runs.

Allen AI Persona-Bias 류 평가에서 필요한 최소 단위는 "같은 질문에 대한
control 응답"과 "persona-conditioned 응답"의 차이를 반복 측정하는 것이다.
이 모듈은 외부 의존성 없이 lexical distribution shift를 계산하고, persona의
value axis별로 집계할 수 있게 한다.
"""

import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Union


try:  # pragma: no cover - 실행 컨텍스트에 따라 import path가 달라질 수 있음
    from safety import lockdown as _lockdown  # type: ignore
except Exception:  # noqa: BLE001
    try:
        import sys as _sys
        from pathlib import Path as _Path

        _SRC = _Path(__file__).resolve().parent.parent
        if str(_SRC) not in _sys.path:
            _sys.path.insert(0, str(_SRC))
        from safety import lockdown as _lockdown  # type: ignore
    except Exception:  # noqa: BLE001
        _lockdown = None


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]{2,}", re.UNICODE)
_STOPWORDS = {
    "the",
    "and",
    "or",
    "but",
    "for",
    "with",
    "from",
    "this",
    "that",
    "are",
    "was",
    "were",
    "있다",
    "이다",
    "한다",
    "했다",
    "그리고",
    "하지만",
    "또한",
    "대한",
    "대해",
    "위해",
}


@dataclass(frozen=True)
class BiasReport:
    """단일 persona/control 비교 결과.

    `kl_divergence`는 persona 응답 분포가 control 응답 분포에서 얼마나
    멀어졌는지 나타낸다. `lexical_shift`는 대칭적인 top-term 차이 요약이다.
    """

    persona_id: str
    axis_tags: List[str]
    kl_divergence: float
    lexical_shift: float
    control_token_count: int
    persona_token_count: int
    shifted_terms: List[Dict[str, float]] = field(default_factory=list)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PersonaBiasCalibrator:
    """Persona-conditioned 응답의 lexical bias shift 측정기."""

    def __init__(self, *, smoothing: float = 0.5, audit: bool = True) -> None:
        if smoothing <= 0:
            raise ValueError("smoothing must be positive")
        self.smoothing = float(smoothing)
        self.audit = audit

    def measure(
        self,
        persona: Union[Mapping[str, Any], str],
        control_response: str,
        persona_response: str,
    ) -> BiasReport:
        """control/persona 응답 간 KL divergence와 lexical shift를 계산한다."""

        control_counts = _token_counts(control_response)
        persona_counts = _token_counts(persona_response)
        vocab = sorted(set(control_counts) | set(persona_counts))

        kl = _kl_divergence(
            persona_counts,
            control_counts,
            vocab,
            smoothing=self.smoothing,
        )
        shifted_terms = _shifted_terms(
            control_counts,
            persona_counts,
            vocab,
            smoothing=self.smoothing,
            limit=8,
        )
        lexical_shift = sum(abs(term["delta"]) for term in shifted_terms)

        report = BiasReport(
            persona_id=_persona_id(persona),
            axis_tags=_axis_tags(persona),
            kl_divergence=round(kl, 6),
            lexical_shift=round(lexical_shift, 6),
            control_token_count=sum(control_counts.values()),
            persona_token_count=sum(persona_counts.values()),
            shifted_terms=shifted_terms,
        )
        self._audit("persona_bias_measure", report.to_dict())
        return report

    def aggregate(
        self,
        reports: Iterable[Union[BiasReport, Mapping[str, Any]]],
    ) -> Dict[str, Any]:
        """BiasReport 목록을 전체/axis별 평균으로 집계한다."""

        normalized = [_coerce_report(report) for report in reports]
        overall = _summarize(normalized)

        by_axis: MutableMapping[str, List[BiasReport]] = defaultdict(list)
        for report in normalized:
            tags = report.axis_tags or ["overall"]
            for tag in tags:
                by_axis[tag].append(report)

        result = {
            "count": len(normalized),
            "overall": overall,
            "by_axis": {
                tag: _summarize(axis_reports)
                for tag, axis_reports in sorted(by_axis.items())
            },
        }
        self._audit("persona_bias_aggregate", result)
        return result

    def _audit(self, decision: str, context: Mapping[str, Any]) -> None:
        if not self.audit or _lockdown is None:
            return
        try:
            _lockdown.audit_log(decision, context)
        except Exception:  # noqa: BLE001
            # eval 경로에서 audit I/O 실패가 측정 자체를 깨지 않도록 한다.
            return


def _token_counts(text: str) -> Counter:
    tokens = [
        token
        for token in _TOKEN_RE.findall(str(text).lower())
        if token not in _STOPWORDS
    ]
    return Counter(tokens)


def _distribution(
    counts: Counter,
    vocab: Sequence[str],
    *,
    smoothing: float,
) -> Dict[str, float]:
    denom = sum(counts.values()) + smoothing * len(vocab)
    if not vocab or denom <= 0:
        return {}
    return {
        term: (counts.get(term, 0) + smoothing) / denom
        for term in vocab
    }


def _kl_divergence(
    observed: Counter,
    baseline: Counter,
    vocab: Sequence[str],
    *,
    smoothing: float,
) -> float:
    if not vocab:
        return 0.0
    p = _distribution(observed, vocab, smoothing=smoothing)
    q = _distribution(baseline, vocab, smoothing=smoothing)
    return sum(p[term] * math.log(p[term] / q[term]) for term in vocab)


def _shifted_terms(
    control_counts: Counter,
    persona_counts: Counter,
    vocab: Sequence[str],
    *,
    smoothing: float,
    limit: int,
) -> List[Dict[str, float]]:
    control_dist = _distribution(control_counts, vocab, smoothing=smoothing)
    persona_dist = _distribution(persona_counts, vocab, smoothing=smoothing)
    deltas = [
        {
            "term": term,
            "control": round(control_dist.get(term, 0.0), 6),
            "persona": round(persona_dist.get(term, 0.0), 6),
            "delta": round(persona_dist.get(term, 0.0) - control_dist.get(term, 0.0), 6),
        }
        for term in vocab
    ]
    return sorted(deltas, key=lambda item: abs(item["delta"]), reverse=True)[:limit]


def _persona_id(persona: Union[Mapping[str, Any], str]) -> str:
    if isinstance(persona, Mapping):
        for key in ("id", "persona_id", "name", "role"):
            value = persona.get(key)
            if value:
                return str(value)
        return "persona:unknown"
    return str(persona or "persona:unknown")


def _axis_tags(persona: Union[Mapping[str, Any], str]) -> List[str]:
    if not isinstance(persona, Mapping):
        return ["persona:string"]

    tags: List[str] = []
    value_axes = persona.get("value_axes")
    if isinstance(value_axes, Mapping):
        for key, value in sorted(value_axes.items()):
            if isinstance(value, (str, int, float, bool)):
                tags.append(f"{key}:{value}")
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                tags.extend(f"{key}:{item}" for item in value)

    for key in ("province", "occupation", "segment", "axis"):
        value = persona.get(key)
        if value:
            tags.append(f"{key}:{value}")

    return tags or ["persona:unlabeled"]


def _coerce_report(report: Union[BiasReport, Mapping[str, Any]]) -> BiasReport:
    if isinstance(report, BiasReport):
        return report
    return BiasReport(
        persona_id=str(report.get("persona_id", "persona:unknown")),
        axis_tags=list(report.get("axis_tags", []) or []),
        kl_divergence=float(report.get("kl_divergence", 0.0)),
        lexical_shift=float(report.get("lexical_shift", 0.0)),
        control_token_count=int(report.get("control_token_count", 0)),
        persona_token_count=int(report.get("persona_token_count", 0)),
        shifted_terms=list(report.get("shifted_terms", []) or []),
        timestamp=str(report.get("timestamp") or datetime.now(timezone.utc).isoformat()),
    )


def _summarize(reports: Sequence[BiasReport]) -> Dict[str, Any]:
    if not reports:
        return {
            "count": 0,
            "mean_kl_divergence": 0.0,
            "mean_lexical_shift": 0.0,
            "max_kl_divergence": 0.0,
            "max_lexical_shift": 0.0,
        }

    count = len(reports)
    return {
        "count": count,
        "mean_kl_divergence": round(
            sum(report.kl_divergence for report in reports) / count,
            6,
        ),
        "mean_lexical_shift": round(
            sum(report.lexical_shift for report in reports) / count,
            6,
        ),
        "max_kl_divergence": round(max(report.kl_divergence for report in reports), 6),
        "max_lexical_shift": round(max(report.lexical_shift for report in reports), 6),
    }


__all__ = ["BiasReport", "PersonaBiasCalibrator"]
