#!/usr/bin/env bash
# Build TikTok Music Downloader.app for macOS.
#
# Prereqs:
#   - Python 3.10+ with Tk (python.org installer or `brew install python-tk@3.12`)
#   - Active venv with deps: `pip install -e . pyinstaller`
#
# Usage:
#   bash build-scripts/build-app.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SPEC_FILE="$PROJECT_ROOT/build-scripts/tiktok-music-downloader.spec"

cd "$PROJECT_ROOT/build-scripts"

if ! command -v pyinstaller >/dev/null 2>&1; then
  echo "ERROR: pyinstaller not on PATH. Run: pip install pyinstaller" >&2
  exit 1
fi

# Fetch the static ffmpeg we bundle for watermarking (gitignored — too big to
# commit). evermeet.cx ships a self-contained macOS build (x86_64; runs via
# Rosetta on Apple Silicon). The spec skips bundling if this file is absent.
FFMPEG_BIN="$PROJECT_ROOT/assets/ffmpeg-static/ffmpeg"
if [[ ! -f "$FFMPEG_BIN" ]]; then
  echo "[0/3] Fetching static ffmpeg for bundling…"
  mkdir -p "$PROJECT_ROOT/assets/ffmpeg-static"
  curl -sL -o /tmp/ffmpeg-static.zip "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip"
  unzip -o -q /tmp/ffmpeg-static.zip -d "$PROJECT_ROOT/assets/ffmpeg-static"
  chmod +x "$FFMPEG_BIN"
  rm -f /tmp/ffmpeg-static.zip
fi

echo "[1/3] Cleaning previous build…"
rm -rf "$PROJECT_ROOT/build" "$PROJECT_ROOT/dist"

echo "[2/3] Running PyInstaller (this can take 2-5 min)…"
pyinstaller "$SPEC_FILE" --noconfirm --distpath "$PROJECT_ROOT/dist" --workpath "$PROJECT_ROOT/build"

APP_PATH="$PROJECT_ROOT/dist/TikTok Music Downloader.app"
if [[ ! -d "$APP_PATH" ]]; then
  echo "ERROR: bundle not produced at: $APP_PATH" >&2
  exit 1
fi

echo "[3/4] Ad-hoc codesign (free, no Apple Developer account)…"
# Sign with the ad-hoc identity '-'. This satisfies macOS Catalina+ that
# requires *some* signature, even an unsigned one, for unsigned binaries to
# launch on the same machine. Does NOT satisfy Gatekeeper on other machines —
# users must still right-click → Open the first time.
codesign --force --deep --sign - "$APP_PATH"

echo "[4/4] Bundle ready: $APP_PATH"
du -sh "$APP_PATH" | awk '{print "  size:", $1}'

cat <<NOTES

Done.

Next steps:
  1. Open Finder, navigate to:  $PROJECT_ROOT/dist/
  2. Drag "TikTok Music Downloader.app" into /Applications (optional).
  3. First launch (on YOUR machine):
     - Right-click the .app → Open → Open. (One-time Gatekeeper bypass.)
     - On first launch the app downloads Chromium (~150 MB, one-time).

Sharing with teammates (free, no Apple Developer ID):
  1. Zip the .app:  cd dist && zip -r tiktok-music-downloader.zip "TikTok Music Downloader.app"
  2. Send the zip.
  3. Teammate unzips, then runs ONCE to strip the macOS "downloaded" quarantine flag:
       xattr -dr com.apple.quarantine "TikTok Music Downloader.app"
     (Otherwise macOS shows "damaged" because the app is unsigned.)
  4. Right-click → Open → Open.
NOTES
