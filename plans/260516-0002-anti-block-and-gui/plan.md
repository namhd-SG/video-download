# Anti-Block Hardening + Tkinter GUI

**Created:** 2026-05-16 00:02
**Status:** Completed
**Parent:** v0.1 (CLI baseline)

## Goal

1. Reduce risk of TikTok rate-limit / captcha on 50-500 video runs.
2. Add Tkinter GUI so non-technical users can run without terminal.

## Anti-block tactics (KISS — only proven, low-effort)

| # | Tactic | Where |
|---|--------|-------|
| 1 | Random jitter delay (1.5-4s) instead of fixed 2s | utils + downloader |
| 2 | Rotating User-Agent pool (5 recent UAs) | utils + scraper |
| 3 | `--proxy http://user:pass@host:port` flag (single proxy) | cli + scraper + downloader |
| 4 | Persistent Playwright context dir → cookies survive runs | scraper |
| 5 | Adaptive backoff on 429/blocked (sleep 30s, then 60s, …) | downloader |
| 6 | Stealth init script (hide `navigator.webdriver`) | scraper |
| 7 | Chunk into batches of 50 with 60s rest between batches | downloader |

## GUI (Tkinter + ttk)

Single window, no menu bar. Widgets:
- URL entry (top, full-width)
- Output dir + Browse button
- Max videos spinbox, Delay spinbox, Proxy entry (optional)
- Headful checkbox, Verbose checkbox
- Start / Stop buttons
- Progress bar
- Scrolling log textbox (bottom)

Threading: worker thread runs scrape+download; UI updated via `queue.Queue` polled by `after()`.

## Phases

| # | Phase | Status |
|---|-------|--------|
| 1 | utils.py: JitterThrottle, UA pool, adaptive backoff helper | ☑ |
| 2 | scraper.py: persistent context, UA rotation, proxy, stealth | ☑ |
| 3 | downloader.py: jitter, adaptive backoff, batching | ☑ |
| 4 | cli.py: new flags --proxy --profile-dir | ☑ |
| 5 | gui.py + gui_helpers.py: Tkinter window + threaded worker | ☑ |
| 6 | pyproject.toml: add `tiktok-music-dl-gui` script entry | ☑ |
| 7 | tests (10/10 pass) + compile check (all modules) | ☑ |

## Success Criteria

- All previous tests still pass
- New: jitter test (avg delay within range), UA pool non-empty
- Compile pass on all modules (`python3 -m py_compile`)
- `tiktok-music-dl-gui` launches Tkinter window
- CLI accepts `--proxy` and `--profile-dir` without error
