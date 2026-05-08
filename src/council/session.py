"""Council session for report-derived debate agents."""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.agents.generator import DebateAgentSpec
from src.agents.mirofish import debate_agent_to_council_persona
from src.council.karpathy_prompts import (
    build_chairman_prompt,
    build_individual_prompt,
    build_peer_review_prompt,
)
from src.council.oasis_camel_runtime import build_protocol_trace
from src.council.parsers import RoundResult, parse_council_response
from src.council.round_layers import RoundLayer
from src.execution.gateway_v2 import GatewayV2
from src.execution.models import ModelGateway, ModelResult
from src.runtime.live_mode import LiveModeViolation


ProgressCallback = Callable[[dict], None]

_SECRETS_RE = re.compile(
    r"(?i)(api[_-]?key|token|authorization|bearer|password|secret)\s*[:=]\s*[^\s,}]+"
)


class CouncilProviderCallTimeout(TimeoutError):
    """Raised when a council model call exceeds the session watchdog."""


@dataclass(frozen=True)
class IndividualOpinion:
    persona_id: str
    key_claim: str
    body_claims: list[str] = field(default_factory=list)
    evidence_ref_ids: list[str] = field(default_factory=list)
    confidence_score: float = 0.0
    raw_response: str = ""


@dataclass(frozen=True)
class PeerComment:
    reviewer_id: str
    text: str
    stance: str = ""
    confidence_score: float = 0.0
    raw_response: str = ""


@dataclass
class PlateauDetector:
    """Detect confidence plateaus across structured council rounds."""

    window: int = 3
    tolerance: float = 0.05

    def should_stop(self, rounds: list[RoundResult]) -> tuple[bool, str]:
        if len(rounds) < self.window:
            return False, f"plateau check skipped: only {len(rounds)} rounds"

        recent = rounds[-self.window :]
        round_ids = [round_result.layer_id for round_result in recent]
        if len(set(round_ids)) != 1:
            return False, (
                f"plateau check skipped across mandatory layers {round_ids}: "
                "only repeated deliberation of the same layer can stop early"
            )

        confidences = [round_result.confidence_score for round_result in recent]
        spread = max(confidences) - min(confidences)
        if spread <= self.tolerance:
            return True, (
                f"plateau detected over {round_ids}: confidence spread "
                f"{spread:.3f} <= {self.tolerance:.2f}"
            )
        return False, (
            f"no plateau over {round_ids}: confidence spread "
            f"{spread:.3f} > {self.tolerance:.2f}"
        )


