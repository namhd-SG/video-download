# tiktok-music-downloader

Bulk-download watermark-free MP4 videos from a TikTok page. Supported sources:

- **Music page** — `https://www.tiktok.com/music/original-sound-7374515087526136619`
- **Profile page** — `https://www.tiktok.com/@cataldotez5` (all videos of a user)
- **Search page** — `https://www.tiktok.com/search?q=...`

Built for creators who want to archive all videos using their own sound or a
whole profile's catalogue.

> **Profile & search pages need Cookies** (a logged-in TikTok session) to load
> every video — anonymous runs often return few or 0. See the `--cookies` flag /
> GUI *Cookies* field below.

Two entry points:
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

Homebrew Python 3.13/3.14 **does not ship Tk** — importing `tkinter` fails
with `ModuleNotFoundError: No module named '_tkinter'`. Pick one:

| Choice | Install | Notes |
|--------|---------|-------|
| Homebrew + Tk bottle | `brew install python@3.13 python-tk@3.13` | Ships Tk 9.x. **Recommended** — pairs with the venv command below. |
| python.org installer | https://www.python.org/downloads/macos/ | Ships Tk 9.x. |
| System Python | already there at `/usr/bin/python3` | Old Tk 8.5, but works for GUI |

CLI only (no GUI)? Any Python ≥3.10 works — skip the Tk step.

### Install the package

> **Create the venv with a Tk-enabled interpreter.** Bare `python3` on
> Homebrew points at 3.14 (no Tk) and the GUI will crash on launch. Pin the
> version explicitly:

```bash
cd Projects/tiktok-music-downloader
python3.13 -m venv .venv          # must be a python that has Tk (see table above)
source .venv/bin/activate
python -c "import tkinter"         # sanity check — must print nothing (no error)
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
# Music page
tiktok-music-dl "https://www.tiktok.com/music/original-sound-7374515087526136619" \
  --output ./downloads \
  --max 200 \
  --delay 2.0

# Whole profile (needs cookies to load all videos)
tiktok-music-dl "https://www.tiktok.com/@cataldotez5" \
  --output ./downloads \
  --cookies ./tiktok-cookies.json \
  --max 200
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

Ship a double-clickable `TikTok Music Downloader.app` so non-technical users
don't need terminal/Python.

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

Output: `dist/TikTok Music Downloader.app` (~170 MB — yt-dlp extractors + Playwright driver bundled).

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
├── build-app.sh                       # PyInstaller wrapper + ad-hoc codesign
└── build-icon.sh                      # SVG → .icns via ImageMagick + iconutil

assets/
├── icon.svg                           # editable source
└── icon.icns                          # produced by build-icon.sh
```

## Distribute to teammates (free, no Apple Developer ID)

1. `cd dist && zip -r tiktok-music-downloader.zip "TikTok Music Downloader.app"`
2. Send the zip (Slack, Drive, etc.).
3. Teammate:
   - Unzips.
   - Runs **once** in Terminal to strip the macOS "downloaded" quarantine flag (otherwise macOS shows "damaged" because the .app is unsigned):
     ```bash
     xattr -dr com.apple.quarantine "TikTok Music Downloader.app"
     ```
   - Right-click → Open → Open (one-time Gatekeeper bypass).
   - First launch downloads Chromium (~150 MB, one-time).
