#!/usr/bin/env python3
"""Nightly dream-cycle runner: scan vault, dedupe, emit cluster summary.

The runner reuses :class:`src.wiki.dream_cycle.DreamCycle` for the
episode→semantic promotion bookkeeping and adds the I/O layer needed for
unattended (cron) execution:

- recursively scan ``vault/personas/`` and ``vault/insights/`` (configurable)
- normalise records from ``.md`` / ``.txt`` / ``.jsonl`` into episodes
- deduplicate identical observations and cluster by derived key
- write a markdown cluster-summary report (no external LLM calls)

Stdlib-only by design so it can run from a vanilla Python install.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Sequence

from src.wiki.dream_cycle import DreamCycle, Episode

DEFAULT_SCAN_DIRS = ("personas", "insights")
DEFAULT_EXTENSIONS = (".md", ".txt", ".jsonl")
_TEXT_KEYS = ("content", "text", "body", "observation", "summary", "insight")
_KEY_HINTS = ("key", "topic", "cluster", "theme", "persona_id")


@dataclass
class DreamRunReport:
    """Outcome of a single dream-cycle run."""

    scanned_files: int = 0
    accumulated_episodes: int = 0
    clusters: List[str] = field(default_factory=list)
    promoted: List[str] = field(default_factory=list)
    summary_path: Optional[Path] = None
    summary_text: str = ""

    def to_dict(self) -> dict:
        return {
            "scanned_files": self.scanned_files,
            "accumulated_episodes": self.accumulated_episodes,
            "clusters": list(self.clusters),
            "promoted": list(self.promoted),
            "summary_path": str(self.summary_path) if self.summary_path else None,
        }


@dataclass
class DreamRunner:
    """Scan vault directories and emit a cluster-summary report."""

    vault_root: Path
    scan_subdirs: Sequence[str] = DEFAULT_SCAN_DIRS
    extensions: Sequence[str] = DEFAULT_EXTENSIONS
    threshold: int = 3
    output_dir: Optional[Path] = None
    cycle: DreamCycle = field(init=False)

    def __post_init__(self) -> None:
        self.vault_root = Path(self.vault_root)
        if self.output_dir is not None:
            self.output_dir = Path(self.output_dir)
        self.cycle = DreamCycle(threshold=max(1, int(self.threshold)))

    def run(self) -> DreamRunReport:
        report = DreamRunReport()
        for path in self._iter_files():
            report.scanned_files += 1
            for episode in self._read_episodes(path):
                self.cycle.accumulate(episode)
                report.accumulated_episodes += 1

        report.clusters = sorted(
            {ep.key for ep in self.cycle.episodes},
            key=lambda k: (-self.cycle.promotion_candidates().get(k, 0), k),
        )
        report.promoted = sorted(self.cycle.promotion_candidates().keys())
        report.summary_text = self._render_summary(report)
        if self.output_dir is not None:
            report.summary_path = self._write_summary(report.summary_text)
        return report

    def _iter_files(self) -> Iterable[Path]:
        for sub in self.scan_subdirs:
            base = self.vault_root / sub
            if not base.exists():
                continue
            for ext in self.extensions:
                yield from sorted(base.rglob(f"*{ext}"))

    def _read_episodes(self, path: Path) -> Iterable[Episode]:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []

        if path.suffix == ".jsonl":
            return list(self._parse_jsonl(text, path))
        return list(self._parse_freeform(text, path))

    def _parse_jsonl(self, text: str, path: Path) -> Iterable[Episode]:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, Mapping):
                yield from self._episodes_from_mapping(record, path)

    def _parse_freeform(self, text: str, path: Path) -> Iterable[Episode]:
        cleaned = text.strip()
        if not cleaned:
            return
        for chunk in re.split(r"\n\s*\n", cleaned):
            content = chunk.strip()
            if not content:
                continue
            yield Episode(
                key=self._derive_key(content, path),
                content=content,
                source=str(path),
            )

    def _episodes_from_mapping(self, record: Mapping, path: Path) -> Iterable[Episode]:
        content = next(
            (str(record[k]).strip() for k in _TEXT_KEYS if record.get(k)),
            "",
        )
        if not content:
            return
        key = next(
            (str(record[k]).strip() for k in _KEY_HINTS if record.get(k)),
            "",
        ) or self._derive_key(content, path)
        yield Episode(key=key, content=content, source=str(path))

    @staticmethod
    def _derive_key(content: str, path: Path) -> str:
        words = re.findall(r"[A-Za-z0-9가-힣]+", content.lower())
        if words:
            return "-".join(words[:5])
        return path.stem or "untitled"

    def _render_summary(self, report: DreamRunReport) -> str:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        lines = [
            "# Dream Cycle Summary",
            "",
            f"- generated_at: {timestamp}",
            f"- vault_root: {self.vault_root}",
            f"- scanned_files: {report.scanned_files}",
            f"- accumulated_episodes: {report.accumulated_episodes}",
            f"- distinct_clusters: {len(report.clusters)}",
            f"- promotion_threshold: {self.cycle.threshold}",
            f"- promoted_clusters: {len(report.promoted)}",
            "",
            "## Clusters",
        ]
        if not report.clusters:
            lines.append("- (none)")
        else:
            counts = {ep.key: 0 for ep in self.cycle.episodes}
            for ep in self.cycle.episodes:
                counts[ep.key] += 1
            for key in report.clusters:
                marker = " ⭐" if key in set(report.promoted) else ""
                lines.append(f"- `{key}` × {counts.get(key, 0)}{marker}")
        return "\n".join(lines) + "\n"

    def _write_summary(self, text: str) -> Path:
        assert self.output_dir is not None
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = self.output_dir / f"dream-summary-{stamp}.md"
        target.write_text(text, encoding="utf-8")
        return target


def run_dream_cycle(
    vault_root: Path | str,
    *,
    output_dir: Optional[Path | str] = None,
    threshold: int = 3,
    scan_subdirs: Sequence[str] = DEFAULT_SCAN_DIRS,
) -> DreamRunReport:
    """Convenience entrypoint used by ``tools/dream_cycle.sh``."""
    runner = DreamRunner(
        vault_root=Path(vault_root),
        scan_subdirs=tuple(scan_subdirs),
        threshold=threshold,
        output_dir=Path(output_dir) if output_dir else None,
    )
    return runner.run()


def _build_cli() -> "argparse.ArgumentParser":
    import argparse

    parser = argparse.ArgumentParser(
        prog="dream_runner",
        description="Scan vault personas/insights and emit a dream-cycle summary.",
    )
    parser.add_argument("--vault", default="vault", help="Vault root directory (default: vault)")
    parser.add_argument(
        "--output-dir",
        default="logs/dream-cycle",
        help="Where to write the summary markdown (default: logs/dream-cycle)",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=3,
        help="Repetition threshold for promotion (default: 3)",
    )
    parser.add_argument(
        "--scan-subdir",
        action="append",
        dest="scan_subdirs",
        help="Subdirectory under vault to scan (repeatable). Defaults: personas, insights.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Compute summary but skip writing the markdown report.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_cli()
    args = parser.parse_args(argv)
    subdirs = tuple(args.scan_subdirs) if args.scan_subdirs else DEFAULT_SCAN_DIRS
    output_dir = None if args.no_write else args.output_dir
    report = run_dream_cycle(
        args.vault,
        output_dir=output_dir,
        threshold=args.threshold,
        scan_subdirs=subdirs,
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
