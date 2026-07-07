# Video Download

Bulk-download MP4 videos into a folder — runs on **Windows and macOS**.

> **Text-only build:** the watermark feature here has a single overlay —
> **animated text**. The static corner logo and animated image/icon overlays
> have been removed.

## Supported sources (what you can paste as the URL)

| Source | URL shape | Notes |
|--------|-----------|-------|
| **TikTok — music page** | `https://www.tiktok.com/music/...-<id>` | all videos using that sound |
| **TikTok — search page** | `https://www.tiktok.com/search?q=...` | usually needs a Cookies file (logged-in session) |
| **Facebook Ads Library** | `https://www.facebook.com/ads/library/?...` | downloads each ad's MP4 |
| **Google Drive** | a shared **folder** link | downloads every MP4 in the folder |

Anything else is rejected up front. Everything downloads to plain `.mp4`.

### Cookies — TikTok only

The **Cookies** field is only for TikTok: the search page (`/search`) needs it,
and a logged-in session lets you download **more than ~28 videos** (the guest
limit). **Facebook and Google Drive don't need cookies** — leave it empty.

How to export a TikTok cookies file (the GUI also has a **"Cách lấy cookie"** button):
1. Install the **Cookie-Editor** browser extension (Chrome / Edge / Firefox).
2. Open `tiktok.com` and **log in**.
3. Click Cookie-Editor → **Export** → choose **JSON** (not "Header String").
4. Save it as e.g. `tiktok-cookies.json`.
5. In the app, click **Browse…** next to Cookies and pick that file.

A Playwright `storage_state` file (`{"cookies": [...]}`) also works. Cookies
expire over time — if you start getting blocked, export a fresh file.

## 🚀 Quick start (for the team — no build needed)

Everything is bundled in this repo (including ffmpeg). Just:

