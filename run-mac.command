#!/usr/bin/env bash
# Video Download — one double-click launcher for macOS.
#
# Team usage: clone/open the repo, then DOUBLE-CLICK this file in Finder.
#   - First run: creates a local .venv and installs dependencies (needs internet).
#   - Every run after: just launches the app instantly.
#   - First time the app opens, it downloads Chromium (~150 MB, one-time).
#
# If macOS blocks it ("unidentified developer"): right-click → Open → Open once.

set -euo pipefail
cd "$(dirname "$0")"

# Pick a Python that is BOTH >= 3.10 AND has tkinter (the window needs Tk).
# macOS is a minefield: system python3 is often 3.9 (too old), and Homebrew
# python3 usually ships WITHOUT Tk. So we probe candidates and take the first
# that satisfies both. Override with:  PYTHON=/path/to/python ./run-mac.command
_ok_python() {
  command -v "$1" >/dev/null 2>&1 || return 1
  "$1" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)' 2>/dev/null || return 1
  "$1" -c 'import tkinter' 2>/dev/null || return 1
  return 0
}

PY=""
for c in "${PYTHON:-}" python3.13 python3.12 python3.11 python3.10 /usr/local/bin/python3 python3; do
  [ -n "$c" ] || continue
  if _ok_python "$c"; then PY="$c"; break; fi
done

if [ -z "$PY" ]; then
  echo "ERROR: no suitable Python found (need 3.10+ WITH Tk/tkinter)."
  echo "Install the python.org build — it ships Tk:"
  echo "  https://www.python.org/downloads/macos/"
  echo "Then re-run this file."
  read -r -p "Press Enter to close."
  exit 1
fi
echo "Using Python: $("$PY" --version 2>&1) ($PY)"

# Check the actual entry point, not just the .venv dir — a half-finished first
# install (interrupted / no internet) would otherwise be skipped and then crash.
if [ ! -x ".venv/bin/tiktok-music-dl-gui" ]; then
  echo "=== First-time setup (one-time, ~1-2 min) ==="
  echo "[1/3] Creating virtual environment…"
  "$PY" -m venv .venv
  echo "[2/3] Upgrading pip…"
  ./.venv/bin/python -m pip install --upgrade pip >/dev/null
  echo "[3/3] Installing dependencies…"
  ./.venv/bin/python -m pip install -e .
  echo "Setup done."
fi

echo "Launching Video Download…"
exec ./.venv/bin/tiktok-music-dl-gui
