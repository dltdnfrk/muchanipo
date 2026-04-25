#!/usr/bin/env python3
"""Capture a lightweight token baseline stub for v0.3 comparison."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Record a token baseline stub")
    parser.add_argument("--output", default=".omc/autoresearch/token-baseline-v03.json")
    parser.add_argument("--label", default="v0.3-1day")
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "label": args.label,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "status": "stub",
        "note": "Replace with provider usage export when available.",
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote token baseline stub to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
