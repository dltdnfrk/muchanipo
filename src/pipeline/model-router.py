#!/usr/bin/env python3
"""
MuchaNipo Model Router — 파이프라인 단계별 최적 모델 자동 선택 + 호출
====================================================================
멀티 프로바이더(Ollama/Claude/Codex/Kimi/MiniMax) API 인프라.
파이프라인 단계(task)에 따라 최적 모델을 자동 선택하고,
프로바이더별 호출 방식(REST/subprocess/prompt-file)으로 실행한다.

Usage:
  python model-router.py call --task ontology_extraction --prompt "텍스트..."
  python model-router.py call --task council_debate_deep --prompt "분석해줘" --persona "투자자"
  python model-router.py route --task council_debate_deep  # 어떤 모델이 선택되는지 확인
  python model-router.py providers                          # 사용 가능한 프로바이더 목록
  python model-router.py test                               # 모든 프로바이더 연결 테스트
  python model-router.py cost --task council_debate_deep --length 5000  # 비용 추정

순수 Python — 외부 라이브러리 없음 (urllib.request, subprocess, json만 사용).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "model-router.json"
PROMPTS_DIR = SCRIPT_DIR / "prompts"
LOGS_DIR = SCRIPT_DIR / "logs"

# ---------------------------------------------------------------------------
# Environment defaults
# ---------------------------------------------------------------------------
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
KIMI_API_KEY = os.environ.get("KIMI_API_KEY", "")
MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Ollama generation defaults
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "120"))
CODEX_TIMEOUT = int(os.environ.get("CODEX_TIMEOUT", "180"))


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _log(msg: str) -> None:
    print(f"[{_ts()}] {msg}", flush=True)


def _timestamp_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _slugify(text: str) -> str:
    """간단한 slug 변환: 공백→하이픈, 비영숫자 제거, 소문자."""
    import re
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:64]


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_config(path: Optional[Path] = None) -> dict[str, Any]:
    """model-router.json 설정 파일 로드."""
    cfg_path = path or CONFIG_PATH
    if not cfg_path.exists():
        _log(f"[WARN] 설정 파일 없음: {cfg_path}. 기본값 사용.")
        return {"providers": {}, "routing": {}, "multi_model_council": {}}
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Provider availability checks
# ---------------------------------------------------------------------------

def _ollama_available(host: str = OLLAMA_HOST) -> bool:
    """Ollama 서버 접속 가능 여부 확인."""
    url = f"{host}/api/tags"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ollama_models(host: str = OLLAMA_HOST) -> list[str]:
    """Ollama에 로드된 모델 목록 반환."""
    url = f"{host}/api/tags"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def _codex_available() -> bool:
    """Codex CLI 설치 여부 확인."""
    try:
        result = subprocess.run(
            ["codex", "--version"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "no_proxy": "*"},
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _codex_version() -> str:
    """Codex CLI 버전 반환."""
    try:
        result = subprocess.run(
            ["codex", "--version"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "no_proxy": "*"},
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unavailable"


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------

class ModelRouter:
    """파이프라인 단계별 최적 모델 자동 선택 + 호출 라우터."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config = load_config(config_path)
        self._ollama_cache: Optional[bool] = None
        self._ollama_models_cache: Optional[list[str]] = None
        self._codex_cache: Optional[bool] = None

    # --- Routing -----------------------------------------------------------

    def route(self, task: str) -> dict[str, Any]:
        """
        태스크에 최적 모델 반환.
        Returns: {model, provider, method, cost, fallback, note}
        """
        routing = self.config.get("routing", {})
        if task not in routing:
            return {
                "model": None,
                "provider": "unknown",
                "error": f"알 수 없는 태스크: {task}",
                "available_tasks": list(routing.keys()),
            }

        entry = routing[task]
        model = entry.get("model")

        # 1. code → LLM 불필요
        if model == "code":
            return {
                "model": None,
                "provider": "code",
                "method": "python-script",
                "cost": "$0",
                "note": entry.get("note", "LLM 불필요 — 규칙 기반 Python"),
            }

        # 2. 로컬 모델 → Ollama 상태 확인
        if self._is_ollama_model(model):
            if self._check_ollama():
                return {
                    "model": model,
                    "provider": "ollama",
                    "method": "rest-api",
                    "cost": "$0",
                    "note": entry.get("note", "로컬 Ollama"),
                }
            # Ollama 불가 → fallback
            fallback = entry.get("fallback")
            if fallback:
                _log(f"[ROUTE] Ollama 불가. fallback → {fallback}")
                return self._resolve_model(fallback, entry)
            return {
                "model": model,
                "provider": "ollama",
                "method": "rest-api",
                "cost": "$0",
                "available": False,
                "error": "Ollama 서버 접속 불가",
                "note": entry.get("note", ""),
            }

        # 3. Claude 모델
        if model in ("opus-4-6", "sonnet-4-6", "haiku-4-5"):
            return {
                "model": model,
                "provider": "claude",
                "method": "agent-tool",
                "cost": entry.get("cost", "$$"),
                "note": entry.get("note", "Claude Code Agent tool"),
                "alt": entry.get("alt"),
            }

        # 4. Codex 모델
        if model in ("o3", "gpt-5.4-codex"):
            return {
                "model": model,
                "provider": "codex",
                "method": "cli",
                "cost": entry.get("cost", "$$"),
                "note": entry.get("note", "Codex CLI"),
                "alt": entry.get("alt"),
            }

        # 5. Kimi
        if model.startswith("kimi"):
            available = bool(KIMI_API_KEY)
            result: dict[str, Any] = {
                "model": model,
                "provider": "kimi",
                "method": "rest-api",
                "cost": entry.get("cost", "$$"),
                "available": available,
                "note": entry.get("note", "Kimi API"),
            }
            if not available:
                fallback = entry.get("fallback")
                if fallback:
                    _log(f"[ROUTE] Kimi API 키 없음. fallback → {fallback}")
                    return self._resolve_model(fallback, entry)
                result["error"] = "KIMI_API_KEY 미설정"
            return result

        # 6. MiniMax
        if model.startswith("minimax"):
            available = bool(MINIMAX_API_KEY)
            result = {
                "model": model,
                "provider": "minimax",
                "method": "rest-api",
                "cost": entry.get("cost", "$$"),
                "available": available,
                "note": entry.get("note", "MiniMax API"),
            }
            if not available:
                fallback = entry.get("fallback")
                if fallback:
                    _log(f"[ROUTE] MiniMax API 키 없음. fallback → {fallback}")
                    return self._resolve_model(fallback, entry)
                result["error"] = "MINIMAX_API_KEY 미설정"
            return result

        # fallback: 모델명 기반 추정
        return {
            "model": model,
            "provider": "unknown",
            "method": "unknown",
            "cost": entry.get("cost", "?"),
            "note": entry.get("note", ""),
        }

    def _is_ollama_model(self, model: str) -> bool:
        """Ollama 로컬 모델인지 판별."""
        ollama_models = self.config.get("providers", {}).get("ollama", {}).get("models", [])
        if model in ollama_models:
            return True
        # 패턴 매칭: gemma*, nomic-embed-*
        return model.startswith("gemma") or model == "nomic-embed-text"

    def _check_ollama(self) -> bool:
        """Ollama 접속 가능 여부 (캐시)."""
        if self._ollama_cache is None:
            self._ollama_cache = _ollama_available()
        return self._ollama_cache

    def _check_codex(self) -> bool:
        """Codex CLI 사용 가능 여부 (캐시)."""
        if self._codex_cache is None:
            self._codex_cache = _codex_available()
        return self._codex_cache

    def _resolve_model(self, model: str, entry: dict[str, Any]) -> dict[str, Any]:
        """모델명으로 provider/method를 결정."""
        if model in ("opus-4-6", "sonnet-4-6", "haiku-4-5"):
            return {
                "model": model,
                "provider": "claude",
                "method": "agent-tool",
                "cost": entry.get("cost", "$$"),
                "note": f"fallback → {model}",
                "is_fallback": True,
            }
        if model in ("o3", "gpt-5.4-codex"):
            return {
                "model": model,
                "provider": "codex",
                "method": "cli",
                "cost": entry.get("cost", "$$"),
                "note": f"fallback → {model}",
                "is_fallback": True,
            }
        if self._is_ollama_model(model):
            return {
                "model": model,
                "provider": "ollama",
                "method": "rest-api",
                "cost": "$0",
                "note": f"fallback → {model}",
                "is_fallback": True,
            }
        return {
            "model": model,
            "provider": "unknown",
            "method": "unknown",
            "note": f"fallback → {model}",
            "is_fallback": True,
        }

    # --- Call dispatching ---------------------------------------------------

    def call(self, task: str, prompt: str, **kwargs: Any) -> dict[str, Any]:
        """
        태스크에 맞는 모델로 실제 호출.
        Returns: {provider, model, response, elapsed_ms, error?}
        """
        route_info = self.route(task)
        provider = route_info.get("provider", "unknown")
        model = route_info.get("model")

        if route_info.get("error"):
            return {
                "provider": provider,
                "model": model,
                "response": None,
                "error": route_info["error"],
            }

        if provider == "code":
            return {
                "provider": "code",
                "model": None,
                "response": "[code] LLM 호출 불필요. 해당 스크립트를 직접 실행하세요.",
                "note": route_info.get("note", ""),
            }

        system = kwargs.get("system")
        persona = kwargs.get("persona")

        t0 = time.monotonic()
        try:
            if provider == "ollama":
                response = self.call_ollama(model, prompt, system=system)
            elif provider == "codex":
                response = self.call_codex(model, prompt)
            elif provider == "claude":
                result = self.generate_claude_prompt(task, prompt, system=system, persona=persona)
                return {
                    "provider": "claude",
                    "model": model,
                    "method": "prompt-file",
                    "prompt_file": result["prompt_file"],
                    "response": None,
                    "note": "Claude Code Agent tool로 실행하세요. 프롬프트 파일이 생성되었습니다.",
                    "instruction": result["instruction"],
                }
            elif provider == "kimi":
                response = self.call_kimi(model, prompt, system=system)
            elif provider == "minimax":
                response = self.call_minimax(model, prompt, system=system)
            else:
                return {
                    "provider": provider,
                    "model": model,
                    "response": None,
                    "error": f"지원하지 않는 프로바이더: {provider}",
                }
        except Exception as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            # fallback 시도
            fallback_result = self._try_fallback(task, prompt, kwargs, str(e))
            if fallback_result:
                fallback_result["original_error"] = str(e)
                return fallback_result
            return {
                "provider": provider,
                "model": model,
                "response": None,
                "error": str(e),
                "elapsed_ms": elapsed,
            }

        elapsed = int((time.monotonic() - t0) * 1000)
        return {
            "provider": provider,
            "model": model,
            "response": response,
            "elapsed_ms": elapsed,
        }

    def _try_fallback(
        self, task: str, prompt: str, kwargs: dict[str, Any], original_error: str
    ) -> Optional[dict[str, Any]]:
        """프로바이더 실패 시 fallback 모델로 재시도."""
        routing = self.config.get("routing", {})
        entry = routing.get(task, {})
        fallback = entry.get("fallback") or entry.get("alt")
        if not fallback:
            return None

        _log(f"[FALLBACK] {entry.get('model')} 실패 → {fallback} 시도")
        resolved = self._resolve_model(fallback, entry)
        fb_provider = resolved["provider"]
        fb_model = resolved["model"]

        try:
            t0 = time.monotonic()
            if fb_provider == "ollama":
                response = self.call_ollama(fb_model, prompt, system=kwargs.get("system"))
            elif fb_provider == "codex":
                response = self.call_codex(fb_model, prompt)
            elif fb_provider == "claude":
                result = self.generate_claude_prompt(
                    task, prompt,
                    system=kwargs.get("system"),
                    persona=kwargs.get("persona"),
                )
                return {
                    "provider": "claude",
                    "model": fb_model,
                    "method": "prompt-file",
                    "prompt_file": result["prompt_file"],
                    "response": None,
                    "is_fallback": True,
                    "note": "fallback → Claude Code Agent tool",
                    "instruction": result["instruction"],
                }
            else:
                return None
            elapsed = int((time.monotonic() - t0) * 1000)
            return {
                "provider": fb_provider,
                "model": fb_model,
                "response": response,
                "elapsed_ms": elapsed,
                "is_fallback": True,
            }
        except Exception:
            return None

    # --- Ollama provider ---------------------------------------------------

    def call_ollama(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        stream: bool = False,
    ) -> str:
        """
        Ollama REST API 호출 (localhost:11434).
        urllib.request 사용 — 외부 의존 없음.
        """
        url = f"{OLLAMA_HOST}/api/generate"
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
        }
        if system:
            payload["system"] = system

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT) as resp:
                body = resp.read().decode("utf-8")

            if not stream:
                result = json.loads(body)
                return result.get("response", "")

            # streaming: 각 줄이 JSON, response 필드를 이어붙임
            parts: list[str] = []
            for line in body.strip().splitlines():
                if line.strip():
                    chunk = json.loads(line)
                    parts.append(chunk.get("response", ""))
            return "".join(parts)

        except urllib.error.URLError as e:
            raise ConnectionError(f"Ollama 접속 실패 ({OLLAMA_HOST}): {e}") from e
        except json.JSONDecodeError as e:
            raise ValueError(f"Ollama 응답 파싱 실패: {e}") from e

    def call_ollama_embed(self, text: str, model: str = "nomic-embed-text") -> list[float]:
        """
        Ollama 임베딩 API 호출.
        Returns: 768-dim float vector.
        """
        url = f"{OLLAMA_HOST}/api/embed"
        payload = {"model": model, "input": text}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            embeddings = body.get("embeddings", [])
            if embeddings:
                return embeddings[0]
            return []
        except Exception as e:
            raise ConnectionError(f"Ollama embed 실패: {e}") from e

    # --- Codex provider ----------------------------------------------------

    def call_codex(self, model: str, prompt: str) -> str:
        """
        Codex CLI 호출 (subprocess).
        `no_proxy="*" codex exec --full-auto -m {model} "{prompt}"`
        """
        env = {**os.environ, "no_proxy": "*"}
        cmd = [
            "codex", "exec",
            "--full-auto",
            "-m", model,
            prompt,
        ]

        _log(f"[CODEX] model={model}, prompt_len={len(prompt)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=CODEX_TIMEOUT,
                env=env,
                cwd=str(SCRIPT_DIR),
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()[:500]
                raise RuntimeError(f"Codex 실행 실패 (rc={result.returncode}): {stderr}")
            return result.stdout.strip()
        except FileNotFoundError:
            raise RuntimeError("Codex CLI가 설치되지 않았습니다. `npm i -g @openai/codex` 실행 필요.")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Codex 호출 타임아웃 ({CODEX_TIMEOUT}초)")

    # --- Claude provider (prompt file) -------------------------------------

    def generate_claude_prompt(
        self,
        task: str,
        prompt: str,
        system: Optional[str] = None,
        persona: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Claude Code Agent용 프롬프트 파일 생성.
        .omc/autoresearch/prompts/{task}-{timestamp}.md로 저장.
        Claude Code가 이 파일을 읽어서 Agent tool로 실행.
        Returns: {prompt_file, instruction, model}
        """
        PROMPTS_DIR.mkdir(parents=True, exist_ok=True)

        route_info = self.route(task)
        model = route_info.get("model", "sonnet-4-6")
        ts = _timestamp_id()
        task_slug = _slugify(task)
        filename = f"{task_slug}-{ts}.md"
        prompt_path = PROMPTS_DIR / filename

        # 프롬프트 파일 작성
        lines: list[str] = []
        lines.append(f"# MuchaNipo Task: {task}")
        lines.append(f"- Model: {model}")
        lines.append(f"- Generated: {datetime.now(timezone.utc).isoformat()}")
        lines.append(f"- Task: {task}")
        if persona:
            lines.append(f"- Persona: {persona}")
        lines.append("")

        if system:
            lines.append("## System")
            lines.append("")
            lines.append(system)
            lines.append("")

        if persona:
            lines.append("## Persona Context")
            lines.append("")
            lines.append(f"당신은 **{persona}** 관점에서 분석합니다.")
            lines.append("")

        lines.append("## Prompt")
        lines.append("")
        lines.append(prompt)
        lines.append("")

        prompt_path.write_text("\n".join(lines), encoding="utf-8")

        instruction = (
            f"Agent tool로 실행: model={model}, "
            f"prompt 파일 → {prompt_path}"
        )

        _log(f"[CLAUDE] 프롬프트 파일 생성: {prompt_path}")

        return {
            "prompt_file": str(prompt_path),
            "instruction": instruction,
            "model": model,
        }

    # --- Kimi provider (placeholder) ---------------------------------------

    def call_kimi(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
    ) -> str:
        """
        Kimi API 호출.
        KIMI_API_KEY 설정 시 활성화. 미설정 시 에러.
        """
        if not KIMI_API_KEY:
            raise RuntimeError(
                "KIMI_API_KEY 환경변수가 설정되지 않았습니다. "
                "Kimi 구독 후 설정하세요."
            )

        # Kimi API endpoint (placeholder — 실제 엔드포인트로 교체 필요)
        url = "https://api.moonshot.cn/v1/chat/completions"

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {KIMI_API_KEY}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            choices = body.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""
        except urllib.error.URLError as e:
            raise ConnectionError(f"Kimi API 호출 실패: {e}") from e

    # --- MiniMax provider (placeholder) ------------------------------------

    def call_minimax(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
    ) -> str:
        """
        MiniMax API 호출.
        MINIMAX_API_KEY 설정 시 활성화. 미설정 시 에러.
        """
        if not MINIMAX_API_KEY:
            raise RuntimeError(
                "MINIMAX_API_KEY 환경변수가 설정되지 않았습니다. "
                "MiniMax 구독 후 설정하세요."
            )

        # MiniMax API endpoint (placeholder — 실제 엔드포인트로 교체 필요)
        url = "https://api.minimaxi.chat/v1/text/chatcompletion_v2"

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {MINIMAX_API_KEY}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            choices = body.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""
        except urllib.error.URLError as e:
            raise ConnectionError(f"MiniMax API 호출 실패: {e}") from e

    # --- OpenRouter fallback -----------------------------------------------

    def call_openrouter(
        self,
        model: str,
        prompt: str,
        system: Optional[str] = None,
    ) -> str:
        """
        OpenRouter 범용 fallback.
        OPENROUTER_API_KEY 설정 시 활성화.
        """
        if not OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY 환경변수가 설정되지 않았습니다.")

        url = "https://openrouter.ai/api/v1/chat/completions"

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "messages": messages,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer": "https://muchanipo.local",
                "X-Title": "MuchaNipo",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            choices = body.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""
        except urllib.error.URLError as e:
            raise ConnectionError(f"OpenRouter API 호출 실패: {e}") from e

    # --- Multi-Model Council -----------------------------------------------

    def council_multi_model(
        self,
        personas: list[dict[str, Any]],
        topic: str,
        system: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        각 페르소나를 다른 모델로 실행하여 진짜 다관점 토론.
        model-router.json의 multi_model_council 설정 사용.

        Returns: [{persona, model, provider, response|prompt_file, elapsed_ms}]
        """
        mmc = self.config.get("multi_model_council", {})
        example = mmc.get("example_5_personas", {})

        # 역할→모델 매핑 (설정 기반)
        role_model_map: dict[str, str] = {}
        for key, value in example.items():
            # "persona_1_investor": "opus-4-6 (비판적 분석)" → role=investor, model=opus-4-6
            parts = key.split("_")
            if len(parts) >= 3:
                role = parts[2]  # investor, scientist, farmer, ...
                model_name = value.split(" ")[0] if isinstance(value, str) else value
                role_model_map[role] = model_name

        # 기본 매핑 (설정에 없는 역할용)
        default_map: dict[str, str] = {
            "투자자": "opus-4-6",
            "기술전문가": "o3",
            "사용자대표": "sonnet-4-6",
            "규제전문가": "kimi-k2",
            "경쟁분석가": "gemma4:26b",
        }
        # 역할 한글명 매핑도 추가
        role_model_map.update({
            "investor": "opus-4-6",
            "scientist": "o3",
            "farmer": "sonnet-4-6",
            "regulator": "kimi-k2",
            "competitor": "gemma4:26b",
        })

        results: list[dict[str, Any]] = []
        for persona in personas:
            role = persona.get("role", "")
            name = persona.get("name", role)

            # 모델 선택: 역할 매핑 → 한글 매핑 → 기본값
            role_key = _slugify(role)
            model = role_model_map.get(role_key) or default_map.get(role) or "sonnet-4-6"

            persona_prompt = (
                f"당신은 **{name}** ({role})입니다.\n"
                f"전문 분야: {', '.join(persona.get('expertise', []))}\n"
                f"관점: {persona.get('perspective_bias', '')}\n"
                f"논증 스타일: {persona.get('argument_style', '')}\n\n"
                f"주제: {topic}\n\n"
                f"위 주제에 대해 당신의 관점에서 심층 분석해주세요."
            )

            call_result = self._call_by_model(model, persona_prompt, system=system)
            call_result["persona"] = name
            call_result["role"] = role
            results.append(call_result)

        return results

    def _call_by_model(
        self, model: str, prompt: str, system: Optional[str] = None
    ) -> dict[str, Any]:
        """모델명으로 직접 호출 (route 우회)."""
        t0 = time.monotonic()

        try:
            if self._is_ollama_model(model):
                response = self.call_ollama(model, prompt, system=system)
                provider = "ollama"
            elif model in ("opus-4-6", "sonnet-4-6", "haiku-4-5"):
                result = self.generate_claude_prompt("council_debate_deep", prompt, system=system)
                return {
                    "model": model,
                    "provider": "claude",
                    "method": "prompt-file",
                    "prompt_file": result["prompt_file"],
                    "response": None,
                    "note": "Claude Agent tool로 실행 필요",
                }
            elif model in ("o3", "gpt-5.4-codex"):
                response = self.call_codex(model, prompt)
                provider = "codex"
            elif model.startswith("kimi"):
                response = self.call_kimi(model, prompt, system=system)
                provider = "kimi"
            elif model.startswith("minimax"):
                response = self.call_minimax(model, prompt, system=system)
                provider = "minimax"
            else:
                return {"model": model, "provider": "unknown", "error": f"알 수 없는 모델: {model}"}

            elapsed = int((time.monotonic() - t0) * 1000)
            return {
                "model": model,
                "provider": provider,
                "response": response,
                "elapsed_ms": elapsed,
            }
        except Exception as e:
            elapsed = int((time.monotonic() - t0) * 1000)
            return {
                "model": model,
                "provider": "error",
                "response": None,
                "error": str(e),
                "elapsed_ms": elapsed,
            }

    # --- Provider testing --------------------------------------------------

    def test_providers(self) -> dict[str, dict[str, Any]]:
        """모든 프로바이더 연결 상태 테스트."""
        results: dict[str, dict[str, Any]] = {}

        # Ollama
        ollama_ok = _ollama_available()
        ollama_models = _ollama_models() if ollama_ok else []
        results["ollama"] = {
            "available": ollama_ok,
            "host": OLLAMA_HOST,
            "models": ollama_models,
        }
        if ollama_ok:
            # 실제 간단한 호출 테스트
            try:
                t0 = time.monotonic()
                resp = self.call_ollama(
                    ollama_models[0] if ollama_models else "gemma4:latest",
                    "Say OK.",
                    system="Respond with exactly one word.",
                )
                elapsed = int((time.monotonic() - t0) * 1000)
                results["ollama"]["test_response"] = resp[:100]
                results["ollama"]["test_elapsed_ms"] = elapsed
            except Exception as e:
                results["ollama"]["test_error"] = str(e)

        # Codex
        codex_ok = _codex_available()
        results["codex"] = {
            "available": codex_ok,
            "version": _codex_version() if codex_ok else "not installed",
        }

        # Claude (Claude Code 내에서만 사용 가능)
        results["claude"] = {
            "available": True,
            "note": "Claude Code Agent tool 기반. 항상 사용 가능.",
            "models": ["opus-4-6", "sonnet-4-6", "haiku-4-5"],
        }

        # Kimi
        results["kimi"] = {
            "available": bool(KIMI_API_KEY),
            "api_key_set": bool(KIMI_API_KEY),
            "note": "KIMI_API_KEY 설정 필요" if not KIMI_API_KEY else "API 키 설정됨",
        }

        # MiniMax
        results["minimax"] = {
            "available": bool(MINIMAX_API_KEY),
            "api_key_set": bool(MINIMAX_API_KEY),
            "note": "MINIMAX_API_KEY 설정 필요" if not MINIMAX_API_KEY else "API 키 설정됨",
        }

        # OpenRouter (범용 fallback)
        results["openrouter"] = {
            "available": bool(OPENROUTER_API_KEY),
            "api_key_set": bool(OPENROUTER_API_KEY),
            "note": "범용 fallback. OPENROUTER_API_KEY 설정 필요" if not OPENROUTER_API_KEY else "API 키 설정됨",
        }

        return results

    # --- Cost estimation ---------------------------------------------------

    def estimate_cost(self, task: str, prompt_length: int) -> dict[str, Any]:
        """예상 비용 계산."""
        route_info = self.route(task)
        provider = route_info.get("provider", "unknown")
        model = route_info.get("model")

        # 토큰 추정: 한글 ~2 chars/token, 영어 ~4 chars/token (대략)
        est_tokens = prompt_length // 3  # 한영 혼합 평균

        cost_table: dict[str, dict[str, float]] = {
            "ollama": {"input_per_1k": 0.0, "output_per_1k": 0.0},
            "code": {"input_per_1k": 0.0, "output_per_1k": 0.0},
            "claude": {
                "opus-4-6": {"input_per_1k": 0.015, "output_per_1k": 0.075},
                "sonnet-4-6": {"input_per_1k": 0.003, "output_per_1k": 0.015},
                "haiku-4-5": {"input_per_1k": 0.0008, "output_per_1k": 0.004},
            },
            "codex": {
                "o3": {"input_per_1k": 0.010, "output_per_1k": 0.040},
                "gpt-5.4-codex": {"input_per_1k": 0.002, "output_per_1k": 0.008},
            },
        }

        if provider in ("ollama", "code"):
            return {
                "task": task,
                "model": model,
                "provider": provider,
                "estimated_tokens": est_tokens,
                "estimated_cost_usd": 0.0,
                "note": "로컬 또는 규칙 기반. 비용 없음.",
            }

        provider_rates = cost_table.get(provider, {})
        if isinstance(provider_rates, dict) and model in provider_rates:
            rates = provider_rates[model]
        else:
            rates = {"input_per_1k": 0.003, "output_per_1k": 0.015}  # 기본값

        # output 토큰은 input의 ~1.5배 추정
        est_output_tokens = int(est_tokens * 1.5)
        input_cost = (est_tokens / 1000) * rates.get("input_per_1k", 0)
        output_cost = (est_output_tokens / 1000) * rates.get("output_per_1k", 0)
        total = input_cost + output_cost

        return {
            "task": task,
            "model": model,
            "provider": provider,
            "estimated_input_tokens": est_tokens,
            "estimated_output_tokens": est_output_tokens,
            "estimated_cost_usd": round(total, 4),
            "rates": rates,
            "note": route_info.get("note", ""),
            "oauth_note": "OAuth 사용 시 실제 API 비용 없음 (세션 내 토큰 소비)",
        }

    # --- List all tasks ----------------------------------------------------

    def list_tasks(self) -> list[dict[str, str]]:
        """모든 라우팅 가능한 태스크 목록."""
        routing = self.config.get("routing", {})
        tasks: list[dict[str, str]] = []
        for task_id, entry in routing.items():
            tasks.append({
                "task": task_id,
                "step": entry.get("step", ""),
                "model": entry.get("model", ""),
                "cost": entry.get("cost", ""),
            })
        return tasks

    # --- List providers from config ----------------------------------------

    def list_providers(self) -> dict[str, Any]:
        """설정 파일의 프로바이더 목록 + 실시간 상태."""
        providers = self.config.get("providers", {})
        status = self.test_providers()
        result: dict[str, Any] = {}
        for name, info in providers.items():
            result[name] = {
                **info,
                "status": status.get(name, {}),
            }
        return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MuchaNipo Model Router — 파이프라인 단계별 최적 모델 자동 선택 + 호출",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", help="사용 가능한 명령")

    # call
    p_call = sub.add_parser("call", help="태스크에 맞는 모델로 실제 호출")
    p_call.add_argument("--task", required=True, help="파이프라인 태스크명")
    p_call.add_argument("--prompt", required=True, help="프롬프트 텍스트")
    p_call.add_argument("--system", help="시스템 프롬프트 (선택)")
    p_call.add_argument("--persona", help="페르소나명 (선택)")

    # route
    p_route = sub.add_parser("route", help="어떤 모델이 선택되는지 확인")
    p_route.add_argument("--task", required=True, help="파이프라인 태스크명")

    # providers
    sub.add_parser("providers", help="사용 가능한 프로바이더 목록 + 상태")

    # test
    sub.add_parser("test", help="모든 프로바이더 연결 테스트")

    # tasks
    sub.add_parser("tasks", help="모든 라우팅 가능한 태스크 목록")

    # cost
    p_cost = sub.add_parser("cost", help="예상 비용 계산")
    p_cost.add_argument("--task", required=True, help="파이프라인 태스크명")
    p_cost.add_argument("--length", type=int, default=1000, help="프롬프트 문자 수")

    # council
    p_council = sub.add_parser("council", help="Multi-Model Council 토론 실행")
    p_council.add_argument("--topic", required=True, help="토론 주제")
    p_council.add_argument("--personas", type=int, default=5, help="페르소나 수")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    router = ModelRouter()

    if args.command == "call":
        result = router.call(
            args.task, args.prompt,
            system=args.system,
            persona=args.persona,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "route":
        result = router.route(args.task)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "providers":
        result = router.list_providers()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "test":
        result = router.test_providers()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        # 요약
        ok_count = sum(1 for v in result.values() if v.get("available"))
        total = len(result)
        print(f"\n{ok_count}/{total} 프로바이더 활성화")

    elif args.command == "tasks":
        tasks = router.list_tasks()
        # 테이블 형태 출력
        print(f"{'Task':<30} {'Model':<20} {'Cost':<8} Step")
        print("-" * 90)
        for t in tasks:
            print(f"{t['task']:<30} {t['model']:<20} {t['cost']:<8} {t['step']}")

    elif args.command == "cost":
        result = router.estimate_cost(args.task, args.length)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.command == "council":
        # 기본 페르소나 풀에서 N명 선택
        default_personas = [
            {"name": "이준혁", "role": "투자자", "expertise": ["벤처캐피털", "ROI 분석"], "perspective_bias": "수익성 중심", "argument_style": "데이터 기반"},
            {"name": "박서연", "role": "기술전문가", "expertise": ["AI/ML", "시스템 설계"], "perspective_bias": "기술 타당성 중심", "argument_style": "분석적"},
            {"name": "김민지", "role": "사용자대표", "expertise": ["UX 리서치", "고객 여정"], "perspective_bias": "사용자 관점", "argument_style": "공감적"},
            {"name": "정태호", "role": "규제전문가", "expertise": ["농약 관리법", "식물방역법"], "perspective_bias": "법적 리스크 중심", "argument_style": "조문 인용"},
            {"name": "최윤아", "role": "경쟁분석가", "expertise": ["시장 분석", "경쟁 벤치마킹"], "perspective_bias": "경쟁 우위 중심", "argument_style": "비교 분석"},
        ]
        selected = default_personas[: args.personas]
        results = router.council_multi_model(selected, args.topic)
        print(json.dumps(results, ensure_ascii=False, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
