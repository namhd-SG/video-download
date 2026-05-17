#!/usr/bin/env bash
# Generate assets/icon.icns from assets/icon.svg using ImageMagick + iconutil.
#
# Requires: magick (ImageMagick), iconutil (macOS built-in).

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SVG="$PROJECT_ROOT/assets/icon.svg"
ICONSET="$PROJECT_ROOT/assets/icon.iconset"
ICNS="$PROJECT_ROOT/assets/icon.icns"

if [[ ! -f "$SVG" ]]; then
  echo "ERROR: $SVG not found" >&2
  exit 1
fi

if ! command -v magick >/dev/null 2>&1; then
  echo "ERROR: ImageMagick (magick) not on PATH. brew install imagemagick" >&2
  exit 1
fi

rm -rf "$ICONSET"
mkdir -p "$ICONSET"

echo "[1/2] Rendering PNG sizes from SVG…"
# Apple iconset spec: 10 png variants
declare -a SIZES=(
  "16    icon_16x16.png"
  "32    icon_16x16@2x.png"
  "32    icon_32x32.png"
  "64    icon_32x32@2x.png"
  "128   icon_128x128.png"
  "256   icon_128x128@2x.png"
  "256   icon_256x256.png"
  "512   icon_256x256@2x.png"
  "512   icon_512x512.png"
  "1024  icon_512x512@2x.png"
)
for entry in "${SIZES[@]}"; do
  read -r px name <<<"$entry"
  magick -background none -density 600 "$SVG" -resize "${px}x${px}" "$ICONSET/$name"
done

echo "[2/2] Packing into .icns…"
iconutil -c icns "$ICONSET" -o "$ICNS"

echo "Done: $ICNS"
du -h "$ICNS" | awk '{print "  size:", $1}'
