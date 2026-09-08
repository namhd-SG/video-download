"""Tkinter GUI: paste URL, click Start, watch progress with stats + colored log."""
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from tiktok_music_downloader.bootstrap import ensure_chromium
from tiktok_music_downloader.downloader import download_all
from tiktok_music_downloader.gui_helpers import (
    QueueHandler,
    StatCard,
    StatusPill,
    UiProgress,
)
from tiktok_music_downloader.gui_style import (
    ACCENT,
    BG_SURFACE,
    BG_WINDOW,
    apply_styles,
    classify_log,
    configure_log_tags,
    FONT_LOG,
    TEXT,
    TEXT_DIM,
)
from tiktok_music_downloader.gdrive import download_folder as gdrive_download_folder
from tiktok_music_downloader.local_watermark import iter_mp4s, watermark_folder
from tiktok_music_downloader.scraper import scrape_music_page_multi
from tiktok_music_downloader.scraper_fb import scrape_ads_library
from tiktok_music_downloader.watermark import (
    PATTERN_LABELS_VI,
    PATTERNS,
    QUALITY_FILTERS,
    WatermarkConfig,
)

# Combobox values: "<key> — <Vietnamese description>" so users see both.
# _pattern_key() strips back to the bare key for storage in WatermarkConfig.
PATTERN_CHOICES = [f"{k} — {PATTERN_LABELS_VI[k]}" for k in PATTERNS]


def _pattern_key(combo_value: str) -> str:
    """Extract pattern key from a 'key — label' combobox value."""
    return (combo_value or "").split(" — ", 1)[0].strip() or "orbit"
from tiktok_music_downloader.utils import (
    is_fb_ads_library,
    is_gdrive_folder,
    is_search_page,
    is_tag_page,
    is_tiktok_collection,
    setup_logger,
)

