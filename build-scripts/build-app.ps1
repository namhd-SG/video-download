# Build "Video Download" for Windows (PowerShell).
# (macOS build lives in build-scripts/build-app.sh — run that on a Mac.)
#
# Prereqs:
#   - Python 3.10+ (python.org installer — ships Tk)
#   - A venv with deps:  py -m venv .venv ; .\.venv\Scripts\Activate.ps1
#                        pip install -e . pyinstaller
#   - (Optional) ffmpeg.exe for the watermark feature. Either put a static
#     build at assets\ffmpeg-static\ffmpeg.exe (it gets bundled), or have
#     ffmpeg on PATH at runtime. Without it, downloads still work — only the
#     watermark step is skipped.
#
# Usage (from the project root):
#   powershell -ExecutionPolicy Bypass -File build-scripts\build-app.ps1

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
$SpecFile    = Join-Path $ProjectRoot "build-scripts\tiktok-music-downloader.spec"

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
  Write-Error "pyinstaller not on PATH. Run: pip install pyinstaller"
  exit 1
}

$FfmpegBin = Join-Path $ProjectRoot "assets\ffmpeg-static\ffmpeg.exe"
if (-not (Test-Path $FfmpegBin)) {
  Write-Host "[!] assets\ffmpeg-static\ffmpeg.exe not found — building WITHOUT a bundled ffmpeg."
  Write-Host "    Watermarking will need ffmpeg on PATH at runtime. Downloads work regardless."
  Write-Host "    To bundle it: download a static ffmpeg.exe (gyan.dev or BtbN) into that folder."
}

Write-Host "[1/3] Cleaning previous build..."
Remove-Item -Recurse -Force (Join-Path $ProjectRoot "build") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $ProjectRoot "dist")  -ErrorAction SilentlyContinue

Write-Host "[2/3] Running PyInstaller (this can take 2-5 min)..."
# Run from build-scripts/ so the spec's app-entry.py and pathex=../src resolve
# (mirrors build-app.sh). Output paths below are absolute, so they're unaffected.
Push-Location (Join-Path $ProjectRoot "build-scripts")
try {
  pyinstaller $SpecFile --noconfirm `
    --distpath (Join-Path $ProjectRoot "dist") `
    --workpath (Join-Path $ProjectRoot "build")
} finally {
  Pop-Location
}

$ExePath = Join-Path $ProjectRoot "dist\video-download\video-download.exe"
if (-not (Test-Path $ExePath)) {
  Write-Error "build failed: exe not produced at $ExePath"
  exit 1
}

Write-Host "[3/3] Build ready: $ExePath"

Write-Host ""
Write-Host "Done."
Write-Host "Next steps:"
Write-Host "  1. The whole app is the folder:  dist\video-download\"
Write-Host "  2. Run it by double-clicking:     dist\video-download\video-download.exe"
Write-Host "  3. First launch downloads Chromium (~150 MB, one-time)."
Write-Host ""
Write-Host "Sharing with teammates:"
Write-Host "  - Zip the ENTIRE dist\video-download\ folder (not just the .exe) and send it."
Write-Host "  - Windows SmartScreen may warn on an unsigned app: More info -> Run anyway."
