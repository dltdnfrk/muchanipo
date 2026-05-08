"""Anthropic provider wrapper — CLI-first, streaming, cost-tracking, fallback.

Supports three execution modes:
  1. CLI subprocess (`claude -p`) — auth is owned by Claude Code, no API key.
  2. Anthropic SDK direct (ANTHROPIC_API_KEY).
  3. Offline mock.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any, Callable

from src.execution.models import ModelResult
from src.execution.providers.cli_policy import cli_requested, prefer_cli_default

try:  # pragma: no cover - availability depends on local environment.
    from anthropic import Anthropic
except ImportError:  # pragma: no cover
    Anthropic = None  # type: ignore[assignment, misc]

# Approximate pricing per 1M tokens (input / output) in USD.
# Updated periodically; used for cost_usd estimation.
_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-7": (15.0, 75.0),
    "claude-opus-4-6": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (0.25, 1.25),
    "claude-haiku-4-4": (0.25, 1.25),
}

FALLBACK_CHAIN = ("claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_DEFAULT_MODEL = os.environ.get("MUCHANIPO_ANTHROPIC_MODEL", "claude-sonnet-4-6")
_CLI_TIMEOUT_SEC = _env_int("MUCHANIPO_ANTHROPIC_CLI_TIMEOUT_SEC", 300)


def _resolve_api_key() -> str | None:
    """Check explicit API env vars only; never read Claude Code OAuth files."""
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        val = os.environ.get(key)
        if val:
            return val
    return None


def _cli_enabled() -> bool:
    return cli_requested("ANTHROPIC_USE_CLI")


def _resolve_claude_bin() -> str | None:
    explicit = os.environ.get("CLAUDE_BIN")
    if explicit and os.path.exists(explicit):
        return explicit
    return shutil.which("claude")


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        api_key: str | None = None,
        client: Any = None,
        offline: bool | None = None,
        use_cli: bool | None = None,
        prefer_cli: bool | None = None,
        claude_bin: str | None = None,
    ) -> None:
        self.model = model
        self.client = client
        self.api_key = api_key or _resolve_api_key()
        self.claude_bin = claude_bin or _resolve_claude_bin()
        if prefer_cli is None:
            prefer_cli = prefer_cli_default()
        if use_cli is None:
            use_cli = bool(self.claude_bin) and (_cli_enabled() or (prefer_cli and client is None))
        self.use_cli = use_cli
        if offline is None:
            # CLI mode bypasses the offline-by-no-key check.
            offline = bool(os.environ.get("ANTHROPIC_OFFLINE")) or (
                self.api_key is None and not self.use_cli
            )
        # Injected client trumps offline default — caller wants real call path.
        if client is not None and offline:
            offline = False
        self.offline = offline

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        if self.offline:
            return _mock_result(stage, prompt, model=self.model, provider=self.name, **kwargs)

        stream_callback = kwargs.pop("stream_callback", None)
        allow_fallback = kwargs.pop("allow_fallback", True)

        if self.use_cli and self.claude_bin:
            try:
                return self._call_cli(stage, prompt, stream_callback=stream_callback, **kwargs)
            except Exception as exc:
                if allow_fallback:
                    return _fallback_result(exc, self.model)
                raise

        try:
            return self._call_with_fallback(stage, prompt, stream_callback=stream_callback, **kwargs)
        except Exception as exc:
            if allow_fallback:
                return _fallback_result(exc, self.model)
            raise

    def _call_cli(
        self,
        stage: str,
        prompt: str,
        *,
        stream_callback: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> ModelResult:  # pragma: no cover - subprocess path
        model = kwargs.pop("model", self.model)
        timeout = int(kwargs.pop("timeout", _CLI_TIMEOUT_SEC))
        args = [self.claude_bin, "-p", "--output-format", "text", "--model", model]
        proc = subprocess.run(
            args,
            input=prompt.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(stderr or f"claude CLI exited with {proc.returncode}")
        text = proc.stdout.decode("utf-8", errors="replace").strip()
        if stream_callback:
            stream_callback(text)
        return ModelResult(
            text=text,
            provider=self.name,
            model=model,
            cost_usd=0.0,
            raw={"mode": "cli"},
        )

    def _call_with_fallback(
        self,
        stage: str,
        prompt: str,
        *,
        stream_callback: Callable[[str], None] | None = None,
        **kwargs: Any,
    ) -> ModelResult:
        models = _fallback_models(kwargs.pop("model", self.model))
        last_exc: Exception | None = None
        for m in models:
            try:
                return self._call_one(
                    stage=stage,
                    prompt=prompt,
                    model=m,
                    stream_callback=stream_callback,
                    **kwargs,
                )
            except Exception as exc:
                last_exc = exc
        raise last_exc or RuntimeError("all fallback models failed")

    def _call_one(
        self,
        *,
        stage: str,
        prompt: str,
        model: str,
        stream_callback: Callable[[str], None] | None,
        **kwargs: Any,
    ) -> ModelResult:
        client = self.client
        if client is None:
            if Anthropic is None:
                raise RuntimeError("anthropic package is not installed")
            client = Anthropic(api_key=self.api_key)

        if stream_callback:
            return self._stream_call(client, model, prompt, stream_callback, **kwargs)

        message = client.messages.create(
            model=model,
            max_tokens=int(kwargs.pop("max_tokens", 1024)),
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
        text = _content_text(message)
        cost = _estimate_cost(model, message)
        return ModelResult(
            text=text,
            provider=self.name,
            model=model,
            cost_usd=cost,
            raw=message,
        )

    def _stream_call(
        self,
        client: Any,
        model: str,
        prompt: str,
        callback: Callable[[str], None],
        **kwargs: Any,
    ) -> ModelResult:
        with client.messages.stream(
            model=model,
            max_tokens=int(kwargs.pop("max_tokens", 1024)),
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        ) as stream:
            chunks: list[str] = []
            for text in stream.text_stream:
                if text:
                    chunks.append(text)
                    callback(text)
            full_text = "".join(chunks)
            # Best-effort cost extraction after stream ends
            usage = getattr(stream, "current_message_snapshot", None)
            cost = _estimate_cost(model, usage)
            return ModelResult(
                text=full_text,
                provider=self.name,
                model=model,
                cost_usd=cost,
                raw=None,
            )


def _fallback_models(preferred: str) -> tuple[str, ...]:
    """Return fallback chain starting from the preferred model."""
    try:
        idx = FALLBACK_CHAIN.index(preferred)
        return FALLBACK_CHAIN[idx:]
    except ValueError:
        return (preferred,) + FALLBACK_CHAIN


def _content_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for item in content or []:
        text = getattr(item, "text", None)
        if text:
            parts.append(str(text))
    return "\n".join(parts)


def _estimate_cost(model: str, message: Any) -> float:
    usage = getattr(message, "usage", None) or {}
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    pricing = _PRICING.get(model, (3.0, 15.0))
    # pricing is per 1M tokens
    return round(
        (input_tokens * pricing[0] + output_tokens * pricing[1]) / 1_000_000, 6
    )


def _fallback_result(exc: Exception, model: str) -> ModelResult:
    return ModelResult(
        text=f"[anthropic fallback] {exc}",
        provider="anthropic",
        model=model,
        cost_usd=0.0,
        is_fallback=True,
        fallback_reason=str(exc),
    )


def _mock_result(stage: str, prompt: str, *, model: str, provider: str, **kwargs: Any) -> ModelResult:
    if stage == "council":
        text = _mock_council_json(prompt, council_stage=str(kwargs.get("council_stage") or ""))
        return ModelResult(text=text, provider=provider, model=model, cost_usd=0.0)
    snippet = prompt[:60].replace("\n", " ")
    text = f"[mock-{provider}/{stage}] {snippet}"
    return ModelResult(text=text, provider=provider, model=model, cost_usd=0.0)


def _mock_council_json(prompt: str, *, council_stage: str) -> str:
    if "# HACHIMI Stage 2 DEEP VALIDATE" in prompt:
        return json.dumps(
            {
                "score": 8,
                "reason": "offline deterministic judge keeps ontology-grounded personas available for local council smoke runs",
                "issues": [],
            },
            ensure_ascii=False,
        )
    if "# HACHIMI Stage 1 PROPOSE" in prompt:
        return json.dumps(
            {
                "personas": [
                    {
                        "persona_id": "persona-001",
                        "name": "Offline Evidence Reviewer",
                        "role": "evidence_reviewer",
                        "intent": "Check whether offline findings remain clearly labeled as mock evidence.",
                        "allowed_tools": ["model_gateway"],
                        "required_outputs": ["council_round_response"],
                        "value_axes": {
                            "time_horizon": "mid",
                            "risk_tolerance": 0.35,
                            "stakeholder_priority": ["primary", "secondary", "tertiary"],
                            "innovation_orientation": 0.55,
                        },
                        "manifest": {"topic_fit": "offline deterministic persona for local council smoke runs"},
                    }
                ]
            },
            ensure_ascii=False,
        )
    title = _extract_prompt_field(prompt, r"Chapter\s+—\s*(.+)") or "검토 대상 chapter"
    focus = _extract_prompt_field(prompt, r"\*\*Focus Question:\*\*\s*(.+)") or "핵심 가정과 실행 조건"
    evidence = _extract_prompt_field(prompt, r"\*\*필요 evidence:\*\*\s*(.+)") or "근거"
    success = _extract_prompt_field(prompt, r"\*\*성공 기준:\*\*\s*(.+)") or "성공 기준"
    evidence_records = _mock_evidence_records(prompt)
    evidence_ids = [record["id"] for record in evidence_records]
    source_backed = any(not _is_demo_evidence_id(evidence_id) for evidence_id in evidence_ids)
    cited_ids = _layer_relevant_evidence_ids(title, focus, evidence_records)
    evidence_refs = ", ".join(f"`{evidence_id}`" for evidence_id in cited_ids[:4])

    if council_stage == "peer_review":
        if source_backed:
            payload = {
                "stance": "conditional_support",
                "critiques": [
                    _peer_source_scope(title, cited_ids, evidence),
                    f"직접 근거가 없는 항목은 다음 수집 배치에서 보강해야 한다: {evidence}.",
                ],
                "agreements": [
                    f"운영 기준({_compact_sentence(success)})을 Evidence ID별 주장 범위와 분리하는 순서에는 동의한다."
                ],
                "suggested_revision": "보고서에는 직접 근거가 있는 관찰, 근거 부족 항목, 다음 검증 backlog를 분리한다.",
                "confidence_score": 0.66,
            }
            return json.dumps(payload, ensure_ascii=False)
        payload = {
            "stance": "conditional_support",
            "critiques": [
                f"{title} 판단은 방향성은 검토 가능하지만 offline mock 근거만으로 외부 주장으로 승격할 수 없다.",
                f"필요 근거({evidence})를 실제 A/B급 출처로 다시 채워야 한다.",
            ],
            "agreements": [
                f"성공 기준({success})을 먼저 고정한 뒤 실측 데이터로 검증하는 순서에는 동의한다."
            ],
            "suggested_revision": "보고서에는 offline/mock 한계를 표시하고, live research 재검증 action을 포함한다.",
            "confidence_score": 0.58,
        }
        return json.dumps(payload, ensure_ascii=False)

    claim_prefix = "출처 기반 검토" if source_backed else "흐름 검증"
    if source_backed:
        payload = {
            "key_claim": _source_backed_key_claim(title, focus, cited_ids),
            "body_claims": [
                f"부족한 근거 범위: {evidence}.",
                "외부 시장성 주장은 직접 근거가 있는 항목만 승격하고, 나머지는 검증 backlog로 남긴다.",
            ],
            "evidence_ref_ids": cited_ids,
            "confidence_score": 0.68 if council_stage == "chairman" else 0.62,
            "disagreements": [
                "출처 범위 밖의 TAM, 경쟁 가격, 지불의사는 확정 주장으로 쓰면 안 된다.",
                "공개 학술/로컬 vault 근거와 실제 고객 인터뷰 사이에는 별도 검증 gap이 남아 있다.",
            ],
            "next_actions": [
                f"{evidence} 범주별 A/B급 출처를 추가 확보한다.",
                "사용자 인터뷰 답변과 Plannotator 수정사항을 반영한 뒤 claim별 evidence coverage를 재평가한다.",
            ],
            "framework_output": {
                "framework": _framework_for_title(title),
                "chapter_title": title,
                "offline_mock": False,
                "source_backed": True,
            },
        }
        return json.dumps(payload, ensure_ascii=False)

    payload = {
        "key_claim": (
            f"{claim_prefix}: {title} - 아직 실제 출처가 없어 시장성 결론으로 사용할 수 없다."
        ),
        "body_claims": [
            f"{evidence} 범주의 A/B급 출처를 수집해야 한다.",
            "mock evidence가 섞인 결론은 검증 backlog로 남기고 최종 주장으로 표시하지 않는다.",
        ],
        "evidence_ref_ids": evidence_ids,
        "confidence_score": 0.62 if council_stage == "chairman" else 0.56,
        "disagreements": [
            "live source 없이 시장 규모, 경쟁 지형, 지불의사를 확정할 수 없다.",
            "offline council은 제품 흐름 검증용이지 외부 배포용 리서치가 아니다.",
        ],
        "next_actions": [
            f"{evidence} 기반의 A/B급 출처를 최소 3개 확보한다.",
            "사용자 인터뷰 답변과 Plannotator 수정사항을 반영한 뒤 council을 재실행한다.",
        ],
        "framework_output": {
            "framework": _framework_for_title(title),
            "chapter_title": title,
            "offline_mock": True,
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def _extract_prompt_field(prompt: str, pattern: str) -> str:
    match = re.search(pattern, prompt)
    return match.group(1).strip() if match else ""


def _mock_evidence_ids(prompt: str) -> list[str]:
    source_ids = [record["id"] for record in _mock_evidence_records(prompt)]
    if source_ids:
        return source_ids[:4]
    ids = list(dict.fromkeys(re.findall(r"\bmock-evidence-\d+\b", prompt)))
    return ids[:4] or ["mock-evidence-1", "mock-evidence-2", "mock-evidence-3", "mock-evidence-4"]


def _mock_evidence_records(prompt: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    pattern = re.compile(
        r"- Evidence ID:\s*`([^`]+)`\s*\n"
        r"(?:\s*- Source:\s*(.*?))?\n"
        r"(?:\s*- Quote:\s*(.*?)(?=\n- Evidence ID:|\Z))?",
        re.DOTALL,
    )
    for match in pattern.finditer(prompt):
        records.append(
            {
                "id": match.group(1).strip(),
                "source": " ".join(str(match.group(2) or "").split()),
                "quote": " ".join(str(match.group(3) or "").split()),
            }
        )
    if records:
        return records[:8]
    ids = list(dict.fromkeys(re.findall(r"\bmock-evidence-\d+\b", prompt)))[:4]
    if not ids:
        ids = ["mock-evidence-1", "mock-evidence-2", "mock-evidence-3", "mock-evidence-4"]
    return [{"id": evidence_id, "source": "", "quote": ""} for evidence_id in ids]


def _is_demo_evidence_id(evidence_id: str) -> bool:
    lowered = evidence_id.lower()
    return lowered.startswith(("mock-", "empty-", "placeholder-", "stub-"))


def _compact_sentence(text: str, limit: int = 110) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _layer_relevant_evidence_ids(
    title: str,
    focus: str,
    evidence_records: list[dict[str, str]],
) -> list[str]:
    records = [record for record in evidence_records if not _is_demo_evidence_id(record.get("id", ""))]
    if not records:
        return [record.get("id", "") for record in evidence_records if record.get("id")][:4]
    lowered = f"{title} {focus}".lower()
    if "executive" in lowered or "summary" in lowered or "recommendation" in lowered:
        return [record["id"] for record in records[:5]]

    keyword_groups: list[set[str]] = []
    if "시장" in title or "market" in lowered:
        keyword_groups = [
            {"market", "시장", "tam", "sam", "som", "statistics", "통계", "production", "acreage", "diagnostic", "diagnostics", "진단", "poc", "biosensor"},
        ]
    elif "경쟁" in title or "competitor" in lowered:
        keyword_groups = [
            {"competitor", "competitive", "경쟁", "company", "filing", "price", "pricing", "channel", "제품", "기업"},
        ]
    elif "jtbd" in lowered or "고객" in title:
        keyword_groups = [
            {"farmer", "farmers", "농가", "willingness", "pay", "interview", "field", "사용", "지불"},
        ]
    elif "재무" in title or "unit" in lowered:
        keyword_groups = [
            {"price", "pricing", "willingness", "pay", "cost", "margin", "cac", "ltv", "payback", "지불"},
        ]
    elif "리스크" in title or "반론" in title or "risk" in lowered:
        keyword_groups = [
            {"risk", "regulatory", "disease", "pathogen", "diagnostic", "field", "실증", "위험", "규제"},
        ]
    elif "로드맵" in title or "governance" in lowered or "kpi" in lowered:
        keyword_groups = [
            {"case", "practice", "implementation", "pilot", "field", "poc", "diagnostic", "실증", "운영"},
        ]

    if not keyword_groups:
        return [record["id"] for record in records[:4]]
    matched: list[str] = []
    for record in records:
        haystack = f"{record.get('source', '')} {record.get('quote', '')}".lower()
        if any(group & set(re.findall(r"[a-z0-9]+|[가-힣]{2,}", haystack)) for group in keyword_groups):
            matched.append(record["id"])
    return matched[:4]


def _source_backed_key_claim(title: str, focus: str, cited_ids: list[str]) -> str:
    if "Executive" in title or "Recommendation" in title:
        return "현재 확보 근거로는 시장성 결론을 확정하지 말고, 90일 검증 배치로 공식 통계·경쟁·현장 인터뷰를 먼저 채워야 한다."
    if not cited_ids:
        return f"{title}: 직접 출처가 아직 부족해 결론보다 검증 공백으로 다뤄야 한다."
    return f"{title}: 확보된 직접 근거 범위 안에서만 판단하고, 부족한 항목은 검증 공백으로 분리한다."


def _peer_source_scope(title: str, cited_ids: list[str], evidence: str) -> str:
    if cited_ids:
        refs = ", ".join(f"`{evidence_id}`" for evidence_id in cited_ids[:4])
        return f"{title} 판단은 {refs}가 직접 지지하는 범위로 제한해야 한다."
    return f"{title}에는 아직 직접 근거가 없어 {evidence} 수집 전 결론화하면 안 된다."


def _framework_for_title(title: str) -> str:
    if "경쟁" in title:
        return "Porter 5 Forces"
    if "고객" in title or "JTBD" in title:
        return "JTBD"
    if "재무" in title:
        return "Unit Economics"
    if "리스크" in title or "반론" in title:
        return "Scenario / Sensitivity"
    if "로드맵" in title or "운영" in title:
        return "RACI / Milestone Plan"
    if "KPI" in title or "성과" in title:
        return "North Star Tree"
    return "MECE Tree"