POLL_INTERVAL_MS = 100
PAD_OUT = 16  # outer section padding


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("Video Download")
        # Wide enough that the Source/Cookies hint lines show in full by default
        # (they were being clipped at the old 820px width).
        root.geometry("1240x940")
        root.minsize(900, 560)
        root.resizable(True, True)

        apply_styles(root)

        self.log_queue: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.bootstrap_ok = False
        self.stats = {"scraped": 0, "downloaded": 0, "skipped": 0, "failed": 0}

        # Vertical scroll: the form alone is taller than the user's screen on
        # smaller laptops, so wrap everything in a Canvas + Scrollbar. All
        # _build_* methods parent their widgets to self.body instead of root.
        self.body = self._setup_scrollable(root)

        self._build_header()
        self._build_tabs()
        self._build_form()           # populates Download tab
        self._build_folder_form()    # populates Watermark-folder tab
        self._build_watermark()
        self._build_action_row()
        self._build_progress_and_stats()
        self._build_log()
        self._attach_logger()

        # Now that every form widget exists, attach the mousewheel handler to
        # each of them — see _setup_scrollable for why bind_all alone isn't
        # enough on macOS Aqua.
        self._bind_wheel_recursive(self.body)

        root.after(POLL_INTERVAL_MS, self._poll_queue)
        self._kickoff_bootstrap()
        # First launch: show a short guided tour once the window is drawn.
        root.after(500, self._maybe_first_run_tour)

    # ------------------------------------------------------------------ build
    def _setup_scrollable(self, root: tk.Tk) -> ttk.Frame:
        """Wrap window contents in a Canvas + Scrollbar so tall forms scroll."""
        canvas = tk.Canvas(root, bg=BG_WINDOW, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        body = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")

        # Resize the inner frame's scrollregion when its content size changes,
        # and stretch its width to match the canvas so children fill horizontally.
        body.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(window_id, width=e.width),
        )

        # Mousewheel scrolling — cross-platform.
        # macOS Aqua doesn't propagate <MouseWheel> from ttk widgets up to
        # bind_all reliably, so we attach the handler directly on each widget
        # inside `body` (recursively, after build) and on any later children.
        def _on_wheel(event):
            d = event.delta
            if abs(d) >= 120:           # Windows
                lines = int(d / 120) * 3
            else:                        # macOS / Aqua trackpad
                lines = (1 if d > 0 else -1) * 3
            canvas.yview_scroll(-lines, "units")

        def _btn4(_e): canvas.yview_scroll(-3, "units")
        def _btn5(_e): canvas.yview_scroll(3, "units")

        # Save for the recursive binder called after the form is built.
        self._scroll_handlers = (_on_wheel, _btn4, _btn5)
        self._scroll_canvas = canvas
        # Still bind_all as a fallback for the Canvas / Scrollbar themselves.
        canvas.bind_all("<Button-4>", _btn4)
        canvas.bind_all("<Button-5>", _btn5)
        canvas.bind("<MouseWheel>", _on_wheel)
        return body

    def _bind_wheel_recursive(self, widget) -> None:
        """Attach the wheel handlers to `widget` and every descendant.

        Skips tk.Text (the log box) so the Text widget's built-in scrolling
        keeps working without competing with the outer canvas scroll.
        """
        on_wheel, btn4, btn5 = self._scroll_handlers
        def _bind(w):
            if isinstance(w, tk.Text):
                return
            try:
                w.bind("<MouseWheel>", on_wheel, add="+")
                w.bind("<Button-4>", btn4, add="+")
                w.bind("<Button-5>", btn5, add="+")
            except tk.TclError:
                pass
            for c in w.winfo_children():
                _bind(c)
        _bind(widget)

    def _build_header(self) -> None:
        bar = ttk.Frame(self.body, padding=(PAD_OUT, PAD_OUT, PAD_OUT, 8))
        bar.pack(fill="x")
        ttk.Label(bar, text="⬇  Video Download",
                  style="Title.TLabel").pack(side="left")
        self.status_pill = StatusPill(bar, state="Idle")
        self.status_pill.pack(side="right")
        # Re-openable guided tour (also shown automatically on first launch).
        ttk.Button(bar, text="❔ Hướng dẫn", command=self._show_welcome).pack(
            side="right", padx=(0, 10))

    def _build_tabs(self) -> None:
        """Notebook with two pipelines: Download URLs vs. Watermark a folder.

        Each tab carries its own source-side inputs. Watermark settings, action
        button, progress bar, and log live BELOW the notebook so they're shared
        across modes — there's only one pipeline running at a time anyway.
        """
        self.notebook = ttk.Notebook(self.body)
        self.notebook.pack(fill="x", padx=PAD_OUT, pady=(0, 10))
        self.tab_download = ttk.Frame(self.notebook, padding=4)
        self.tab_folder = ttk.Frame(self.notebook, padding=4)
        self.notebook.add(self.tab_download, text="  ⬇  Download  ")
        self.notebook.add(self.tab_folder, text="  🗂  Watermark folder  ")

    def _build_form(self) -> None:
        src = ttk.Labelframe(self.tab_download, text="  🔗  Source  ",
                              style="Section.TLabelframe", padding=18)
        src.pack(fill="x", padx=PAD_OUT, pady=(0, 10))
        ttk.Label(src, text="URL").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.url_var = tk.StringVar()
        ttk.Entry(src, textvariable=self.url_var).grid(
            row=0, column=1, sticky="ew", ipady=4)
        # Platform note — the tool only downloads from these sources, so users
        # know what to paste. Keep in sync with the URL validator in _start().
        ttk.Label(src, style="Hint.TLabel",
                  text="Hỗ trợ tải từ:  TikTok (trang /music/ • /tag/ • /search)  •  "
                       "Facebook Ads Library (/ads/library)  •  "
                       "Google Drive (link folder chia sẻ)"
                  ).grid(row=1, column=1, sticky="w", pady=(4, 0))
        src.columnconfigure(1, weight=1)

        opt = ttk.Labelframe(self.tab_download, text="  ⚙  Options  ",
                              style="Section.TLabelframe", padding=18)
        opt.pack(fill="x", padx=PAD_OUT, pady=(0, 10))

        ttk.Label(opt, text="Output").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.out_var = tk.StringVar(
            value=str(Path.home() / "Downloads" / "tiktok-music"))
        ttk.Entry(opt, textvariable=self.out_var).grid(
            row=0, column=1, columnspan=3, sticky="ew", ipady=3)
        ttk.Button(opt, text="Browse…", command=self._pick_dir).grid(
            row=0, column=4, padx=(8, 0))

        ttk.Label(opt, text="Max videos").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.max_var = tk.IntVar(value=100)
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

        # Note so users know these are freely adjustable.
        ttk.Label(opt, style="Hint.TLabel",
                  text="💡 Chỉnh tự do: Max videos = số video tối đa (1–2000)  •  "
                       "Delay = giãn cách giây giữa mỗi video (tăng nếu bị chặn)  •  "
                       "Passes = quét lại nhiều lần để gom thêm video (TikTok)"
                  ).grid(row=2, column=1, columnspan=5, sticky="w", pady=(2, 0))

        ttk.Label(opt, text="Proxy").grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.proxy_var = tk.StringVar()
        ttk.Entry(opt, textvariable=self.proxy_var).grid(
            row=3, column=1, columnspan=5, sticky="ew", ipady=3, pady=(10, 0))

        # Cookies JSON (Playwright storage_state / EditThisCookie export) — used to
        # bypass TikTok's guest video limit (~28) by reusing a logged-in session.
        ttk.Label(opt, text="Cookies").grid(row=4, column=0, sticky="w", pady=(10, 0))
        self.cookies_var = tk.StringVar()
        ttk.Entry(opt, textvariable=self.cookies_var).grid(
            row=4, column=1, columnspan=4, sticky="ew", ipady=3, pady=(10, 0))
        ttk.Button(opt, text="Browse…", command=self._pick_cookies).grid(
            row=4, column=5, padx=(8, 0), pady=(10, 0))
        # Cookies are TikTok-only — explain that and offer a how-to so users don't
        # think they need it for Facebook / Google Drive.
        ttk.Label(opt, style="Hint.TLabel",
                  text="🔒 Chỉ cần cho TikTok (trang /search, hoặc để vượt giới hạn "
                       "~28 video khi chưa đăng nhập). Facebook / Google Drive KHÔNG cần."
                  ).grid(row=5, column=1, columnspan=4, sticky="w", pady=(2, 0))
        ttk.Button(opt, text="Cách lấy cookie", command=self._show_cookie_help).grid(
            row=5, column=5, padx=(8, 0), pady=(2, 0))

        self.headful_var = tk.BooleanVar(value=False)
        self.verbose_var = tk.BooleanVar(value=False)
        # Persistent profile: TikTok sees a returning user → less likely to
        # captcha or rate-limit than a fresh ephemeral context every run.
        self.keep_session_var = tk.BooleanVar(value=True)
        flags = ttk.Frame(opt)
        flags.grid(row=6, column=0, columnspan=6, sticky="w", pady=(10, 0))
        ttk.Checkbutton(flags, text="Show browser (headful)",
                        variable=self.headful_var).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(flags, text="Keep session",
                        variable=self.keep_session_var).pack(side="left", padx=(0, 16))
        ttk.Checkbutton(flags, text="Verbose log",
                        variable=self.verbose_var).pack(side="left")

        opt.columnconfigure(1, weight=1)

    def _build_folder_form(self) -> None:
        """Tab 2 inputs: source folder + recursive + output folder.

        Watermark settings come from the shared section below the notebook,
        so this tab only needs the I/O paths and the recursion flag.
        """
        wrap = ttk.Labelframe(self.tab_folder, text="  🗂  Folder paths  ",
                              style="Section.TLabelframe", padding=18)
        wrap.pack(fill="x", padx=0, pady=(0, 0))

        ttk.Label(wrap, text="Source").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.folder_src_var = tk.StringVar()
        ttk.Entry(wrap, textvariable=self.folder_src_var).grid(
            row=0, column=1, columnspan=3, sticky="ew", ipady=3)
        ttk.Button(wrap, text="Browse…",
                   command=lambda: self._pick_dir_into(self.folder_src_var)).grid(
            row=0, column=4, padx=(8, 0))

        ttk.Label(wrap, text="Output").grid(row=1, column=0, sticky="w",
                                             padx=(0, 8), pady=(10, 0))
        self.folder_out_var = tk.StringVar(
            value=str(Path.home() / "Downloads" / "tiktok-music-watermarked"))
        ttk.Entry(wrap, textvariable=self.folder_out_var).grid(
            row=1, column=1, columnspan=3, sticky="ew", ipady=3, pady=(10, 0))
        ttk.Button(wrap, text="Browse…",
                   command=lambda: self._pick_dir_into(self.folder_out_var)).grid(
            row=1, column=4, padx=(8, 0), pady=(10, 0))

        # Recursive walk — when on, mirrors the subfolder tree into output.
        self.folder_recursive_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(wrap, text="Recursive (walk subfolders, mirror structure)",
                        variable=self.folder_recursive_var).grid(
            row=2, column=1, columnspan=4, sticky="w", pady=(10, 0))

        ttk.Label(wrap, style="Hint.TLabel",
                  text="Source files stay intact — every mp4 is copied to a mirrored "
                       "path under Output, then watermarked there."
                  ).grid(row=3, column=1, columnspan=4, sticky="w", pady=(4, 0))

        wrap.columnconfigure(1, weight=1)

    def _build_watermark(self) -> None:
        """Optional watermark section: animated text only."""
        wm = ttk.Labelframe(self.body, text="  ✨  Watermark (optional)  ",
                             style="Section.TLabelframe", padding=18)
        wm.pack(fill="x", padx=PAD_OUT, pady=(0, 10))

        # Master toggle. Even when ON, the text field can be empty to skip the
        # overlay — the downloader treats an "all empty" config as a no-op so
        # the videos pass through untouched.
        self.wm_enable_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(wm, text="Apply watermark to downloads",
                        variable=self.wm_enable_var).grid(
            row=0, column=0, columnspan=6, sticky="w", pady=(0, 8))

        # Animated text overlay — the only overlay in this build.
        ttk.Label(wm, text="Animated text").grid(row=3, column=0, sticky="w",
                                                  padx=(0, 8), pady=(10, 0))
        self.wm_text_var = tk.StringVar()
        ttk.Entry(wm, textvariable=self.wm_text_var).grid(
            row=3, column=1, columnspan=3, sticky="ew", ipady=3, pady=(10, 0))
        ttk.Label(wm, text="Pattern").grid(row=3, column=4, sticky="e",
                                            padx=(12, 6), pady=(10, 0))
        self.wm_text_pattern_var = tk.StringVar(value=PATTERN_CHOICES[0])
        ttk.Combobox(wm, textvariable=self.wm_text_pattern_var,
                     values=PATTERN_CHOICES,
                     state="readonly", width=24).grid(
            row=3, column=5, columnspan=2, sticky="w", pady=(10, 0))

        # Opacity.
        ttk.Label(wm, text="Opacity %").grid(row=5, column=0, sticky="w",
                                               padx=(0, 8), pady=(10, 0))
        self.wm_opacity_var = tk.IntVar(value=35)
        ttk.Spinbox(wm, from_=5, to=100, textvariable=self.wm_opacity_var,
                    width=4).grid(row=5, column=1, sticky="w", pady=(10, 0))
        ttk.Label(wm, style="Hint.TLabel",
                  text="Chữ chạy theo pattern đã chọn — chỉnh độ mờ bằng Opacity %"
                  ).grid(row=5, column=2, columnspan=5, sticky="w",
                         padx=(12, 0), pady=(10, 0))

        # Output quality (applied after overlay during re-encode).
        ttk.Label(wm, text="Quality").grid(row=7, column=0, sticky="w",
                                            padx=(0, 8), pady=(10, 0))
        self.wm_quality_var = tk.StringVar(value="hd")
        ttk.Combobox(wm, textvariable=self.wm_quality_var,
                     values=list(QUALITY_FILTERS.keys()),
                     state="readonly", width=14).grid(
            row=7, column=1, sticky="w", pady=(10, 0))
        ttk.Label(wm, style="Hint.TLabel",
                  text="HD / FullHD force exact frame size — text stays consistent"
                  ).grid(row=7, column=2, columnspan=5, sticky="w",
                         padx=(10, 0), pady=(10, 0))

        wm.columnconfigure(1, weight=1)

    def _build_action_row(self) -> None:
        wrap = ttk.Frame(self.body, padding=(PAD_OUT, 4, PAD_OUT, 8))
        wrap.pack(fill="x")
        self.start_btn = ttk.Button(wrap, text="▶  START",
                                    style="Primary.TButton",
                                    command=self._start)
        self.start_btn.pack()
        # Highlighted tip: the very first run often fails a few videos (TikTok
        # cold-start) — pressing START again resumes and picks up the rest.
        ttk.Label(
            wrap,
            text="💡 Lần đầu tải đôi khi lỗi vài video (TikTok khởi động) — "
                 "cứ bấm START lại: app TỰ BỎ QUA video đã tải và lấy nốt phần còn thiếu.",
            style="Tip.TLabel", wraplength=760, justify="center",
        ).pack(pady=(10, 0))

    def _build_progress_and_stats(self) -> None:
        wrap = ttk.Frame(self.body, padding=(PAD_OUT, 0, PAD_OUT, 8))
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
        wrap = ttk.Labelframe(self.body, text=" Activity log ", padding=10)
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

    def _pick_dir_into(self, var: tk.StringVar) -> None:
        """Generic folder picker — writes the chosen path into `var`."""
        chosen = filedialog.askdirectory(initialdir=var.get() or str(Path.home()))
        if chosen:
            var.set(chosen)

    def _pick_cookies(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Select cookies JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=str(Path.home()),
        )
        if chosen:
            self.cookies_var.set(chosen)

    def _show_cookie_help(self) -> None:
        """Explain how to export a TikTok cookies JSON the scraper accepts."""
        messagebox.showinfo(
            "Cách lấy cookie TikTok",
            "Cookie chỉ cần cho TikTok — trang tìm kiếm (/search), hoặc để tải "
            "hơn ~28 video (giới hạn khi CHƯA đăng nhập).\n\n"
            "Các bước (dùng tiện ích trình duyệt Cookie-Editor):\n"
            "1. Cài extension \"Cookie-Editor\" (Chrome / Edge / Firefox).\n"
            "2. Mở tiktok.com và ĐĂNG NHẬP tài khoản.\n"
            "3. Bấm icon Cookie-Editor → nút Export → chọn định dạng \"JSON\" "
            "(KHÔNG chọn 'Header String').\n"
            "4. Dán vào một file mới, lưu tên ví dụ  tiktok-cookies.json\n"
            "5. Quay lại app, bấm Browse… ở ô Cookies và chọn file đó.\n\n"
            "Cũng chấp nhận file storage_state của Playwright "
            "({\"cookies\": [...]}).\n"
            "Lưu ý: cookie hết hạn theo thời gian — nếu bị chặn, export lại file mới."
        )

    def _first_run_marker(self) -> Path:
        return Path.home() / ".video-download" / "onboarded"

    def _maybe_first_run_tour(self) -> None:
        """Show the tour once, on the very first launch. Marker survives restarts."""
        marker = self._first_run_marker()
        if marker.exists():
            return
        self._show_welcome()
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("1", encoding="utf-8")
        except OSError:
            pass  # non-fatal — worst case the tour shows again next launch

    # Detailed guide content: list of (text, tag). Tags: "h1" title, "h2" section
    # header, "b" bold sub-item, "" normal body.
    _GUIDE = [
        ("VIDEO DOWNLOAD — HƯỚNG DẪN SỬ DỤNG", "h1"),
        ("Tải video hàng loạt về một thư mục trên máy. Đọc 1 lần là dùng được.", ""),
        ("2 tab ở trên cùng", "h2"),
        ("• Download — tải video từ một đường link (URL).", ""),
        ("• Watermark folder — đóng chữ chạy lên các video .mp4 CÓ SẴN trong một "
         "thư mục (không tải gì, chỉ xử lý video bạn đã có).", ""),
        ("Tải video — 3 bước tối thiểu", "h2"),
        ("1) Dán link vào ô URL.  2) Chọn thư mục lưu ở Output.  3) Bấm START.", ""),
        ("Nguồn hỗ trợ (dán vào ô URL)", "h2"),
        ("• TikTok — trang nhạc (…/music/…), trang hashtag (…/tag/…) hoặc trang "
         "tìm kiếm (…/search?q=…).", ""),
        ("• Facebook — trang Ads Library (…/ads/library?…).", ""),
        ("• Google Drive — link folder chia sẻ (tải mọi .mp4 trong folder đó).", ""),
        ("Link khác sẽ bị báo lỗi ngay khi bấm START.", ""),
        ("Các ô trong Options", "h2"),
        ("• Output — thư mục lưu video. Bấm Browse… để chọn.", ""),
        ("• Max videos — số video tối đa muốn tải (1–2000, mặc định 100).", ""),
        ("• Delay (s) — nghỉ mấy giây giữa mỗi video. Để 2. Hay bị chặn thì tăng 3–5.", ""),
        ("• Passes — số lần quét lại trang (chỉ TikTok). TikTok mỗi lần trả về một "
         "phần video ngẫu nhiên; quét 2–3 lần gom được nhiều hơn. Trên 3 dễ bị chặn.", ""),
        ("• Proxy — để TRỐNG. Chỉ điền nếu bạn có proxy riêng.", ""),
        ("• Cookies — CHỈ dùng cho TikTok. Xem nút “Cách lấy cookie”.", ""),
        ("3 ô tick — có nên tick không?", "h2"),
        ("☐ Show browser (headful) — mặc định TẮT.", "b"),
        ("   Hiện cửa sổ trình duyệt lúc quét. Bình thường để TẮT (chạy ẩn, nhanh). "
         "BẬT khi bị bắt giải captcha / bị chặn: cửa sổ hiện ra cho bạn giải bằng "
         "tay rồi app chạy tiếp.", ""),
        ("☑ Keep session — NÊN ĐỂ BẬT (mặc định bật).", "b"),
        ("   Ghi nhớ phiên đăng nhập/cookies giữa các lần chạy → TikTok thấy “người "
         "quen” nên ít bắt captcha, ít giới hạn hơn. Chỉ tắt nếu muốn chạy sạch hoàn toàn.", ""),
        ("☐ Verbose log — thường KHÔNG cần.", "b"),
        ("   Ghi log chi tiết để soi lỗi. Chỉ bật khi cần gửi log cho người hỗ trợ "
         "kỹ thuật; bình thường để tắt cho log gọn.", ""),
        ("Cookies (chỉ TikTok)", "h2"),
        ("Chỉ cần khi tải trang /search, hoặc để tải HƠN ~28 video (giới hạn khi "
         "chưa đăng nhập). Facebook và Google Drive KHÔNG cần. Bấm nút “Cách lấy "
         "cookie” cạnh ô Cookies để xem các bước lấy file.", ""),
        ("Watermark (tuỳ chọn — đóng chữ chạy lên video)", "h2"),
        ("• Tick “Apply watermark to downloads” để bật.", ""),
        ("• Animated text — chữ muốn hiển thị (tên bạn / thương hiệu). Bỏ trống = "
         "không đóng chữ.", ""),
        ("• Pattern — kiểu chuyển động của chữ (xoay vòng, số 8, lắc ngang, trượt "
         "chéo, xoắn ốc, hoặc đứng yên giữa video).", ""),
        ("• Opacity % — độ mờ của chữ (35 = mờ nhẹ, 100 = rõ đặc).", ""),
        ("• Quality — HD/FullHD ép khung hình về kích thước chuẩn (chữ luôn cân đối); "
         "chọn “original” để giữ nguyên.", ""),
        ("Bản này chỉ có watermark CHỮ (đã bỏ logo tĩnh và icon động).", ""),
        ("Lần đầu chạy", "h2"),
        ("Bấm START lần đầu, app tự tải trình duyệt Chromium (~150MB, chỉ 1 lần). "
         "Chờ trạng thái báo sẵn sàng rồi việc tải bắt đầu.", ""),
        ("⚠ Lần đầu tải hay lỗi vài video (TikTok khởi động). ĐỪNG LO — cứ bấm "
         "START lại: app tự bỏ qua video đã tải và lấy nốt phần còn thiếu. Chạy "
         "lại 1–2 lần là đủ 100%.", "b"),
        ("Kết quả", "h2"),
        ("Video lưu dạng <mã>.mp4 trong thư mục Output. Chạy lại cùng link sẽ TỰ BỎ "
         "QUA video đã có — an toàn khi dừng giữa chừng rồi chạy tiếp.", ""),
        ("Mở lại hướng dẫn này bất cứ lúc nào bằng nút “❔ Hướng dẫn” ở góc trên.", ""),
    ]

    def _show_welcome(self) -> None:
        """Detailed, scrollable guide window (used by first-run tour + the button)."""
        # If already open, just bring it to front instead of stacking copies.
        existing = getattr(self, "_help_win", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        win = tk.Toplevel(self.root)
        self._help_win = win
        win.title("Hướng dẫn sử dụng — Video Download")
        win.geometry("720x640")
        win.minsize(520, 400)
        win.configure(bg=BG_WINDOW)
        win.transient(self.root)

        wrap = tk.Frame(win, bg=BG_WINDOW)
        wrap.pack(fill="both", expand=True, padx=0, pady=0)

        sb = ttk.Scrollbar(wrap, orient="vertical")
        sb.pack(side="right", fill="y")
        txt = tk.Text(
            wrap, wrap="word", bg=BG_WINDOW, fg=TEXT, bd=0,
            padx=22, pady=18, spacing1=2, spacing3=6,
            font=("Helvetica", 13), yscrollcommand=sb.set, cursor="arrow",
        )
        txt.pack(side="left", fill="both", expand=True)
        sb.config(command=txt.yview)

        txt.tag_configure("h1", font=("Helvetica", 17, "bold"), foreground=ACCENT,
                           spacing1=4, spacing3=12)
        txt.tag_configure("h2", font=("Helvetica", 14, "bold"), foreground=TEXT,
                           spacing1=14, spacing3=6)
        txt.tag_configure("b", font=("Helvetica", 13, "bold"), foreground=TEXT)
        txt.tag_configure("", foreground=TEXT_DIM)

        for line, tag in self._GUIDE:
            txt.insert("end", line + "\n", tag)
        txt.config(state="disabled")

        btnbar = tk.Frame(win, bg=BG_SURFACE)
        btnbar.pack(fill="x")
        ttk.Button(btnbar, text="Đã hiểu", command=win.destroy,
                   style="Primary.TButton").pack(side="right", padx=14, pady=10)

    def _build_watermark_config(self) -> WatermarkConfig | None:
        """Read watermark UI fields into a WatermarkConfig, or None if disabled."""
        if not self.wm_enable_var.get():
            return None
        # Clamp opacity to [5, 100] in case user typed an out-of-range value into
        # the spinbox; convert to 0..1 float for the dataclass.
        op_pct = max(5, min(100, int(self.wm_opacity_var.get() or 35)))
        return WatermarkConfig(
            animated_text=self.wm_text_var.get().strip() or None,
            text_pattern=_pattern_key(self.wm_text_pattern_var.get()),
            output_quality=self.wm_quality_var.get() or "original",
            opacity=op_pct / 100,
        )

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
        if self.worker and self.worker.is_alive():
            return

        active_tab = self.notebook.index(self.notebook.select())
        if active_tab == 1:
            # Watermark-folder mode — validate paths then run.
            src = self.folder_src_var.get().strip()
            out = self.folder_out_var.get().strip()
            if not src or not Path(src).is_dir():
                self._append_log("ERROR: Source folder is empty or doesn't exist")
                return
            if not out:
                self._append_log("ERROR: Output folder is required")
                return
            if Path(src).resolve() == Path(out).resolve():
                self._append_log(
                    "ERROR: Source and Output must be different folders"
                )
                return
            self._attach_logger()
            self._reset_stats()
            # Progress max is computed in the worker once the file list is known.
            self.progress.config(value=0, maximum=1)
            self._update_progress_label()
            self.start_btn.config(state="disabled", text="Working…")
            self.status_pill.set("Working")
            self.worker = threading.Thread(
                target=self._run_folder_pipeline,
                args=(src, out, self.folder_recursive_var.get()),
                daemon=True,
            )
            self.worker.start()
            return

        # Download mode (tab 0) — URL-driven pipeline.
        url = self.url_var.get().strip()
        if not (is_tiktok_collection(url) or is_fb_ads_library(url)
                or is_gdrive_folder(url)):
            self._append_log(
                "ERROR: URL must be TikTok /music/, /tag/<hashtag>, /search?q=…, "
                "Facebook /ads/library/, or a Google Drive folder share link"
            )
            return
        if is_search_page(url) and not self.cookies_var.get().strip():
            self._append_log(
                "⚠ Search page usually needs Cookies (logged-in TikTok session). "
                "Anonymous attempts often return 0 videos."
            )
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
            # Google Drive folder — no scraper, no yt-dlp; gdown pulls files
            # directly into the output dir, then we watermark them in place.
            if is_gdrive_folder(url):
                self._run_gdrive_pipeline(url)
                return

            # "Keep session" persists Playwright profile under the user's app-support
            # dir — both TikTok and FB then see a returning client across runs.
            profile_dir: str | None = None
            if self.keep_session_var.get():
                p = (Path.home() / "Library" / "Application Support"
                     / "tiktok-music-downloader" / "playwright-profile")
                profile_dir = str(p)

            if is_fb_ads_library(url):
                # FB is more rate-aggressive than TikTok; default cap is lower
                # and we do a single pass (no multi-visit — FB notices that).
                refs = scrape_ads_library(
                    url,
                    max_videos=self.max_var.get(),
                    headless=not self.headful_var.get(),
                    proxy=self.proxy_var.get().strip() or None,
                    profile_dir=profile_dir,
                )
            else:
                # /music/, /tag/ and /search?q= all reuse scrape_music_page_multi
                # — the scraper is generic (any TikTok page with
                # `a[href*=/video/]` cards). Search additionally tends to need
                # cookies for results to render, which the user is warned about
                # in _start().
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
                # Page type is known here, not in the response handler.
                if is_tag_page(url) or is_search_page(url):
                    self.log_queue.put(
                        "no videos found — nếu phía trên có cảnh báo feed rỗng "
                        "thì server không trả item nào cho loại trang này "
                        "(trang /music/ dùng endpoint khác, có thể vẫn chạy). "
                        "KHÔNG có cảnh báo thì chưa chắc là server ổn: nó chỉ "
                        "có nghĩa mấy endpoint bản này canh đều không rỗng — "
                        "thử bật Show browser / thêm Cookie"
                    )
                else:
                    self.log_queue.put(
                        "no videos found — thử bật Show browser (headful) "
                        "hoặc thêm Cookie"
                    )
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
                watermark=self._build_watermark_config(),
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

    def _run_gdrive_pipeline(self, url: str) -> None:
        """Download a public Drive folder, then watermark each mp4 in place."""
        import re as _re
        import time as _time
        from tiktok_music_downloader.watermark import apply_watermark
        from tiktok_music_downloader.gdrive import iter_mp4s_under
        try:
            # gdown sets the output folder's mtime when it finishes — macOS
            # blocks that on directories with extended attrs (Downloads/, etc.
            # carry com.apple.quarantine). Always drop into a fresh subfolder
            # we own to side-step the EPERM. Subfolder name derives from the
            # Drive folder ID for stability across runs.
            m = _re.search(r"folders/([\w\-]+)", url)
            sub = f"drive-{m.group(1)[:12] if m else int(_time.time())}"
            out_dir = Path(self.out_var.get()) / sub
            out_dir.mkdir(parents=True, exist_ok=True)
            self.log_queue.put(("status", "Downloading"))
            self.log_queue.put(f"Drive: pulling folder → {out_dir}")
            downloaded_files = gdrive_download_folder(url, out_dir)
            # Only mp4s are watermark targets; gdown may have pulled non-video
            # files (thumbnails, srt, etc.) — those stay on disk untouched.
            mp4s = [p for p in downloaded_files if p.suffix.lower() == ".mp4"]
            # Fallback: if gdown returned no list, rescan output recursively.
            if not mp4s:
                mp4s = iter_mp4s_under(out_dir)
            total = len(mp4s)
            self.log_queue.put(f"Drive: {total} mp4 file(s) ready")
            if total == 0:
                self.log_queue.put("no mp4 files in this Drive folder")
                self.log_queue.put(("status", "Done"))
                return

            self.log_queue.put(("stat_set", ("scraped", total)))
            self.log_queue.put(("max", total))

            cfg = self._build_watermark_config()
            processed = skipped = 0
            failed: list[str] = []
            progress = UiProgress(self.log_queue)

            for f in mp4s:
                try:
                    if cfg is not None and not cfg.is_empty:
                        ok = apply_watermark(f, cfg)
                        if not ok:
                            self.log_queue.put(f"⚠ watermark failed for {f.name}")
                    processed += 1
                    progress.note("downloaded")
                    self.log_queue.put(f"✓ {f.name}")
                except Exception as exc:  # noqa: BLE001
                    failed.append(f.name)
                    progress.note("failed")
                    self.log_queue.put(f"✗ {f.name}: {exc}")
                finally:
                    progress.update(1)

            self.log_queue.put(
                f"DONE — watermarked={processed} skipped={skipped} failed={len(failed)}"
            )
            self.log_queue.put(("status", "Done"))
        except Exception as exc:  # noqa: BLE001
            self.log_queue.put(f"ERROR: {exc}")
            self.log_queue.put(("status", "Error"))
        finally:
            self.log_queue.put(("enable_start", None))

    def _run_folder_pipeline(self, src: str, out: str, recursive: bool) -> None:
        """Watermark-only worker — walks `src` and applies overlays into `out`."""
        try:
            src_path = Path(src)
            out_path = Path(out)
            files = iter_mp4s(src_path, recursive)
            total = len(files)
            self.log_queue.put(f"Found {total} mp4 file(s) in {src_path}"
                               + (" (recursive)" if recursive else ""))
            if total == 0:
                self.log_queue.put(("status", "Done"))
                return
            self.log_queue.put(("stat_set", ("scraped", total)))
            self.log_queue.put(("max", total))

            processed, skipped, failed = watermark_folder(
                src_path, out_path, self._build_watermark_config() or WatermarkConfig(),
                recursive=recursive,
                progress=UiProgress(self.log_queue),
            )
            self.log_queue.put(
                f"DONE — watermarked={processed} skipped={skipped} failed={len(failed)}"
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
            # First-run TikTok cold-start often fails a few — nudge to re-run.
            if self.stats.get("failed", 0) > 0:
                self._append_log(
                    f"⚠ {self.stats['failed']} video bị lỗi — cứ bấm START LẠI để "
                    "lấy nốt (app tự bỏ qua video đã tải). Lần đầu hay bị vậy, "
                    "chạy lại 1–2 lần là đủ."
                )
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
