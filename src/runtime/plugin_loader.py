#!/usr/bin/env python3
"""
Plugin slot loader — Composio식 slot abstraction의 최소 구현.

외부 YAML 의존성 없이 config/plugin-slots.yaml의 단순 slots 매핑만 읽는다.
런타임 등록(register_slot)은 설정 파일보다 우선한다.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "plugin-slots.yaml"

_REGISTERED_SLOTS: dict[str, Callable[..., Any]] = {}


class PluginSlotError(LookupError):
    """slot 설정 또는 import 실패를 호출자에게 명확히 전달한다."""


def _strip_inline_comment(value: str) -> str:
    """따옴표 없는 단순 YAML 값에서 inline comment를 제거한다."""
    return value.split("#", 1)[0].strip()


def _parse_slots_config(path: Path | None = None) -> dict[str, str]:
    """
    config/plugin-slots.yaml의 slots 매핑을 파싱한다.

    지원 범위는 의도적으로 좁다:
    slots:
      name: package.module:callable
    """
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise PluginSlotError(f"plugin slot config not found: {config_path}")

    slots: dict[str, str] = {}
    in_slots = False
    slots_indent: int | None = None

    for line_number, raw_line in enumerate(config_path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()

        if stripped == "slots:":
            in_slots = True
            slots_indent = indent
            continue

        if not in_slots:
            continue

        if slots_indent is not None and indent <= slots_indent:
            in_slots = False
            continue

        if ":" not in stripped:
            raise PluginSlotError(f"invalid slot entry at {config_path}:{line_number}")

        name, target = stripped.split(":", 1)
        name = name.strip()
        target = _strip_inline_comment(target).strip("\"'")

        if not name or not target:
            raise PluginSlotError(f"empty slot name or target at {config_path}:{line_number}")
        slots[name] = target

    if not slots:
        raise PluginSlotError(f"no slots configured in {config_path}")
    return slots


def _import_callable(dot_path: str) -> Callable[..., Any]:
    """module:function 형식의 경로를 callable로 해석한다."""
    if ":" not in dot_path:
        raise PluginSlotError(f"slot target must use module:callable format: {dot_path}")

    module_name, attr_name = dot_path.split(":", 1)
    if not module_name or not attr_name:
        raise PluginSlotError(f"slot target must use module:callable format: {dot_path}")

    try:
        module = importlib.import_module(module_name)
        impl = getattr(module, attr_name)
    except (ImportError, AttributeError) as exc:
        raise PluginSlotError(f"cannot import slot target {dot_path}: {exc}") from exc

    if not callable(impl):
        raise PluginSlotError(f"slot target is not callable: {dot_path}")
    return impl


def register_slot(name: str, impl: Callable[..., Any]) -> None:
    """현재 프로세스에서 slot 구현을 등록한다. 등록값은 파일 설정보다 우선한다."""
    if not name:
        raise PluginSlotError("slot name must not be empty")
    if not callable(impl):
        raise PluginSlotError(f"registered slot is not callable: {name}")
    _REGISTERED_SLOTS[name] = impl


def load_slot(name: str) -> Callable[..., Any]:
    """slot 이름으로 callable 구현을 로드한다."""
    if name in _REGISTERED_SLOTS:
        return _REGISTERED_SLOTS[name]

    slots = _parse_slots_config()
    try:
        target = slots[name]
    except KeyError as exc:
        available = ", ".join(sorted(slots))
        raise PluginSlotError(f"unknown plugin slot: {name}; available: {available}") from exc
    return _import_callable(target)


def default_model_router(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """기본 model_router slot: 호출 가능한 no-op 라우터."""
    return {"provider": "default", "model": None, "args": args, "kwargs": kwargs}


def tmux_runtime(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """기본 runtime slot: tmux 기반 런타임을 대신하는 no-op 스텁."""
    return {"runtime": "tmux", "started": False, "args": args, "kwargs": kwargs}


def default_notifier(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """기본 notifier slot: 알림을 보내지 않고 payload만 반환한다."""
    return {"notified": False, "args": args, "kwargs": kwargs}


__all__ = [
    "PluginSlotError",
    "default_model_router",
    "default_notifier",
    "load_slot",
    "register_slot",
    "tmux_runtime",
]