1. **Install Python 3.10+** once — [macOS](https://www.python.org/downloads/macos/) · [Windows](https://www.python.org/downloads/windows/) (on Windows tick *"Add python.exe to PATH"*).
2. Get the repo folder (clone or download-zip → unzip).
3. **Double-click the launcher:**
   - **macOS** → `run-mac.command`  *(first time: right-click → Open → Open)*
   - **Windows** → `run-windows.bat`

That's it. The launcher auto-creates a local environment and installs
dependencies on the **first run** (needs internet, ~1-2 min). The app then opens
a window — paste a URL, pick a folder, click **START**. The very first launch
also downloads Chromium (~150 MB, one-time). ffmpeg for the watermark is already
in the repo, so nothing else to install.

> Later runs are instant — the launcher skips setup once the environment exists.

**Good to know**
- **First run often fails a few videos** (TikTok cold-start). This is normal —
  just press **START again**: the app skips already-downloaded files and picks
  up the rest. Running 1–2 times usually gets you the full set.
- **Downloading never needs ffmpeg** — it's only used for the optional watermark.
  If ffmpeg is somehow unavailable, downloads still succeed; the watermark step
  is skipped with a log warning.
- **macOS:** the bundled mac ffmpeg is a **universal binary** (arm64 + x86_64),
  so it runs natively on both Apple Silicon and Intel — no Rosetta needed.
- The launcher picks a Python that is **3.10+ AND has Tk** — if it can't find
  one it tells you to install the python.org build.

---

Two entry points (for developers):
- **CLI** — `tiktok-music-dl` (for power users)
- **GUI** — `tiktok-music-dl-gui` (Tkinter window for non-technical users)

## How it works

1. **Scrape** — Playwright opens the music page in stealth Chromium, rotates UA,
   auto-scrolls, collects unique video URLs.
2. **Download** — yt-dlp downloads each video as watermark-free MP4 with
   jittered delay, adaptive backoff on rate-limit, batch rest every 50 videos,
   and resume (skips files already on disk).

## Install

### Python with Tkinter (GUI requirement)

Homebrew Python 3.13/3.14 **does not ship Tk**. Pick one:

| Choice | Install | Notes |
|--------|---------|-------|
| python.org installer | https://www.python.org/downloads/macos/ | Ships Tk 9.x. **Recommended.** |
| Homebrew + Tk bottle | `brew install python-tk@3.12` | Works with `python3.12` |
| System Python | already there at `/usr/bin/python3` | Old Tk 8.5, but works for GUI |

CLI only (no GUI)? Any Python ≥3.10 works — skip the Tk step.

### Install the package

```bash
cd Projects/tiktok-music-downloader
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

## Usage

### GUI (recommended for creators)

```bash
tiktok-music-dl-gui
```

A window opens. Paste the music URL, pick output folder, click **Start**.
Logs stream live in the bottom pane; progress bar tracks downloads.

### CLI

```bash
tiktok-music-dl "https://www.tiktok.com/music/original-sound-7374515087526136619" \
  --output ./downloads \
  --max 200 \
  --delay 2.0
```

#### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--output, -o` | `./downloads` | Output directory |
| `--max, -n` | `200` | Max videos (1–2000) |
| `--delay, -d` | `2.0` | **Base** seconds between downloads (actual: jittered ×0.75–2.0) |
| `--proxy` | none | HTTP proxy `http://user:pass@host:port` |
| `--profile-dir` | none | Persistent Playwright user-data dir (cookies survive runs) |
| `--cookies` | none | Path to Playwright cookies JSON |
| `--headful` | off | Show browser window (solve captcha manually) |
| `--scroll-pause` | `1.5` | Seconds between scroll steps |
| `--idle-rounds` | `4` | Stop scroll after N idle rounds |
| `--verbose, -v` | off | Debug logging |

## Anti-block features

Designed for ~50-500 video runs without getting blocked:

- **Jittered delay** — actual wait randomized in `[base*0.75, base*2.0]`
- **UA rotation** — random Chrome UA per scrape session
- **Stealth init** — hides `navigator.webdriver` + plugin fingerprints
- **Persistent profile** — `--profile-dir` keeps cookies → fewer captchas
- **Proxy** — single proxy via `--proxy`
- **Adaptive backoff** — on 429/blocked: sleep 30s → 60s → 120s → ... → cap 300s
- **Batch rest** — auto-pause 60s after every 50 successful downloads

If still blocked: open `--headful`, solve captcha by hand, the cookie stays.

## Resumable

Files saved as `<video_id>.mp4`. Re-running the same command skips any
video already on disk → safe to interrupt + resume.

## Tests

```bash
pip install pytest
pytest tests/ -v
```

10 unit tests cover URL parsing, jitter range, UA pool, adaptive backoff.

## Legal note

Personal-use archival of content **you own** (e.g. your own sound's videos) or
content you have explicit permission to download. Bulk-scraping third-party
content violates TikTok's ToS. Respect creators.

## Build the `.app` (macOS)

Ship a double-clickable `Video Download.app` so non-technical users
don't need terminal/Python. (For Windows, see **Build on Windows** below.)

### Prereqs (one-time)

1. **Python ≥3.10 with Tk** (python.org installer recommended — Homebrew Python lacks Tk).
2. Create venv and install deps + PyInstaller:

```bash
cd Projects/tiktok-music-downloader
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[build]"
playwright install chromium    # for local dev runs (not bundled)
```

### Build

```bash
# 1. Generate the .icns icon from SVG (one-time, or after icon.svg edits)
bash build-scripts/build-icon.sh

# 2. Build the .app
bash build-scripts/build-app.sh
```

Output: `dist/Video Download.app` (~170 MB — yt-dlp extractors + Playwright driver bundled).

### Build on Windows

```powershell
# from the project root, in an activated venv with deps + pyinstaller
powershell -ExecutionPolicy Bypass -File build-scripts\build-app.ps1
```

Output: `dist\video-download\` — run `video-download.exe` inside it. Share the
**whole folder** (zip it), not just the .exe. SmartScreen may warn on the
unsigned app: **More info → Run anyway**.

> **ffmpeg on Windows:** the watermark step needs ffmpeg. Either drop a static
> `ffmpeg.exe` into `assets\ffmpeg-static\` before building (it gets bundled),
> or have ffmpeg on `PATH` at runtime. Downloads work either way — only the
> watermark is skipped if ffmpeg is missing.

### First launch on a target machine

1. Drag `.app` into `/Applications` (or anywhere).
2. **Right-click → Open → Open** (one-time Gatekeeper bypass for unsigned apps).
3. App detects Chromium missing → downloads it (~150 MB, one-time, ~1-2 min).
4. After that, subsequent launches are instant.

### Distribute

The `.app` is self-contained Python + deps. To share with someone:
- Zip the `.app` folder.
- They unzip, right-click → Open the first time.
- No Python install needed on their machine.

> **Signing/notarization:** unsigned apps trigger Gatekeeper. For wide
> distribution, sign with Apple Developer ID (`codesign`) + notarize. Beyond
> the scope of this README.

## Project layout

```
src/tiktok_music_downloader/
├── __init__.py
├── __main__.py        # python -m tiktok_music_downloader
├── bootstrap.py       # First-run Chromium auto-install
├── cli.py             # Typer CLI
├── downloader.py      # yt-dlp wrapper
├── gui.py             # Tkinter window
├── gui_helpers.py     # Thread-safe queue adapters
├── scraper.py         # Playwright music-page scraper
└── utils.py           # logger, URL parsing, jitter, UA pool, backoff

build-scripts/
├── app-entry.py                       # frozen-app entry point
├── tiktok-music-downloader.spec       # PyInstaller spec
├── build-app.sh                       # macOS build: PyInstaller + ad-hoc codesign
├── build-app.ps1                      # Windows build: PyInstaller (PowerShell)
└── build-icon.sh                      # SVG → .icns via ImageMagick + iconutil

assets/
├── icon.svg                           # editable source
└── icon.icns                          # produced by build-icon.sh
```

## Distribute to teammates (free, no Apple Developer ID)

1. `cd dist && zip -r video-download-mac.zip "Video Download.app"`
2. Send the zip (Slack, Drive, etc.).
3. Teammate:
   - Unzips.
   - Runs **once** in Terminal to strip the macOS "downloaded" quarantine flag (otherwise macOS shows "damaged" because the .app is unsigned):
     ```bash
     xattr -dr com.apple.quarantine "Video Download.app"
     ```
   - Right-click → Open → Open (one-time Gatekeeper bypass).
   - First launch downloads Chromium (~150 MB, one-time).
