"""Web layer: thin FastAPI wrapper around the existing CLI core.

Tkinter cannot be served over HTTP, so this package exists to expose the same
scrape/download core (`tiktok_music_downloader.*`, never modified here) behind
a job queue + browser UI. See `plans/260914-1412-tool-len-mini-va-domain/`.
"""
