#!/usr/bin/env python3
"""Build a compact replay JSONL from recent MuchaNipo autoresearch outputs."""

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _tail_rows(results_path: Path, limit: int) -> List[Dict[str, str]]:
    if not results_path.exists():
        return []
    with open(results_path, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return rows[-limit:]


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _candidate_keys(row: Dict[str, str]) -> Iterable[str]:
    for key in ("council_id", "id", "experiment_id", "report_id"):
        value = row.get(key)
        if value:
            yield value


def _match_report(row: Dict[str, str], reports: List[Path]) -> Optional[Path]:
    keys = list(_candidate_keys(row))
    for key in keys:
        for path in reports:
            if key in path.stem:
                return path

    topic = (row.get("topic") or "").strip().lower()
    if topic:
        for path in reports:
            try:
                data = _load_json(path)
            except (json.JSONDecodeError, OSError):
                continue
            if str(data.get("topic", "")).strip().lower() == topic:
                return path
    return None


def build_replay_set(results_path: Path, logs_dir: Path, output_path: Path, limit: int) -> int:
    rows = _tail_rows(results_path, limit)
    reports = sorted(logs_dir.glob("council-report-*.json"))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(output_path, "w", encoding="utf-8") as out:
        for row in rows:
            report_path = _match_report(row, reports)
            if report_path is None:
                continue
            try:
                report = _load_json(report_path)
            except (json.JSONDecodeError, OSError):
                continue
            out.write(json.dumps({
                "source_result": row,
                "report_path": str(report_path),
                "council_report": report,
            }, ensure_ascii=False) + "\n")
            written += 1
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build recent-N replay JSONL")
    parser.add_argument("--results", default=".omc/autoresearch/results.tsv")
    parser.add_argument("--logs-dir", default=".omc/autoresearch/logs")
    parser.add_argument("--output", default=".omc/autoresearch/replay/recent-N.jsonl")
    parser.add_argument("-n", "--limit", type=int, default=20)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    written = build_replay_set(
        Path(args.results),
        Path(args.logs_dir),
        Path(args.output),
        args.limit,
    )
    print(f"wrote {written} replay item(s) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
