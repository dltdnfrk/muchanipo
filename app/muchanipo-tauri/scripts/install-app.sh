#!/usr/bin/env bash
# Install the freshly-built Muchanipo.app into /Applications atomically.
#
# Run after `npm run tauri build`. Wired up via the `tauri:install` npm
# script so a single `npm run tauri:install` builds + installs in one go.
#
# Strategy:
#   1. Resolve the freshly built bundle in target/release/bundle/macos.
#   2. If /Applications/Muchanipo.app exists, kill any running instance and
#      remove the old copy so we never end up with multiple .app bundles
#      drifting on disk (the ChatGPT install model — single canonical
#      location, in-place replacement).
#   3. `ditto` the new bundle into place (preserves macOS metadata + symlinks
#      better than cp -R).
#   4. Touch the bundle so LaunchServices re-registers it.
set -euo pipefail

cd "$(dirname "$0")/.."
BUNDLE_DIR="$(pwd)/target/release/bundle/macos"
SOURCE_APP="$BUNDLE_DIR/Muchanipo.app"
TARGET_APP="/Applications/Muchanipo.app"

if [[ ! -d "$SOURCE_APP" ]]; then
  echo "[install-app] no built bundle at $SOURCE_APP — run 'npm run tauri build' first" >&2
  exit 1
fi

echo "[install-app] stopping any running Muchanipo instances"
# AppleScript quit asks the app to exit cleanly first (releases file handles
# that block rm -rf). Fall through to pkill if the app isn't responding.
osascript -e 'tell application "Muchanipo" to quit' 2>/dev/null || true
pkill -x muchanipo-tauri 2>/dev/null || true
pkill -f "Muchanipo.app/Contents/MacOS/" 2>/dev/null || true
# Wait for the process to actually exit so rm -rf doesn't race against open
# file handles. Up to 5 seconds, polling every 200ms.
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25; do
  if ! pgrep -x muchanipo-tauri >/dev/null 2>&1 && \
     ! pgrep -f "Muchanipo.app/Contents/MacOS/" >/dev/null 2>&1; then
    break
  fi
  sleep 0.2
done

if [[ -d "$TARGET_APP" ]]; then
  echo "[install-app] removing previous install at $TARGET_APP"
  rm -rf "$TARGET_APP" || {
    echo "[install-app] rm failed — likely a stuck process; killing forcefully"
    pkill -9 -f "Muchanipo.app/Contents/MacOS/" 2>/dev/null || true
    sleep 1
    rm -rf "$TARGET_APP"
  }
fi

echo "[install-app] copying $SOURCE_APP -> $TARGET_APP"
/usr/bin/ditto "$SOURCE_APP" "$TARGET_APP"
touch "$TARGET_APP"

echo "[install-app] done — launch via:  open -n /Applications/Muchanipo.app"
