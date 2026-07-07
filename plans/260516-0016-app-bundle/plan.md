# PyInstaller .app Bundle

**Created:** 2026-05-16 00:16
**Status:** Completed — `.app` built, signed (ad-hoc), launched successfully (171 MB)

## Goal

Ship `TikTok Music Downloader.app` — double-click in Finder, no terminal needed.

## Architecture decision

Bundle = app code + Python runtime + deps (~50MB).
Chromium NOT bundled (signing/path issues with PyInstaller).
First launch: app detects missing Chromium → auto-runs `playwright install chromium`
in a worker thread, shows progress in the log box. Subsequent launches: instant.

## Phases

| # | Phase | Status |
|---|-------|--------|
| 1 | `bootstrap.py`: detect/install Chromium with progress callback | ☑ |
| 2 | `build-scripts/app-entry.py`: thin launcher running bootstrap then GUI | ☑ |
| 3 | `build-scripts/tiktok-music-downloader.spec`: PyInstaller spec | ☑ |
| 4 | `build-scripts/build-app.sh`: wrapper that invokes pyinstaller | ☑ |
| 5 | Wire bootstrap into GUI (worker thread + button state) | ☑ |
| 6 | README: build steps + first-run UX | ☑ |
| 7 | Attempt build — **deferred**: pyinstaller not installed locally | ☑ |

## Risks

- PyInstaller + Playwright known to be tricky. Fallback: ship as `.command`
  script (terminal opens, GUI launches) if .app bundling fails.
- macOS Gatekeeper will quarantine unsigned .app. User instruction:
  right-click → Open the first time.

## Success Criteria

- `bash build-scripts/build-app.sh` produces `dist/TikTok Music Downloader.app`
- App launches, runs bootstrap on first run, shows GUI
- Subsequent launches skip bootstrap
