#!/usr/bin/env bash
# Remove every Muchanipo.app on disk EXCEPT the canonical install at
# /Applications/Muchanipo.app. Each old worktree's
# `target/release/bundle/macos/Muchanipo.app` accumulates over time and
# confuses LaunchServices; this is the ChatGPT model — only one app on disk.
#
# Safe to run repeatedly. Lists what it touches before deleting.
set -euo pipefail

CANON="/Applications/Muchanipo.app"

echo "[cleanup] scanning for Muchanipo.app under \$HOME …"
removed=0
total=0
while IFS= read -r p; do
  total=$((total + 1))
  if [[ "$p" == "$CANON" ]]; then
    echo "[cleanup] keeping canonical $p"
    continue
  fi
  echo "[cleanup] removing $p"
  rm -rf "$p"
  removed=$((removed + 1))
done < <(find "$HOME" -name "Muchanipo.app" -type d 2>/dev/null)

if [[ $total -eq 0 ]]; then
  echo "[cleanup] no stray bundles found under \$HOME"
fi
echo "[cleanup] removed $removed stale bundle(s); canonical install at $CANON preserved"
