"""Tkinter GUI: paste URL, click Start, watch progress with stats + colored log."""
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from tiktok_music_downloader.bootstrap import ensure_chromium
from tiktok_music_downloader.downloader import download_all
from tiktok_music_downloader.gui_helpers import (
    QueueHandler,
    StatCard,
    StatusPill,
    UiProgress,
)
from tiktok_music_downloader.gui_style import (
    BG_WINDOW,
    apply_styles,
    classify_log,
    configure_log_tags,
    FONT_LOG,
    TEXT,
)
from tiktok_music_downloader.scraper import scrape_music_page_multi
from tiktok_music_downloader.utils import is_music_page, setup_logger

POLL_INTERVAL_MS = 100
PAD_OUT = 16  # outer section padding


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("TikTok Music Downloader")
        root.geometry("780x720")
        root.minsize(640, 600)

        apply_styles(root)

        self.log_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.bootstrap_ok = False
        self.stats = {"scraped": 0, "downloaded": 0, "skipped": 0, "failed": 0}

        self._build_header()
        self._build_form()
        self._build_action_row()
        self._build_progress_and_stats()
        self._build_log()
        self._attach_logger()

        root.after(POLL_INTERVAL_MS, self._poll_queue)
        self._kickoff_bootstrap()

    # ------------------------------------------------------------------ build
    def _build_header(self) -> None:
        bar = ttk.Frame(self.root, padding=(PAD_OUT, PAD_OUT, PAD_OUT, 8))
        bar.pack(fill="x")
        ttk.Label(bar, text="🎵  TikTok Music Downloader",
                  style="Title.TLabel").pack(side="left")
        self.status_pill = StatusPill(bar, state="Idle")
        self.status_pill.pack(side="right")

    def _build_form(self) -> None:
        src = ttk.Labelframe(self.root, text=" Source ", padding=12)
        src.pack(fill="x", padx=PAD_OUT, pady=(0, 8))
        ttk.Label(src, text="URL").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.url_var = tk.StringVar()
        ttk.Entry(src, textvariable=self.url_var).grid(
            row=0, column=1, sticky="ew", ipady=3)
        src.columnconfigure(1, weight=1)

        opt = ttk.Labelframe(self.root, text=" Options ", padding=12)
        opt.pack(fill="x", padx=PAD_OUT, pady=(0, 8))

        ttk.Label(opt, text="Output").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.out_var = tk.StringVar(
            value=str(Path.home() / "Downloads" / "tiktok-music"))
        ttk.Entry(opt, textvariable=self.out_var).grid(
            row=0, column=1, columnspan=3, sticky="ew", ipady=3)
        ttk.Button(opt, text="Browse…", command=self._pick_dir).grid(
            row=0, column=4, padx=(8, 0))

        ttk.Label(opt, text="Max videos").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.max_var = tk.IntVar(value=200)
        ttk.Spinbox(opt, from_=1, to=2000, textvariable=self.max_var,
                    width=8).grid(row=1, column=1, sticky="w", pady=(10, 0))

        ttk.Label(opt, text="Delay (s)").grid(row=1, column=2, sticky="e", padx=(12, 8), pady=(10, 0))
        self.delay_var = tk.DoubleVar(value=2.0)
        ttk.Spinbox(opt, from_=0.0, to=30.0, increment=0.5,
                    textvariable=self.delay_var, width=8).grid(
            row=1, column=3, sticky="w", pady=(10, 0))

        # Passes: TikTok music pages return a randomized slice per visit.
        # Re-scraping 2-3× with delay accumulates more uniques; > 3 risks block.
        ttk.Label(opt, text="Passes").grid(row=1, column=4, sticky="e", padx=(12, 8), pady=(10, 0))
        self.passes_var = tk.IntVar(value=1)
        ttk.Spinbox(opt, from_=1, to=5, textvariable=self.passes_var,
                    width=4).grid(row=1, column=5, sticky="w", pady=(10, 0))

        ttk.Label(opt, text="Proxy").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.proxy_var = tk.StringVar()
        ttk.Entry(opt, textvariable=self.proxy_var).grid(
            row=2, column=1, columnspan=5, sticky="ew", ipady=3, pady=(10, 0))

        # Cookies JSON (Playwright storage_state / EditThisCookie export) — used to
        # bypass TikTok's guest video limit (~28) by reusing a logged-in session.
        ttk.Label(opt, text="Cookies").grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.cookies_var = tk.StringVar()
        ttk.Entry(opt, textvariable=self.cookies_var).grid(
            row=3, column=1, columnspan=4, sticky="ew", ipady=3, pady=(10, 0))
        ttk.Button(opt, text="Browse…", command=self._pick_cookies).grid(
            row=3, column=5, padx=(8, 0), pady=(10, 0))

        self.headful_var = tk.BooleanVar(value=False)
        self.verbose_var = tk.BooleanVar(value=False)
        # Persistent profile: TikTok sees a returning user → less likely to
        # captcha or rate-limit than a fresh ephemeral context every run.
        self.keep_session_var = tk.BooleanVar(value=True)
        flags = ttk.Frame(opt)
        flags.grid(row=4, column=0, columnspan=6, sticky="w", pady=(10, 0))
        ttk.Checkbutton(flags, text="Show browser (headful)",
                        variable=self.headful_var).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(flags, text="Keep session",
                        variable=self.keep_session_var).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(flags, text="Verbose log",
                        variable=self.verbose_var).pack(side="left")

        opt.columnconfigure(1, weight=1)

    def _build_action_row(self) -> None:
        wrap = ttk.Frame(self.root, padding=(PAD_OUT, 4, PAD_OUT, 8))
        wrap.pack(fill="x")
        self.start_btn = ttk.Button(wrap, text="▶  START",
                                    style="Primary.TButton",
                                    command=self._start)
        self.start_btn.pack()

    def _build_progress_and_stats(self) -> None:
        wrap = ttk.Frame(self.root, padding=(PAD_OUT, 0, PAD_OUT, 8))
        wrap.pack(fill="x")

        row = ttk.Frame(wrap)
        row.pack(fill="x")
        self.progress = ttk.Progressbar(row, mode="determinate", maximum=1,
                                        style="Big.Horizontal.TProgressbar")
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress_lbl = ttk.Label(row, text="0 / 0  (0%)",
                                      style="Progress.TLabel", width=16,
                                      anchor="e")
        self.progress_lbl.pack(side="right", padx=(10, 0))

        cards = ttk.Frame(wrap)
        cards.pack(fill="x", pady=(10, 0))
        self.card_scraped    = StatCard(cards, "Scraped")
        self.card_downloaded = StatCard(cards, "Downloaded")
        self.card_skipped    = StatCard(cards, "Skipped")
        self.card_failed     = StatCard(cards, "Failed")
        for i, c in enumerate(
            (self.card_scraped, self.card_downloaded, self.card_skipped, self.card_failed)
        ):
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            cards.columnconfigure(i, weight=1)

    def _build_log(self) -> None:
        wrap = ttk.Labelframe(self.root, text=" Activity log ", padding=10)
        wrap.pack(fill="both", expand=True, padx=PAD_OUT, pady=(0, PAD_OUT))

        # Hand-built Text + Scrollbar so we can apply dark bg + tags.
        body = tk.Frame(wrap, bg=BG_WINDOW, highlightthickness=0, bd=0)
        body.pack(fill="both", expand=True)
        self.log_box = tk.Text(
            body, height=14, wrap="word",
            bg="#16161a", fg=TEXT, insertbackground=TEXT,
            relief="flat", bd=0, padx=10, pady=8,
            font=FONT_LOG, state="disabled",
        )
        sb = ttk.Scrollbar(body, orient="vertical", command=self.log_box.yview)
        self.log_box.config(yscrollcommand=sb.set)
        self.log_box.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        configure_log_tags(self.log_box)

    # ----------------------------------------------------------- behaviour
    def _pick_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.out_var.get() or str(Path.cwd()))
        if chosen:
            self.out_var.set(chosen)

    def _pick_cookies(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Select cookies JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=str(Path.home()),
        )
        if chosen:
            self.cookies_var.set(chosen)

    def _attach_logger(self) -> None:
        logger = setup_logger(self.verbose_var.get())
        for h in list(logger.handlers):
            if isinstance(h, QueueHandler):
                logger.removeHandler(h)
        handler = QueueHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
        logger.addHandler(handler)

    def _kickoff_bootstrap(self) -> None:
        """On first launch, install Chromium in a worker thread."""
        self.status_pill.set("Setting up")
        self.start_btn.config(state="disabled", text="Setting up…")

        def _runner():
            ok = ensure_chromium(lambda msg: self.log_queue.put(msg))
            self.log_queue.put(("bootstrap_done", ok))

        threading.Thread(target=_runner, daemon=True).start()

    def _reset_stats(self) -> None:
        self.stats = {"scraped": 0, "downloaded": 0, "skipped": 0, "failed": 0}
        self.card_scraped.set(0)
        self.card_downloaded.set(0)
        self.card_skipped.set(0)
        self.card_failed.set(0)

    def _start(self) -> None:
        if not self.bootstrap_ok:
            self._append_log("setup not finished — please wait")
            return
        url = self.url_var.get().strip()
        if not is_music_page(url):
            self._append_log("ERROR: URL must be a TikTok /music/ page")
            return
        if self.worker and self.worker.is_alive():
            return
        self._attach_logger()
        self._reset_stats()
        self.progress.config(value=0, maximum=max(1, self.max_var.get()))
        self._update_progress_label()
        self.start_btn.config(state="disabled", text="Working…")
        self.status_pill.set("Scraping")
        self.worker = threading.Thread(target=self._run_pipeline, args=(url,), daemon=True)
        self.worker.start()

    def _run_pipeline(self, url: str) -> None:
        try:
            # "Keep session" persists Playwright profile under the user's app-support
            # dir — TikTok then sees a returning client across runs (less captcha).
            profile_dir: str | None = None
            if self.keep_session_var.get():
                p = (Path.home() / "Library" / "Application Support"
                     / "tiktok-music-downloader" / "playwright-profile")
                profile_dir = str(p)

            refs = scrape_music_page_multi(
                url,
                passes=self.passes_var.get(),
                max_videos=self.max_var.get(),
                headless=not self.headful_var.get(),
                proxy=self.proxy_var.get().strip() or None,
                cookies_path=self.cookies_var.get().strip() or None,
                profile_dir=profile_dir,
            )
            if not refs:
                self.log_queue.put("no videos found — try Show browser (headful)")
                self.log_queue.put(("status", "Error"))
                return
            self.log_queue.put(("stat_set", ("scraped", len(refs))))
            self.log_queue.put(("max", len(refs)))
            self.log_queue.put(("status", "Downloading"))
            downloaded, skipped, failed = download_all(
                refs,
                Path(self.out_var.get()),
                delay_seconds=self.delay_var.get(),
                proxy=self.proxy_var.get().strip() or None,
                progress=UiProgress(self.log_queue),
                cookies_path=self.cookies_var.get().strip() or None,
            )
            self.log_queue.put(
                f"DONE — downloaded={downloaded} skipped={skipped} failed={len(failed)}"
            )
            self.log_queue.put(("status", "Done"))
        except Exception as exc:  # noqa: BLE001
            self.log_queue.put(f"ERROR: {exc}")
            self.log_queue.put(("status", "Error"))
        finally:
            self.log_queue.put(("enable_start", None))

    # -------------------------------------------------------------- queue
    def _poll_queue(self) -> None:
        try:
            while True:
                item = self.log_queue.get_nowait()
                if isinstance(item, tuple):
                    self._handle_event(item)
                else:
                    self._append_log(item)
        except queue.Empty:
            pass
        self.root.after(POLL_INTERVAL_MS, self._poll_queue)

    def _handle_event(self, item: tuple) -> None:
        kind, payload = item
        if kind == "progress":
            self.progress.step(payload)
            self._update_progress_label()
        elif kind == "max":
            self.progress.config(value=0, maximum=max(1, int(payload)))
            self._update_progress_label()
        elif kind == "stat":
            if payload in self.stats:
                self.stats[payload] += 1
                self._refresh_card(payload)
        elif kind == "stat_set":
            key, val = payload
            if key in self.stats:
                self.stats[key] = int(val)
                self._refresh_card(key)
        elif kind == "status":
            self.status_pill.set(str(payload))
        elif kind == "enable_start":
            self.start_btn.config(state="normal", text="▶  START")
        elif kind == "bootstrap_done":
            self.bootstrap_ok = bool(payload)
            self.start_btn.config(
                state="normal" if payload else "disabled",
                text="▶  START" if payload else "Setup failed",
            )
            self.status_pill.set("Idle" if payload else "Setup failed")

    def _refresh_card(self, key: str) -> None:
        card = {
            "scraped": self.card_scraped,
            "downloaded": self.card_downloaded,
            "skipped": self.card_skipped,
            "failed": self.card_failed,
        }[key]
        card.set(self.stats[key])

    def _update_progress_label(self) -> None:
        cur = int(self.progress["value"])
        total = int(self.progress["maximum"])
        pct = int(round(100 * cur / total)) if total else 0
        self.progress_lbl.config(text=f"{cur} / {total}  ({pct}%)")

    def _append_log(self, msg: str) -> None:
        tag, icon = classify_log(msg)
        self.log_box.config(state="normal")
        self.log_box.insert("end", f" {icon}  {msg}\n", tag)
        self.log_box.see("end")
        self.log_box.config(state="disabled")


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
