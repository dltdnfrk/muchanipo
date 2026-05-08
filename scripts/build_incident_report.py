#!/usr/bin/env python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research.incident_report import build_incident_report, load_run_events, write_incident_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Muchanipo incident report from run-scoped stdout JSONL")
    parser.add_argument("artifact", type=Path, help="Path to muchanipo-python-<run>-stdout.jsonl")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Markdown report path (default: .omx/incident-reports/<artifact-stem>.md)",
    )
    args = parser.parse_args()
    report = build_incident_report(load_run_events(args.artifact), artifact_path=args.artifact)
    output = args.output or Path(".omx/incident-reports") / f"{args.artifact.stem}-incident.md"
    written = write_incident_report(report, output)
    print(written)
    print(f"verdict={report['verdict']}")
    print(f"anomalies={len(report['anomalies'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