class Session:
    """Run the 10-layer council through GatewayV2 and parse structured results."""

    def __init__(
        self,
        gateway: GatewayV2,
        layers: list[RoundLayer],
        personas: list[Any],
        evidence_refs: list[Any] | None = None,
        plateau: PlateauDetector | None = None,
        active_persona_count: int | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.gateway = gateway
        self.layers = list(layers)
        self.personas = list(personas)
        self.evidence_refs = list(evidence_refs or [])
        self.plateau = plateau or PlateauDetector(window=11, tolerance=0.05)
        if active_persona_count is not None and active_persona_count < 1:
            raise ValueError("active_persona_count must be >= 1")
        self.active_persona_count = active_persona_count
        self.rounds: list[RoundResult] = []
        self.turn_transcript: list[dict[str, Any]] = []
        self.active_persona_ids_by_round: dict[int, list[str]] = {}
        self.protocol_traces_by_round: dict[int, dict[str, Any]] = {}
        self.stopped = False
        self.stop_reason: str | None = None
        self.progress_callback = progress_callback

    def run_one_round(self, round_no: int) -> RoundResult:
        if round_no < 1:
            raise ValueError("round_no must be >= 1")
        if round_no > len(self.layers):
            raise ValueError(f"round_no {round_no} exceeds configured layers ({len(self.layers)})")

        layer = self.layers[round_no - 1]
        active_personas = self._active_personas_for_round(round_no, layer)
        self.active_persona_ids_by_round[round_no] = [
            _persona_id(persona, idx)
            for idx, persona in enumerate(active_personas, start=1)
        ]
        protocol_trace = build_protocol_trace(
            round_no=round_no,
            layer_id=layer.layer_id,
            active_persona_ids=list(self.active_persona_ids_by_round[round_no]),
        )
        self.protocol_traces_by_round[round_no] = protocol_trace
        self._emit_progress(
            {
                "event": "council_round_start",
                "stage": "council_progress",
                "pipeline_stage": "council",
                "round": round_no,
                "layer": layer.layer_id,
                "active_persona_count": len(active_personas),
                "active_persona_ids": list(self.active_persona_ids_by_round[round_no]),
                "protocol_runtime": protocol_trace["runtime"],
                "protocol_phase_count": protocol_trace["phase_count"],
                "protocol_trace": protocol_trace,
            }
        )
        individuals = self._individual_stage(layer, active_personas, round_no)
        peer_reviews = self._peer_review_stage(individuals, layer, active_personas, round_no)
        round_result = self._chairman_synthesis(individuals, peer_reviews, layer)
        self.rounds.append(round_result)

        plateau, reason = self.plateau.should_stop(self.rounds)
        self.stop_reason = reason
        if plateau:
            self.stopped = True
        self._emit_progress(
            {
                "event": "council_round_done",
                "stage": "council_progress",
                "pipeline_stage": "council",
                "round": round_no,
                "layer": layer.layer_id,
                "score": round(round_result.confidence_score * 100),
                "stop_reason": self.stop_reason,
                "stopped": self.stopped,
            }
        )
        return round_result

    def run_all(self, allow_early_stop: bool = False) -> list[RoundResult]:
        max_rounds = min(10, len(self.layers))
        for round_no in range(1, max_rounds + 1):
            if allow_early_stop and self.stopped:
                break
            self.run_one_round(round_no)
        return list(self.rounds)

    def _active_personas_for_round(
        self,
        round_no: int,
        layer: RoundLayer,
    ) -> list[Any]:
        if not self.personas:
            return []
        limit = self.active_persona_count or len(self.personas)
        if limit >= len(self.personas):
            return list(self.personas)

        offset = ((round_no - 1) * limit) % len(self.personas)
        rotated = self.personas[offset:] + self.personas[:offset]
        selected: list[Any] = []
        emphasis_budget = max(1, limit // 3)
        emphasized = sorted(
            [persona for persona in self.personas if _persona_layer_score(persona, layer) > 0],
            key=lambda persona: _persona_layer_score(persona, layer),
            reverse=True,
        )
        for persona in emphasized[:emphasis_budget]:
            if persona not in selected:
                selected.append(persona)
            if len(selected) >= limit:
                return selected

        for persona in rotated:
            if persona in selected:
                continue
            selected.append(persona)
            if len(selected) >= limit:
                return selected
        return selected

    def _individual_stage(
        self,
        layer: RoundLayer,
        personas: list[Any],
        round_no: int,
    ) -> dict[str, IndividualOpinion]:
        prev_summary = _previous_summary(self.rounds)
        opinions: dict[str, IndividualOpinion] = {}
        for idx, persona in enumerate(personas, start=1):
            persona_id = _persona_id(persona, idx)
            prompt = build_individual_prompt(
                persona,
                layer,
                prev_summary,
                evidence_refs=self.evidence_refs,
            )
            try:
                result = self._call_gateway_with_progress(
                    round_no,
                    layer,
                    "individual",
                    persona_id,
                    prompt,
                )
            except Exception as exc:
                if _council_call_failure_kind(exc) in {"auth_or_policy_failure", "mock_live_output"}:
                    raise
                self._emit_progress(
                    {
                        "event": "council_persona_skipped",
                        "stage": "council_progress",
                        "pipeline_stage": "council",
                        "round": round_no,
                        "layer": layer.layer_id,
                        "council_stage": "individual",
                        "persona": persona_id,
                        "error_class": exc.__class__.__name__,
                        "error": _redact_text(exc),
                        "reason": "persona_call_failed",
                    }
                )
                continue
            self._record_turn(round_no, layer, "individual", persona_id, prompt, result)
            parsed = parse_council_response(getattr(result, "text", str(result)), layer)
            opinions[persona_id] = IndividualOpinion(
                persona_id=persona_id,
                key_claim=parsed.key_claim,
                body_claims=list(parsed.body_claims),
                evidence_ref_ids=list(parsed.evidence_ref_ids),
                confidence_score=parsed.confidence_score,
                raw_response=getattr(result, "text", str(result)),
            )
        return opinions

    def _peer_review_stage(
        self,
        individuals: dict[str, IndividualOpinion],
        layer: RoundLayer,
        personas: list[Any],
        round_no: int,
    ) -> dict[str, list[PeerComment]]:
        reviews: dict[str, list[PeerComment]] = {}
        for idx, persona in enumerate(personas, start=1):
            persona_id = _persona_id(persona, idx)
            blinded = [
                {
                    "key_claim": opinion.key_claim,
                    "body_claims": list(opinion.body_claims),
                    "confidence_score": opinion.confidence_score,
                }
                for other_id, opinion in individuals.items()
                if other_id != persona_id
            ]
            prompt = build_peer_review_prompt(
                persona,
                blinded,
                layer,
                evidence_refs=self.evidence_refs,
            )
            try:
                result = self._call_gateway_with_progress(
                    round_no,
                    layer,
                    "peer_review",
                    persona_id,
                    prompt,
                )
            except Exception as exc:
                if _council_call_failure_kind(exc) in {"auth_or_policy_failure", "mock_live_output"}:
                    raise
                self._emit_progress(
                    {
                        "event": "council_persona_skipped",
                        "stage": "council_progress",
                        "pipeline_stage": "council",
                        "round": round_no,
                        "layer": layer.layer_id,
                        "council_stage": "peer_review",
                        "persona": persona_id,
                        "error_class": exc.__class__.__name__,
                        "error": _redact_text(exc),
                        "reason": "persona_call_failed",
                    }
                )
                continue
            self._record_turn(round_no, layer, "peer_review", persona_id, prompt, result)
            text = getattr(result, "text", str(result))
            reviews[persona_id] = [_parse_peer_comment(persona_id, text)]
        return reviews

    def _chairman_synthesis(
        self,
        individuals: dict[str, IndividualOpinion],
        peer_reviews: dict[str, list[PeerComment]],
        layer: RoundLayer,
    ) -> RoundResult:
        prompt = build_chairman_prompt(
            individuals,
            peer_reviews,
            layer,
            evidence_refs=self.evidence_refs,
        )
        round_no = len(self.rounds) + 1
        try:
            result = self._call_gateway_with_progress(
                round_no,
                layer,
                "chairman",
                "chairman",
                prompt,
            )
        except CouncilProviderCallTimeout as exc:
            if not _chairman_timeout_fallback_enabled():
                raise
            fallback_text = _fallback_chairman_json(individuals, peer_reviews)
            timeout_note = f"chairman provider timed out; local synthesis fallback used: {_redact_text(exc)}"
            fallback_payload = json.loads(fallback_text)
            fallback_payload["next_actions"] = list(fallback_payload.get("next_actions") or []) + [timeout_note]
            fallback_payload["timeout_fallback"] = True
            fallback_text = json.dumps(fallback_payload, ensure_ascii=False)
            result = ModelResult(
                text=fallback_text,
                provider="local_timeout_fallback",
                model="deterministic_chairman_timeout_fallback",
            )
            self._emit_progress(
                {
                    "event": "council_chairman_timeout_fallback",
                    "stage": "council_progress",
                    "pipeline_stage": "council",
                    "round": round_no,
                    "layer": layer.layer_id,
                    "council_stage": "chairman",
                    "persona": "chairman",
                    "provider": "local_timeout_fallback",
                    "blocks_product_pass": True,
                    "reason": timeout_note,
                }
            )
        self._record_turn(round_no, layer, "chairman", "chairman", prompt, result)
        text = getattr(result, "text", str(result)) if result else _fallback_chairman_json(individuals, peer_reviews)
        parsed = parse_council_response(text, layer)
        if not parsed.disagreements:
            parsed = RoundResult(
                layer_id=parsed.layer_id,
                chapter_title=parsed.chapter_title,
                key_claim=parsed.key_claim,
                body_claims=list(parsed.body_claims),
                evidence_ref_ids=list(parsed.evidence_ref_ids),
                confidence_score=parsed.confidence_score,
                framework=parsed.framework,
                disagreements=_derive_disagreements(peer_reviews),
                next_actions=list(parsed.next_actions),
                raw_response=parsed.raw_response,
                framework_output=parsed.framework_output,
            )
        return parsed

    def _call_gateway_with_progress(
        self,
        round_no: int,
        layer: RoundLayer,
        council_stage: str,
        persona_id: str,
        prompt: str,
    ) -> Any:
        timeout_sec = _council_call_timeout_sec()
        provider_route = _council_provider_route(self.gateway)
        base_event = {
            "round": round_no,
            "layer": layer.layer_id,
            "stage": "council_progress",
            "pipeline_stage": "council",
            "council_stage": council_stage,
            "persona": persona_id,
            "provider_route": provider_route,
            "timeout_sec": timeout_sec,
            "prompt_chars": len(prompt),
        }
        self._emit_progress({"event": "council_provider_call_start", **base_event})
        started_at = time.monotonic()
        call_kwargs = {
            "council_stage": council_stage,
            "layer_id": layer.layer_id,
            "max_tokens": _council_stage_max_tokens(council_stage),
        }
        if timeout_sec > 0:
            call_kwargs["timeout"] = timeout_sec

        try:
            result = self._call_gateway_with_watchdog(prompt, timeout_sec, call_kwargs)
        except Exception as exc:
            failure_kind = _council_call_failure_kind(exc)
            if _is_empty_or_timeout_live_output(exc) and _compact_retry_enabled():
                elapsed_sec = round(time.monotonic() - started_at, 3)
                self._emit_progress(
                    {
                        "event": "council_provider_call_error",
                        **base_event,
                        "elapsed_sec": elapsed_sec,
                        "error_class": exc.__class__.__name__,
                        "error": _redact_text(exc),
                        "failure_kind": failure_kind,
                        "blocks_product_pass": True,
                        "retry": "compact_council_prompt",
                    }
                )
                retry_model = (
                    _opencode_empty_retry_model(self.gateway, provider_route, call_kwargs.get("model"))
                    if failure_kind == "empty_live_output"
                    else None
                )
                compact_prompt = _compact_council_retry_prompt(
                    council_stage=council_stage,
                    persona_id=persona_id,
                    layer=layer,
                    evidence_refs=self.evidence_refs,
                )
                retry_call_kwargs = dict(call_kwargs)
                if retry_model:
                    retry_call_kwargs["model"] = retry_model
                retry_event = dict(base_event)
                retry_event["prompt_chars"] = len(compact_prompt)
                retry_event["retry"] = "compact_council_prompt"
                if retry_model:
                    retry_event["retry_model"] = retry_model
                self._emit_progress({"event": "council_provider_call_start", **retry_event})
                retry_started_at = time.monotonic()
                try:
                    result = self._call_gateway_with_watchdog(compact_prompt, timeout_sec, retry_call_kwargs)
                    base_event = retry_event
                    started_at = retry_started_at
                except Exception as retry_exc:
                    self._emit_call_failure(retry_exc, retry_started_at, retry_event)
                    raise
            else:
                self._emit_call_failure(exc, started_at, base_event)
                raise

        elapsed_sec = round(time.monotonic() - started_at, 3)
        response_text = getattr(result, "text", str(result)) if result else ""
        self._emit_progress(
            {
                "event": "council_provider_call_done",
                **base_event,
                "elapsed_sec": elapsed_sec,
                "provider": str(getattr(result, "provider", "")),
                "model": str(getattr(result, "model", "")),
                "response_chars": len(response_text),
            }
        )
        return result

    def _call_gateway_with_watchdog(
        self,
        prompt: str,
        timeout_sec: float,
        call_kwargs: dict[str, Any],
    ) -> Any:
        if timeout_sec > 0:
            return _call_with_watchdog(
                self.gateway,
                "council",
                prompt,
                _chain_watchdog_timeout_sec(self.gateway, "council", timeout_sec),
                call_kwargs,
            )
        return self.gateway.call("council", prompt, **call_kwargs)

    def _emit_call_failure(
        self,
        exc: Exception,
        started_at: float,
        base_event: dict[str, Any],
    ) -> None:
        elapsed_sec = round(time.monotonic() - started_at, 3)
        if isinstance(exc, CouncilProviderCallTimeout):
            self._emit_progress(
                {
                    "event": "council_provider_call_timeout",
                    **base_event,
                    "elapsed_sec": elapsed_sec,
                    "blocks_product_pass": True,
                }
            )
            return
        self._emit_progress(
            {
                "event": "council_provider_call_error",
                **base_event,
                "elapsed_sec": elapsed_sec,
                "error_class": exc.__class__.__name__,
                "error": _redact_text(exc),
                "failure_kind": _council_call_failure_kind(exc),
                "blocks_product_pass": True,
            }
        )

    def _record_turn(
        self,
        round_no: int,
        layer: RoundLayer,
        stage: str,
        persona_id: str,
        prompt: str,
        result: Any,
    ) -> None:
        response_text = getattr(result, "text", str(result)) if result else ""
        provider = str(getattr(result, "provider", ""))
        self.turn_transcript.append(
            {
                "round": round_no,
                "layer_id": layer.layer_id,
                "stage": stage,
                "persona_id": persona_id,
                "provider": provider,
                "prompt_chars": len(prompt),
                "response_chars": len(response_text),
            }
        )
        self._emit_progress(
            {
                "event": "council_turn",
                "round": round_no,
                "layer": layer.layer_id,
                "stage": "council_progress",
                "pipeline_stage": "council",
                "council_stage": stage,
                "persona": persona_id,
                "provider": provider,
                "prompt_chars": len(prompt),
                "response_chars": len(response_text),
            }
        )
        if response_text:
            delta, visualization = _visualized_preview(
                response_text=response_text,
                round_no=round_no,
                layer=layer,
                council_stage=stage,
                persona_id=persona_id,
            )
            token_event = {
                "event": "council_persona_token",
                "round": round_no,
                "layer": layer.layer_id,
                "stage": "council_progress",
                "pipeline_stage": "council",
                "council_stage": stage,
                "persona": persona_id,
                "delta": delta,
            }
            token_event.update(visualization)
            self._emit_progress(
                token_event
            )

    def _emit_progress(self, event: dict[str, Any]) -> None:
        if self.progress_callback is not None:
            self.progress_callback(event)


@dataclass
class CouncilSession:
    report_id: str
    agents: list[DebateAgentSpec]
    topic: str = ""
    council_id: str | None = None
    council_dir: Path | None = None
    max_rounds: int = 5
    research_type: str = "exploratory"
    rounds: list[dict] = field(default_factory=list)
    consensus: str | None = None
    disagreements: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    stopped: bool = False
    stop_reason: str | None = None

    def run_round(self, *, model_gateway: ModelGateway) -> dict:
        runner = _load_council_runner()
        personas = [debate_agent_to_council_persona(agent) for agent in self.agents]
        round_num = len(self.rounds) + 1
        council_dir = self._ensure_council_dir()

        if round_num == 1:
            prompt_paths = runner._generate_round1_prompts(
                self._topic(),
                personas,
                self._council_id(),
                council_dir,
                total_rounds=self.max_rounds,
                research_type=self.research_type,
            )
        else:
            prompt_paths = runner._generate_roundN_prompts(
                self._topic(),
                personas,
                self._council_id(),
                council_dir,
                round_num,
                self._previous_results(),
                total_rounds=self.max_rounds,
                research_type=self.research_type,
            )

        responses = []
        result_records = []
        for agent, persona, prompt_path in zip(self.agents, personas, prompt_paths):
            prompt = prompt_path.read_text(encoding="utf-8")
            result = model_gateway.call(stage="council", prompt=prompt)
            result_record = _model_result_to_round_record(
                self._council_id(), round_num, persona, result.text
            )
            _write_round_result(council_dir, round_num, persona, result_record)
            result_records.append(result_record)
            responses.append(
                {
                    "agent": agent.name,
                    "text": result.text,
                    "provider": result.provider,
                    "prompt_path": str(prompt_path),
                }
            )

        avg_confidence, consensus = runner._measure_consensus(result_records)
        round_record = {
            "round": round_num,
            "responses": responses,
            "results": result_records,
            "prompt_files": [str(path) for path in prompt_paths],
            "confidence": avg_confidence,
            "consensus": consensus,
        }
        self.rounds.append(round_record)
        self.consensus = consensus
        self.disagreements = self.disagreements or ["requires further evidence review"]
        self.next_actions = self.next_actions or ["convert council critique into next research iteration"]
        self._update_plateau_state(runner)
        return round_record

    def _topic(self) -> str:
        return self.topic or f"Research report {self.report_id}"

    def _council_id(self) -> str:
        if self.council_id is None:
            self.council_id = f"council-{self.report_id}"
        return self.council_id

    def _ensure_council_dir(self) -> Path:
        if self.council_dir is None:
            self.council_dir = Path("src/council/council-logs") / self._council_id()
        self.council_dir.mkdir(parents=True, exist_ok=True)
        meta_path = self.council_dir / "meta.json"
        if not meta_path.exists():
            import json

            meta = {
                "council_id": self._council_id(),
                "topic": self._topic(),
                "personas": [debate_agent_to_council_persona(agent) for agent in self.agents],
                "max_rounds": self.max_rounds,
                "research_type": self.research_type,
            }
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.council_dir

    def _previous_results(self) -> list[dict[str, Any]]:
        if not self.rounds:
            return []
        return list(self.rounds[-1].get("results", []))

    def _update_plateau_state(self, runner: Any) -> None:
        all_rounds = {
            int(round_record["round"]): list(round_record.get("results", []))
            for round_record in self.rounds
        }
        plateau, reason = runner._detect_plateau(all_rounds, window=3, tolerance=0.05)
        if plateau:
            self.stopped = True
            self.stop_reason = reason
            self.next_actions = ["finalize council report because confidence plateaued"]


def _load_council_runner() -> Any:
    import importlib.util

    path = Path(__file__).resolve().parent / "council-runner.py"
    spec = importlib.util.spec_from_file_location("src.council.council_runner_runtime", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load council runner from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _council_call_timeout_sec() -> float:
    raw = (
        os.environ.get("MUCHANIPO_COUNCIL_PROVIDER_TIMEOUT_SEC")
        or os.environ.get("MUCHANIPO_COUNCIL_CALL_TIMEOUT_SEC")
        or ""
    )
    try:
        timeout_sec = float(raw)
    except (TypeError, ValueError):
        # Default: 20s per council call keeps serial 6-persona rounds under
        # ~2 minutes even with occasional retries, well inside the 15-minute
        # deep-profile budget.
        return 20.0
    return max(0.0, timeout_sec)


def _council_stage_max_tokens(council_stage: str) -> int:
    env_stage = f"MUCHANIPO_COUNCIL_{council_stage.upper()}_MAX_TOKENS"
    raw = (
        os.environ.get(env_stage)
        or os.environ.get("MUCHANIPO_OPENCODE_COUNCIL_MAX_TOKENS")
        or os.environ.get("MUCHANIPO_COUNCIL_MAX_TOKENS")
        or "4096"
    )
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 4096
    return max(1024, min(value, 8192))


def _chairman_timeout_fallback_enabled() -> bool:
    raw = (
        os.environ.get("MUCHANIPO_CHAIRMAN_TIMEOUT_FALLBACK")
        or os.environ.get("MUCHANIPO_COUNCIL_CHAIRMAN_TIMEOUT_FALLBACK")
        or ""
    )
    return raw.strip().casefold() in {"1", "true", "yes", "on", "allow", "enabled"}


def _council_provider_route(gateway: GatewayV2) -> str:
    stage_routes = getattr(gateway, "stage_routes", {}) or {}
    route = stage_routes.get("council")
    if route:
        return str(route)
    fallback_chain = getattr(gateway, "fallback_chain", {}) or {}
    chain = fallback_chain.get("council") or []
    return str(chain[0]) if chain else ""


def _chain_watchdog_timeout_sec(gateway: Any, stage: str, per_provider_timeout_sec: float) -> float:
    """Let each fallback provider consume its own bounded timeout plus handoff grace."""

    try:
        names = list((getattr(gateway, "fallback_chain", {}) or {}).get(stage) or [])
    except Exception:
        names = []
    candidate_count = max(1, len(names))
    if candidate_count <= 1:
        return float(per_provider_timeout_sec)
    grace = max(2.0, min(10.0, float(per_provider_timeout_sec) * 0.25))
    return float(per_provider_timeout_sec) * candidate_count + grace


def _compact_retry_enabled() -> bool:
    raw = os.environ.get("MUCHANIPO_COUNCIL_COMPACT_RETRY", "1")
    return raw.strip().casefold() not in {"0", "false", "no", "off", "disabled"}


def _is_empty_or_timeout_live_output(exc: Exception) -> bool:
    text = str(exc).casefold()
    if isinstance(exc, LiveModeViolation):
        return "empty or too-short" in text
    return (
        "empty or too-short" in text
        or "read operation timed out" in text
        or "council provider call timed out" in text
    )


def _council_call_failure_kind(exc: Exception) -> str:
    text = str(exc).casefold()
    if "empty or too-short" in text:
        return "empty_live_output"
    if isinstance(exc, CouncilProviderCallTimeout) or "timed out" in text:
        return "provider_timeout"
    if any(
        marker in text
        for marker in (
            "401",
            "403",
            "unauthorized",
            "forbidden",
            "invalid key",
            "invalid_key",
            "api key is not configured",
            "missing_credential",
            "mock_or_offline",
            "no live provider",
        )
    ):
        return "auth_or_policy_failure"
    if "rejected mock model result" in text or "placeholder model output" in text:
        return "mock_live_output"
    return "provider_error"


def _opencode_empty_retry_model(gateway: Any, provider_route: str, current_model: Any = None) -> str | None:
    if provider_route != "opencode":
        return None
    current = str(current_model or _provider_model(gateway, "opencode") or "")
    raw = os.environ.get("MUCHANIPO_COUNCIL_EMPTY_RETRY_MODELS", "opencode/mimo-v2.5-pro")
    candidates = [
        value.strip()
        for value in raw.split(",")
        if value.strip().startswith(("opencode/", "opencode-go/"))
    ]
    for candidate in candidates:
        if candidate != current:
            return candidate
    return None


def _provider_model(gateway: Any, provider_name: str) -> str:
    providers = getattr(gateway, "providers", {}) or {}
    provider = providers.get(provider_name) if isinstance(providers, dict) else None
    return str(getattr(provider, "model", "") or "")


def _compact_council_retry_prompt(
    *,
    council_stage: str,
    persona_id: str,
    layer: RoundLayer,
    evidence_refs: list[Any],
) -> str:
    lines = [
        "Return only valid JSON. No markdown.",
        f"Council stage: {council_stage}",
        f"Persona: {persona_id}",
        f"Layer: {layer.layer_id} / {getattr(layer, 'chapter_title', getattr(layer, 'title', ''))}",
        f"Question: {layer.focus_question}",
        "Use the evidence IDs below; do not invent IDs.",
    ]
    for ref in evidence_refs[:3]:
        ref_id = str(getattr(ref, "id", "") or "").strip()
        if not ref_id:
            continue
        title = str(getattr(ref, "source_title", "") or "untitled source").strip()
        quote = " ".join(str(getattr(ref, "quote", "") or "").split())[:160]
        lines.append(f"- {ref_id}: {title}{f' — {quote}' if quote else ''}")
    if council_stage == "peer_review":
        lines.append(
            'Schema: {"stance":"agree|challenge|mixed","critiques":["..."],'
            '"agreements":["..."],"suggested_revision":"...","confidence_score":0.0}'
        )
    else:
        lines.append(
            'Schema: {"key_claim":"...","body_claims":["..."],'
            '"evidence_ref_ids":["..."],"confidence_score":0.0,'
            '"disagreements":["..."],"next_actions":["..."]}'
        )
    return "\n".join(lines)


def _call_with_watchdog(
    gateway: GatewayV2,
    stage: str,
    prompt: str,
    timeout_sec: float,
    call_kwargs: dict[str, Any],
) -> Any:
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(gateway.call, stage, prompt, **call_kwargs)
    try:
        return future.result(timeout=timeout_sec)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise CouncilProviderCallTimeout(
            f"council provider call timed out after {timeout_sec:.3g}s"
        ) from exc
    finally:
        executor.shutdown(wait=False)


def _redact_text(value: Any) -> str:
    return _SECRETS_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", str(value))


def _model_result_to_round_record(
    council_id: str,
    round_num: int,
    persona: dict[str, Any],
    text: str,
) -> dict[str, Any]:
    return {
        "council_id": council_id,
        "round": round_num,
        "persona": persona["name"],
        "role": persona["role"],
        "position": "조건부찬성",
        "analysis": text,
        "updated_analysis": text,
        "key_points": [text] if text else [],
        "concerns": [],
        "remaining_concerns": [],
        "evidence": [],
        "confidence": 0.6,
        "position_changed": False,
    }


def _write_round_result(
    council_dir: Path,
    round_num: int,
    persona: dict[str, Any],
    result: dict[str, Any],
) -> None:
    import json

    persona_slug = persona["name"].replace(" ", "_")
    path = council_dir / f"round-{round_num}-{persona_slug}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def _persona_id(persona: Any, idx: int) -> str:
    if isinstance(persona, dict):
        return str(persona.get("persona_id") or persona.get("name") or f"persona-{idx}")
    return str(
        getattr(persona, "persona_id", None)
        or getattr(persona, "name", None)
        or f"persona-{idx}"
    )


def _persona_layer_score(persona: Any, layer: RoundLayer) -> int:
    text_parts: list[str] = []
    if isinstance(persona, dict):
        text_parts.extend([
            str(persona.get("name", "")),
            str(persona.get("role", "")),
            " ".join(str(item) for item in persona.get("expertise", []) or []),
        ])
        manifest = persona.get("manifest") or persona.get("agent_manifest") or {}
        if isinstance(manifest, dict):
            text_parts.append(" ".join(str(value) for value in manifest.values()))
    else:
        text_parts.extend([
            str(getattr(persona, "name", "")),
            str(getattr(persona, "role", "")),
        ])
        manifest = getattr(persona, "manifest", {}) or {}
        if isinstance(manifest, dict):
            text_parts.append(" ".join(str(value) for value in manifest.values()))

    haystack = " ".join(text_parts).casefold().replace("_", " ")
    score = 0
    for role in layer.emphasis_roles:
        needle = str(role).casefold().replace("_", " ")
        if needle and needle in haystack:
            score += 1
    return score


def _previous_summary(rounds: list[RoundResult]) -> str:
    if not rounds:
        return ""
    return "\n".join(
        f"- {round_result.layer_id}: {round_result.key_claim}"
        for round_result in rounds[-3:]
    )


def _parse_peer_comment(reviewer_id: str, text: str) -> PeerComment:
    import json

    stripped = text.strip()
    payload: Any = None
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
    if isinstance(payload, dict):
        critiques = payload.get("critiques") or payload.get("critique") or payload.get("suggested_revision")
        if isinstance(critiques, list):
            comment_text = "; ".join(str(item) for item in critiques if item)
        else:
            comment_text = str(critiques or payload.get("stance") or stripped)
        return PeerComment(
            reviewer_id=reviewer_id,
            text=comment_text,
            stance=str(payload.get("stance") or ""),
            confidence_score=_coerce_float(payload.get("confidence_score"), default=0.0),
            raw_response=text,
        )
    return PeerComment(reviewer_id=reviewer_id, text=stripped, raw_response=text)


def _derive_disagreements(peer_reviews: dict[str, list[PeerComment]]) -> list[str]:
    disagreements = [
        comment.text
        for comments in peer_reviews.values()
        for comment in comments
        if any(token in comment.text.lower() for token in ("disagree", "불일치", "risk", "리스크", "critique"))
    ]
    return disagreements or ["chairman synthesis found no explicit disagreement"]


def _fallback_chairman_json(
    individuals: dict[str, IndividualOpinion],
    peer_reviews: dict[str, list[PeerComment]],
) -> str:
    import json

    claims = [opinion.key_claim for opinion in individuals.values() if opinion.key_claim]
    comments = [
        comment.text
        for values in peer_reviews.values()
        for comment in values
        if comment.text
    ]
    return json.dumps(
        {
            "key_claim": claims[0] if claims else "Chairman synthesis unavailable",
            "body_claims": claims[1:] + comments,
            "confidence_score": 0.5,
            "disagreements": comments[:3],
            "next_actions": ["verify chairman synthesis with evidence"],
        },
        ensure_ascii=False,
    )


def _preview_text(text: str, limit: int = 1200) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 1].rstrip() + "…"


def _visualized_preview(
    *,
    response_text: str,
    round_no: int,
    layer: RoundLayer,
    council_stage: str,
    persona_id: str,
) -> tuple[str, dict[str, str]]:
    fallback = _preview_text(response_text)
    mode = os.environ.get("MUCHANIPO_COUNCIL_VISUALIZER", "").strip().lower()
    if mode not in {"ollama", "qwen", "qwen3.6", "local"}:
        return fallback, {"visualization_source": "raw"}

    model = os.environ.get("MUCHANIPO_COUNCIL_VISUALIZER_MODEL", "qwen3.6-a3b:latest").strip()
    if not model:
        model = "qwen3.6-a3b:latest"
    timeout = _env_float("MUCHANIPO_COUNCIL_VISUALIZER_TIMEOUT_SEC", 20.0)
    prompt = _visualizer_prompt(
        response_text=response_text,
        round_no=round_no,
        layer=layer,
        council_stage=council_stage,
        persona_id=persona_id,
    )
    try:
        from src.execution.providers.ollama import OllamaProvider

        result = OllamaProvider(model=model, timeout=timeout).call(
            stage="council_visualization",
            prompt=prompt,
            options={"temperature": 0.2, "num_predict": 256},
        )
        visualized = _strip_qwen_thinking(str(result.text or ""))
        if not visualized:
            raise ValueError("empty Ollama visualization")
        return (
            _preview_text(visualized, limit=420),
            {
                "visualization_source": "ollama",
                "visualizer_provider": str(result.provider),
                "visualizer_model": str(result.model),
            },
        )
    except Exception as exc:
        return (
            fallback,
            {
                "visualization_source": "raw_fallback",
                "visualizer_provider": "ollama",
                "visualizer_model": model,
                "visualizer_error": _preview_text(str(exc), limit=180),
            },
        )


def _visualizer_prompt(
    *,
    response_text: str,
    round_no: int,
    layer: RoundLayer,
    council_stage: str,
    persona_id: str,
) -> str:
    clipped = _preview_text(response_text, limit=2400)
    return (
        "You are a local-only UI renderer for Muchanipo council deliberation.\n"
        "Rewrite the source response as one concise Korean speech bubble.\n"
        "Do not add facts, numbers, sources, or conclusions that are not in the source.\n"
        "Preserve disagreement, risk, or confidence when present.\n"
        "Return only the speech bubble text, max two short sentences.\n\n"
        f"Round: {round_no}\n"
        f"Layer: {layer.layer_id} / {layer.chapter_title}\n"
        f"Council stage: {council_stage}\n"
        f"Persona: {persona_id}\n\n"
        f"Source response:\n{clipped}"
    )


def _strip_qwen_thinking(text: str) -> str:
    stripped = text.strip()
    if "</think>" in stripped:
        stripped = stripped.split("</think>", 1)[1].strip()
    if stripped.startswith("<think>") and "</think>" not in stripped:
        return ""
    return stripped


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
