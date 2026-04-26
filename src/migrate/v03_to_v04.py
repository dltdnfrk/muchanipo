#!/usr/bin/env python3
"""Migrate MuchaNipo v0.3 data files to v0.4 metadata.

The migration is intentionally stdlib-only and conservative:
- dry-run prints planned changes without writing files
- normal mode writes per-file backups before changing anything
- rollback restores those backups and removes the backup files
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_TSV = REPO_ROOT / ".omc" / "autoresearch" / "results.tsv"
DEFAULT_SIGNOFF_QUEUE = REPO_ROOT / "src" / "hitl" / "signoff-queue"


def _load_runtime_paths():
    spec = importlib.util.spec_from_file_location(
        "muchanipo_runtime_paths",
        REPO_ROOT / "src" / "runtime" / "paths.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_runtime_paths = _load_runtime_paths()
DEFAULT_VAULT_PATH = _runtime_paths.get_vault_path()
BACKUP_SUFFIX = ".v03-to-v04.bak"
MIGRATED_RUBRIC_VERSION = "2.0.0"


@dataclass
class MigrationResult:
    changed: List[str]
    skipped: List[str]


def _backup_path(path: Path) -> Path:
    return Path(str(path) + BACKUP_SUFFIX)


def _write_with_backup(path: Path, content: str, dry_run: bool, changed: List[str]) -> None:
    if dry_run:
        changed.append(f"would update {path}")
        return

    backup = _backup_path(path)
    if not backup.exists():
        backup.write_bytes(path.read_bytes())
    path.write_text(content, encoding="utf-8")
    changed.append(f"updated {path}")


def _read_tsv(path: Path) -> Tuple[List[str], List[dict]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def _serialize_tsv(fieldnames: Sequence[str], rows: Sequence[dict]) -> str:
    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def migrate_results_tsv(path: Path, dry_run: bool = False) -> MigrationResult:
    changed: List[str] = []
    skipped: List[str] = []
    if not path.exists():
        skipped.append(f"missing results.tsv: {path}")
        return MigrationResult(changed, skipped)

    fieldnames, rows = _read_tsv(path)
    if "rubric_version" in fieldnames:
        skipped.append(f"rubric_version already present: {path}")
        return MigrationResult(changed, skipped)

    new_fields = list(fieldnames) + ["rubric_version"]
    for row in rows:
        row["rubric_version"] = MIGRATED_RUBRIC_VERSION
    _write_with_backup(path, _serialize_tsv(new_fields, rows), dry_run, changed)
    return MigrationResult(changed, skipped)


def _find_frontmatter_end(lines: Sequence[str]) -> Optional[int]:
    if not lines or lines[0].strip() != "---":
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return index
    return None


def _upsert_frontmatter_line(lines: List[str], key: str, value: str) -> bool:
    desired = f"{key}: {value}\n"
    for index, line in enumerate(lines):
        if line.startswith(f"{key}:"):
            if line == desired:
                return False
            lines[index] = desired
            return True
    lines.append(desired)
    return True


def migrate_vault_page(path: Path, dry_run: bool = False) -> MigrationResult:
    changed: List[str] = []
    skipped: List[str] = []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    end = _find_frontmatter_end(lines)
    if end is None:
        skipped.append(f"no frontmatter: {path}")
        return MigrationResult(changed, skipped)

    frontmatter = lines[1:end]
    did_change = False
    did_change |= _upsert_frontmatter_line(frontmatter, "schema_version", "v04")
    did_change |= _upsert_frontmatter_line(frontmatter, "citation_grounding_unknown", "true")
    if not did_change:
        skipped.append(f"frontmatter already migrated: {path}")
        return MigrationResult(changed, skipped)

    new_text = "".join([lines[0], *frontmatter, *lines[end:]])
    _write_with_backup(path, new_text, dry_run, changed)
    return MigrationResult(changed, skipped)


def migrate_vault(vault_path: Path, dry_run: bool = False) -> MigrationResult:
    changed: List[str] = []
    skipped: List[str] = []
    if not vault_path.exists():
        skipped.append(f"missing vault path: {vault_path}")
        return MigrationResult(changed, skipped)

    pages = sorted(vault_path.rglob("*.md"))
    if not pages:
        skipped.append(f"no markdown pages under: {vault_path}")
        return MigrationResult(changed, skipped)

    for page in pages:
        result = migrate_vault_page(page, dry_run)
        changed.extend(result.changed)
        skipped.extend(result.skipped)
    return MigrationResult(changed, skipped)


def migrate_signoff_entry(path: Path, dry_run: bool = False) -> MigrationResult:
    changed: List[str] = []
    skipped: List[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        skipped.append(f"invalid json {path}: {exc}")
        return MigrationResult(changed, skipped)

    if data.get("schema_version") == "v04":
        skipped.append(f"signoff already migrated: {path}")
        return MigrationResult(changed, skipped)

    data["schema_version"] = "v04"
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    _write_with_backup(path, content, dry_run, changed)
    return MigrationResult(changed, skipped)


def migrate_signoff_queue(queue_path: Path, dry_run: bool = False) -> MigrationResult:
    changed: List[str] = []
    skipped: List[str] = []
    if not queue_path.exists():
        skipped.append(f"missing signoff queue: {queue_path}")
        return MigrationResult(changed, skipped)

    entries = sorted(queue_path.glob("*.json"))
    if not entries:
        skipped.append(f"no signoff json files under: {queue_path}")
        return MigrationResult(changed, skipped)

    for entry in entries:
        result = migrate_signoff_entry(entry, dry_run)
        changed.extend(result.changed)
        skipped.extend(result.skipped)
    return MigrationResult(changed, skipped)


def _candidate_backup_roots(paths: Iterable[Path]) -> List[Path]:
    roots = []
    for path in paths:
        if path.is_file():
            roots.append(path.parent)
        else:
            roots.append(path)
    return roots


def rollback(paths: Sequence[Path], dry_run: bool = False) -> MigrationResult:
    changed: List[str] = []
    skipped: List[str] = []
    backups = []
    for root in _candidate_backup_roots(paths):
        if root.exists():
            backups.extend(root.rglob(f"*{BACKUP_SUFFIX}"))

    if not backups:
        skipped.append("no migration backups found")
        return MigrationResult(changed, skipped)

    for backup in sorted(set(backups)):
        original = Path(str(backup)[: -len(BACKUP_SUFFIX)])
        if dry_run:
            changed.append(f"would restore {original}")
            continue
        original.write_bytes(backup.read_bytes())
        backup.unlink()
        changed.append(f"restored {original}")
    return MigrationResult(changed, skipped)


def run_migration(
    results_path: Path,
    vault_path: Path,
    signoff_queue: Path,
    dry_run: bool = False,
    rollback_mode: bool = False,
) -> MigrationResult:
    if rollback_mode:
        return rollback([results_path, vault_path, signoff_queue], dry_run=dry_run)

    changed: List[str] = []
    skipped: List[str] = []
    for result in (
        migrate_results_tsv(results_path, dry_run),
        migrate_vault(vault_path, dry_run),
        migrate_signoff_queue(signoff_queue, dry_run),
    ):
        changed.extend(result.changed)
        skipped.extend(result.skipped)
    return MigrationResult(changed, skipped)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate MuchaNipo v0.3 data to v0.4 metadata.")
    parser.add_argument("--dry-run", action="store_true", help="print planned changes without writing files")
    parser.add_argument("--rollback", action="store_true", help="restore files from migration backups")
    parser.add_argument("--results-path", type=Path, default=DEFAULT_RESULTS_TSV)
    parser.add_argument("--vault-path", type=Path, default=DEFAULT_VAULT_PATH)
    parser.add_argument("--signoff-queue", type=Path, default=DEFAULT_SIGNOFF_QUEUE)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_migration(
        results_path=args.results_path.expanduser(),
        vault_path=args.vault_path.expanduser(),
        signoff_queue=args.signoff_queue.expanduser(),
        dry_run=args.dry_run,
        rollback_mode=args.rollback,
    )

    action = "ROLLBACK" if args.rollback else "MIGRATE"
    mode = "DRY-RUN" if args.dry_run else "WRITE"
    print(f"{action} {mode}")
    for item in result.changed:
        print(f"CHANGE: {item}")
    for item in result.skipped:
        print(f"SKIP: {item}")
    print(f"SUMMARY: {len(result.changed)} change(s), {len(result.skipped)} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
