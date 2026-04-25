#!/usr/bin/env python3
"""Fail-closed safety gate for automated MuchaNipo surfaces.

The functions in this module are intentionally small and dependency-free.
They are meant to be called before automation changes rubric/manifest state,
writes files, evolves config, or stores evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "safety-immutable.yaml"
AUDIT_PATH = REPO_ROOT / ".omc" / "autoresearch" / "logs" / "safety-audit.jsonl"

IMMUTABLE_AXES = ("citation_fidelity", "reliability")
DEFAULT_DENY_WRITE = (
    "~/.ssh",
    "~/.aws",
    "~/.config",
    "/etc",
    "~/Library/Keychains",
)
DEFAULT_DENY_EVOLVE = (
    "modify_axis_weight:citation_fidelity",
    "modify_axis_weight:reliability",
    "modify_critic_addendum",
    "shift_endpoint",
    "remove_safety_pattern",
)

DANGEROUS_VERBS = {
    "attack",
    "bypass",
    "crack",
    "credential",
    "ddos",
    "delete",
    "disable",
    "dump",
    "exfiltrate",
    "exploit",
    "hack",
    "impersonate",
    "override",
    "phish",
    "scrape",
    "steal",
    "탈취",
    "우회",
    "해킹",
    "삭제",
    "사칭",
    "유출",
}
HIGH_RISK_TARGETS = {
    "credential",
    "keychain",
    "password",
    "private_key",
    "secret",
    "token",
    "wallet",
    "계정",
    "비밀번호",
    "인증",
    "토큰",
}
HIGH_RISK_TOOLS = {
    "burp",
    "hydra",
    "metasploit",
    "nmap",
    "sqlmap",
    "wireshark",
}

SECRET_PATTERNS: Sequence[Tuple[str, re.Pattern[str]]] = (
    ("AWS_ACCESS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("AWS_SECRET_KEY", re.compile(r"\b(?<![A-Za-z0-9/+=])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])\b")),
    ("GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b")),
    ("OPENAI_KEY", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("ANTHROPIC_KEY", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("LINEAR_KEY", re.compile(r"\blin_api_[A-Za-z0-9]{20,}\b")),
)
PII_PATTERNS: Sequence[Tuple[str, re.Pattern[str]]] = (
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("KOREAN_PHONE", re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b")),
    ("KOREAN_RRN", re.compile(r"\b\d{6}-?[1-4]\d{6}\b")),
    ("KOREAN_BIZ_NO", re.compile(r"\b\d{3}-?\d{2}-?\d{5}\b")),
)
KOREAN_REAL_NAME_HINT = re.compile(r"(?:실명|이름|대표|담당자|고객)\s*[:= ]\s*[가-힣]{2,4}")


def _load_config_text(path: Path = CONFIG_PATH) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _extract_yaml_list(text: str, key: str) -> List[str]:
    """Extract the simple list shapes used by config/safety-immutable.yaml."""
    inline = re.search(rf"^\s*{re.escape(key)}:\s*\[(.*?)\]\s*$", text, re.MULTILINE)
    if inline:
        return [
            item.strip().strip("\"'")
            for item in inline.group(1).split(",")
            if item.strip()
        ]

    lines = text.splitlines()
    out: List[str] = []
    in_key = False
    key_indent = 0
    for line in lines:
        if not in_key:
            match = re.match(rf"^(\s*){re.escape(key)}:\s*$", line)
            if match:
                in_key = True
                key_indent = len(match.group(1))
            continue
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= key_indent and not line.lstrip().startswith("-"):
            break
        item = re.match(r"^\s*-\s*(.+?)\s*$", line)
        if item:
            out.append(item.group(1).strip().strip("\"'"))
    return out


def _runtime_policy() -> Dict[str, Any]:
    text = _load_config_text()
    deny_write = _extract_yaml_list(text, "deny_write") or list(DEFAULT_DENY_WRITE)
    deny_evolve = _extract_yaml_list(text, "deny") or list(DEFAULT_DENY_EVOLVE)
    immutable_axes = _extract_yaml_list(text, "immutable_axes") or list(IMMUTABLE_AXES)
    return {
        "immutable_axes": immutable_axes,
        "immutable_paths": {"deny_write": deny_write},
        "immutable_evolve_actions": {"deny": deny_evolve},
        "immutable_thresholds": {
            "pass_min": 70,
            "citation_grounding_min": 0.7,
        },
    }


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _contains_any(text: str, needles: Iterable[str]) -> List[str]:
    lower = text.lower()
    return sorted({needle for needle in needles if needle.lower() in lower})


def _expand(path: str) -> Path:
    return Path(os.path.expanduser(path)).resolve(strict=False)


def _inside_or_same(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def validate_config(config: Mapping[str, Any] | None) -> Tuple[bool, List[str]]:
    """Validate immutable safety config at startup.

    Missing or malformed critical keys fail closed because downstream gates
    should not infer a weaker policy.
    """
    errors: List[str] = []
    if not isinstance(config, Mapping):
        return False, ["config must be a mapping"]

    axes = config.get("immutable_axes")
    if not isinstance(axes, Sequence) or isinstance(axes, (str, bytes)):
        errors.append("immutable_axes must be a list")
    else:
        for axis in IMMUTABLE_AXES:
            if axis not in axes:
                errors.append(f"immutable_axes missing {axis}")

    thresholds = config.get("immutable_thresholds")
    if not isinstance(thresholds, Mapping):
        errors.append("immutable_thresholds missing")
    else:
        if thresholds.get("pass_min") != 70:
            errors.append("immutable_thresholds.pass_min must be 70")
        if thresholds.get("citation_grounding_min") != 0.7:
            errors.append("immutable_thresholds.citation_grounding_min must be 0.7")

    paths = config.get("immutable_paths")
    deny_write = paths.get("deny_write") if isinstance(paths, Mapping) else None
    if not isinstance(deny_write, Sequence) or isinstance(deny_write, (str, bytes)) or not deny_write:
        errors.append("immutable_paths.deny_write must be a non-empty list")

    evolve = config.get("immutable_evolve_actions")
    deny = evolve.get("deny") if isinstance(evolve, Mapping) else None
    if not isinstance(deny, Sequence) or isinstance(deny, (str, bytes)):
        errors.append("immutable_evolve_actions.deny must be a list")
    else:
        for action in DEFAULT_DENY_EVOLVE:
            if action not in deny:
                errors.append(f"immutable_evolve_actions.deny missing {action}")

    return not errors, errors


def guard_write(path: str | os.PathLike[str]) -> Tuple[bool, str]:
    """Deny writes to immutable local secret/system paths."""
    target = _expand(str(path))
    for denied in _runtime_policy()["immutable_paths"]["deny_write"]:
        denied_path = _expand(str(denied))
        if _inside_or_same(target, denied_path):
            reason = f"deny_write: {target} is inside {denied_path}"
            audit_log("deny_write", {"path": str(target), "reason": reason})
            return False, reason
    return True, "allowed"


def validate_persona_manifest(manifest: Mapping[str, Any] | None) -> Tuple[bool, List[str]]:
    """Reject persona manifests that encode unsafe intent or identity targeting."""
    if not isinstance(manifest, Mapping):
        return False, ["manifest must be a mapping"]

    errors: List[str] = []
    text = _as_text(manifest)
    dangerous = _contains_any(text, DANGEROUS_VERBS)
    if dangerous:
        errors.append(f"dangerous verbs present: {', '.join(dangerous)}")
    if KOREAN_REAL_NAME_HINT.search(text):
        errors.append("real-name targeting present")

    tuple_fields = ("actor", "action", "target", "tool", "output")
    tuple_values = {field: _as_text(manifest.get(field)).lower() for field in tuple_fields}
    if all(tuple_values.values()):
        if (
            _contains_any(tuple_values["action"], DANGEROUS_VERBS)
            and _contains_any(tuple_values["target"], HIGH_RISK_TARGETS)
            and _contains_any(tuple_values["tool"], HIGH_RISK_TOOLS)
        ):
            errors.append("high-risk actor/action/target/tool/output tuple")

    allowed_tools = manifest.get("allowed_tools", [])
    if isinstance(allowed_tools, Sequence) and not isinstance(allowed_tools, (str, bytes)):
        tool_hits = _contains_any(" ".join(map(str, allowed_tools)), HIGH_RISK_TOOLS)
        intent_hits = _contains_any(_as_text(manifest.get("intent")), DANGEROUS_VERBS)
        if tool_hits and intent_hits:
            errors.append(f"dangerous tools in unsafe intent: {', '.join(tool_hits)}")

    return not errors, errors


def _proposal_actions(proposal: Mapping[str, Any]) -> List[str]:
    actions: List[str] = []
    raw_action = proposal.get("action")
    if raw_action:
        actions.append(str(raw_action))
    for key in ("actions", "changes", "deltas"):
        raw = proposal.get(key)
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            for item in raw:
                if isinstance(item, Mapping):
                    action = item.get("action") or item.get("type")
                    axis = item.get("axis")
                    if action and axis:
                        actions.append(f"{action}:{axis}")
                    elif action:
                        actions.append(str(action))
                else:
                    actions.append(str(item))
    return actions


def validate_evolve_proposal(proposal: Mapping[str, Any] | None) -> Tuple[bool, List[str]]:
    """Reject evolution proposals that touch immutable axes or deny-listed actions."""
    if not isinstance(proposal, Mapping):
        return False, ["proposal must be a mapping"]

    policy = _runtime_policy()
    deny = set(policy["immutable_evolve_actions"]["deny"])
    immutable_axes = set(policy["immutable_axes"])
    errors: List[str] = []

    for action in _proposal_actions(proposal):
        if action in deny:
            errors.append(f"denied evolve action: {action}")
        if ":" in action:
            _, axis = action.split(":", 1)
            if axis in immutable_axes:
                errors.append(f"immutable axis cannot evolve: {axis}")

    for axis in proposal.get("axes", []) if isinstance(proposal.get("axes"), list) else []:
        if axis in immutable_axes:
            errors.append(f"immutable axis cannot evolve: {axis}")

    return not errors, sorted(set(errors))


def validate_evidence_provenance(evidence_list: Iterable[Mapping[str, Any]] | None) -> Tuple[bool, List[str]]:
    """Ensure every quote is contained in its source text/content."""
    if evidence_list is None:
        return False, ["evidence_list missing"]

    errors: List[str] = []
    for idx, evidence in enumerate(evidence_list):
        if not isinstance(evidence, Mapping):
            errors.append(f"evidence[{idx}] must be a mapping")
            continue
        quote = str(evidence.get("quote") or "")
        source_text = str(
            evidence.get("source_text")
            or evidence.get("content")
            or evidence.get("text")
            or ""
        )
        if not quote.strip():
            errors.append(f"evidence[{idx}] quote missing")
        elif not source_text.strip():
            errors.append(f"evidence[{idx}] source_text missing")
        elif quote not in source_text:
            errors.append(f"evidence[{idx}] quote is not contained in source_text")

    return not errors, errors


def redact(text: str) -> str:
    """Redact supported secret and Korean PII patterns from text."""
    out = str(text)
    for label, pattern in SECRET_PATTERNS:
        out = pattern.sub(f"[REDACTED_{label}]", out)
    for label, pattern in PII_PATTERNS:
        out = pattern.sub(f"[REDACTED_{label}]", out)
    return out


def aup_risk(prompt: str, ontology: Mapping[str, Any] | None = None) -> float:
    """Return a bounded 0.0-1.0 risk score for unsafe automation prompts."""
    text = str(prompt or "")
    lower = text.lower()
    score = 0.0

    verb_hits = _contains_any(lower, DANGEROUS_VERBS)
    score += min(0.45, 0.12 * len(verb_hits))

    target_hits = _contains_any(lower, HIGH_RISK_TARGETS)
    if target_hits:
        score += 0.2

    tool_hits = _contains_any(lower, HIGH_RISK_TOOLS)
    if tool_hits:
        score += 0.15

    if KOREAN_REAL_NAME_HINT.search(text):
        score += 0.15

    if ontology:
        ontology_terms = ontology.get("high_risk_terms", [])
        if isinstance(ontology_terms, Sequence) and not isinstance(ontology_terms, (str, bytes)):
            score += min(0.2, 0.05 * len(_contains_any(lower, map(str, ontology_terms))))

    return round(min(1.0, score), 3)


def audit_log(decision: str, context: Mapping[str, Any] | None = None) -> Path:
    """Append a redacted safety audit event and return the log path."""
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "decision": str(decision),
        "context": json.loads(redact(json.dumps(context or {}, ensure_ascii=False, sort_keys=True))),
    }
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        json.dump(event, f, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    return AUDIT_PATH


def critic_addendum_template_hash(template: str) -> str:
    """Helper for regenerating the immutable template hash."""
    return hashlib.sha256(template.encode("utf-8")).hexdigest()
