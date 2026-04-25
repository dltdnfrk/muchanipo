#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
python3 src/migrate/v03_to_v04.py "$@"
