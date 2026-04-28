#!/usr/bin/env python3
"""Migrate a MuchaNipo v1 vault to the v2 vault shape.

The migration is stdlib-only and conservative:
- dry-run reports planned file updates without writing or backing up
- normal mode creates one full vault backup before writing any changes
- repeated runs are idempotent and do not create backups when nothing changes
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_VALUE_AXES = {
    "time_horizon": "mid",
    "risk_tolerance": 0.5,
    "stakeholder_priority": ["primary", "secondary", "tertiary"],
    "innovation_orientation": 0.5,
}
MEASUREMENT_AXES = ("citation_fidelity", "density", "coverage_breadth")
BASE_RUBRIC_MAX = 130


class MigrationResult:
    def __init__(
        self,
        changed_files: list[Path] | None = None,
        warnings: list[str] | None = None,
        backup_dir: Path | None = None,
    ) -> None:
        self.changed_files = changed_files or []
        self.warnings = warnings or []
        self.backup_dir = backup_dir

    @property
    def changed_count(self) -> int:
        return len(self.changed_files)


class PlannedWrite:
    def __init__(self, path: Path, content: str) -> None:
        self.path = path
        self.content = content


class UnsupportedFrontmatter(ValueError):
    pass


def migrate_vault(vault_dir: Path, dry_run: bool = False) -> MigrationResult:
    vault_dir = Path(vault_dir)
    warnings: list[str] = []
    if not vault_dir.exists():
        raise FileNotFoundError(f"vault dir not found: {vault_dir}")
    if not vault_dir.is_dir():
        raise NotADirectoryError(f"vault path is not a directory: {vault_dir}")

    planned: dict[Path, str] = {}
    for write in _plan_persona_writes(vault_dir, warnings):
        planned[write.path] = write.content
    for write in _plan_insight_writes(vault_dir, warnings):
        planned[write.path] = write.content
    for write in _plan_wiki_index(vault_dir):
        planned[write.path] = write.content

    warnings.extend(_check_cost_log(vault_dir / "cost-log.jsonl"))

    changed_paths = sorted(planned)
    if dry_run or not changed_paths:
        return MigrationResult(changed_files=changed_paths, warnings=warnings)

    backup_dir = _backup_vault(vault_dir)
    for path in changed_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(planned[path], encoding="utf-8")

    return MigrationResult(
        changed_files=changed_paths,
        warnings=warnings,
        backup_dir=backup_dir,
    )


def _plan_persona_writes(vault_dir: Path, warnings: list[str]) -> Iterable[PlannedWrite]:
    personas_dir = vault_dir / "personas"
    if not personas_dir.exists():
        warnings.append(f"missing personas dir: {personas_dir}")
        return []

    writes: list[PlannedWrite] = []
    for path in sorted(personas_dir.glob("*.md")):
        parsed = _parse_frontmatter_file(path, warnings)
        if parsed is None:
            continue
        frontmatter, body = parsed
        value_axes = frontmatter.get("value_axes")
        if not isinstance(value_axes, dict):
            value_axes = {}

        merged = dict(value_axes)
        changed = frontmatter.get("value_axes") != merged
        for key, value in DEFAULT_VALUE_AXES.items():
            if key not in merged:
                merged[key] = list(value) if isinstance(value, list) else value
                changed = True

        frontmatter["value_axes"] = merged
        warnings.extend(_validate_value_axes(path, merged))
        if changed:
            writes.append(PlannedWrite(path, _render_frontmatter_file(frontmatter, body)))
    return writes


def _plan_insight_writes(vault_dir: Path, warnings: list[str]) -> Iterable[PlannedWrite]:
    insights_dir = vault_dir / "insights"
    if not insights_dir.exists():
        warnings.append(f"missing insights dir: {insights_dir}")
        return []

    writes: list[PlannedWrite] = []
    for path in sorted(insights_dir.glob("*.md")):
        parsed = _parse_frontmatter_file(path, warnings)
        if parsed is None:
            continue
        frontmatter, body = parsed
        scores = _find_scores_mapping(frontmatter)
        if scores is None:
            warnings.append(f"missing scores mapping: {path}")
            continue

        changed = False
        for axis in MEASUREMENT_AXES:
            if axis not in scores:
                scores[axis] = 0
                changed = True
        if "rubric_max" in frontmatter and frontmatter.get("rubric_max") != BASE_RUBRIC_MAX:
            frontmatter["rubric_max"] = BASE_RUBRIC_MAX
            changed = True
        if changed:
            writes.append(PlannedWrite(path, _render_frontmatter_file(frontmatter, body)))
    return writes


def _plan_wiki_index(vault_dir: Path) -> Iterable[PlannedWrite]:
    wiki_dir = vault_dir / "wiki"
    index_path = wiki_dir / "index.md"
    pages = [
        path
        for path in sorted(vault_dir.rglob("*.md"))
        if path != index_path and ".bak." not in path.name
    ]
    if not pages and not index_path.exists():
        return []

    lines = [
        "# MuchaNipo Vault Index",
        "<!-- Generated by scripts/migrate_v1_to_v2.py. -->",
        "",
        "| Page | Type | Title |",
        "|------|------|-------|",
    ]
    for path in pages:
        rel = path.relative_to(vault_dir).as_posix()
        page_type = path.parent.name if path.parent != vault_dir else "root"
        title = _frontmatter_title(path) or path.stem
        lines.append(f"| [{rel}](../{rel}) | {page_type} | {title} |")
    content = "\n".join(lines) + "\n"
    if index_path.exists() and index_path.read_text(encoding="utf-8") == content:
        return []
    return [PlannedWrite(index_path, content)]


def _check_cost_log(path: Path) -> list[str]:
    if not path.exists():
        return [f"missing cost log: {path}"]

    warnings: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            warnings.append(f"invalid cost-log json at {path}:{line_number}: {exc}")
            continue
        if not isinstance(entry, dict):
            warnings.append(f"cost-log entry is not an object at {path}:{line_number}")
            continue
        for key in ("event", "status"):
            if key not in entry:
                warnings.append(f"cost-log entry missing {key} at {path}:{line_number}")
    return warnings


def _backup_vault(vault_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    backup_dir = vault_dir.with_name(f"{vault_dir.name}.bak.{stamp}")
    suffix = 0
    while backup_dir.exists():
        suffix += 1
        backup_dir = vault_dir.with_name(f"{vault_dir.name}.bak.{stamp}-{suffix}")
    shutil.copytree(vault_dir, backup_dir)
    return backup_dir


def _parse_frontmatter_file(path: Path, warnings: list[str]) -> tuple[dict[str, Any], str] | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        warnings.append(f"missing frontmatter: {path}")
        return None
    end = text.find("\n---", 4)
    if end == -1:
        warnings.append(f"unterminated frontmatter: {path}")
        return None
    raw = text[4:end]
    body = text[end + len("\n---") :]
    if body.startswith("\n"):
        body = body[1:]
    try:
        return _parse_mapping(raw.splitlines()), body
    except UnsupportedFrontmatter as exc:
        warnings.append(f"unsupported frontmatter skipped: {path}: {exc}")
        return None


def _parse_mapping(lines: list[str]) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.lstrip().startswith("- "):
            raise UnsupportedFrontmatter("block lists are not supported")
        if ":" not in raw_line:
            raise UnsupportedFrontmatter("multiline scalar continuation is not supported")
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        key, raw_value = raw_line.strip().split(":", 1)
        if raw_value.strip() in {"|", ">"}:
            raise UnsupportedFrontmatter("block scalars are not supported")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]
        value = raw_value.strip()
        if value == "":
            child: dict[str, Any] = {}
            current[key] = child
            stack.append((indent, child))
        else:
            current[key] = _parse_scalar(value)
    return root


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"[]", "{}"}:
        return [] if value == "[]" else {}
    if value.startswith("[") and value.endswith("]"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return [item.strip().strip("\"'") for item in value[1:-1].split(",") if item.strip()]
    if value.startswith("{") and value.endswith("}"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value.strip("\"'")


def _render_frontmatter_file(frontmatter: dict[str, Any], body: str) -> str:
    return "---\n" + _render_mapping(frontmatter) + "---\n" + body


def _render_mapping(mapping: dict[str, Any], indent: int = 0) -> str:
    lines: list[str] = []
    pad = " " * indent
    for key, value in mapping.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.append(_render_mapping(value, indent + 2).rstrip("\n"))
        else:
            lines.append(f"{pad}{key}: {_render_scalar(value)}")
    return "\n".join(lines) + "\n"


def _render_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(str(value), ensure_ascii=False)


def _find_scores_mapping(frontmatter: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("scores", "rubric_scores", "axes"):
        value = frontmatter.get(key)
        if isinstance(value, dict):
            return value
    final = frontmatter.get("final")
    if isinstance(final, dict):
        scores = final.get("scores")
        if isinstance(scores, dict):
            axes = scores.get("axes")
            if isinstance(axes, dict):
                return axes
    return None


def _frontmatter_title(path: Path) -> str | None:
    parsed = _parse_frontmatter_file(path, [])
    if parsed is None:
        return None
    frontmatter, _body = parsed
    title = frontmatter.get("title") or frontmatter.get("name")
    return str(title) if title else None


def _validate_value_axes(path: Path, axes: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if axes.get("time_horizon") not in {"short", "mid", "long"}:
        warnings.append(f"invalid value_axes.time_horizon in {path}")
    for key in ("risk_tolerance", "innovation_orientation"):
        value = axes.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
            warnings.append(f"invalid value_axes.{key} in {path}")
    priority = axes.get("stakeholder_priority")
    if not isinstance(priority, list) or not priority:
        warnings.append(f"invalid value_axes.stakeholder_priority in {path}")
    return warnings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate MuchaNipo v1 vault data to v2.")
    parser.add_argument("--vault-dir", default="vault", help="vault directory to migrate")
    parser.add_argument("--dry-run", action="store_true", help="report planned changes without writing")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = migrate_vault(Path(args.vault_dir), dry_run=args.dry_run)
    mode = "dry-run" if args.dry_run else "migrated"
    print(f"{mode}: {result.changed_count} file(s)")
    if result.backup_dir:
        print(f"backup: {result.backup_dir}")
    if result.changed_files:
        print("changed:")
        for path in result.changed_files:
            print(f"  - {path}")
    if result.warnings:
        print("warnings:")
        for warning in result.warnings:
            print(f"  - {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
