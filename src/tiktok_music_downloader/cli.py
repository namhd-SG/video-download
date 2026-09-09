"""CLI entry: `tiktok-music-dl <music_url> --output <dir> --max <N>`."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from tqdm import tqdm

from tiktok_music_downloader.downloader import download_all
from tiktok_music_downloader.scraper import scrape_music_page
from tiktok_music_downloader.utils import (
    is_profile_page,
    is_search_page,
    is_tag_page,
    is_tiktok_collection,
    setup_logger,
)

app = typer.Typer(
    add_completion=False,
    help="Download all watermark-free MP4 videos from a TikTok music, hashtag, search, or profile page.",
)


@app.command()
def main(
    music_url: str = typer.Argument(
        ..., help="TikTok page URL: /music/…, /tag/<hashtag>, /search?q=…, or /@profile"
    ),
    output: Path = typer.Option(Path("./downloads"), "--output", "-o", help="Output directory"),
    max_videos: int = typer.Option(200, "--max", "-n", min=1, max=2000, help="Max videos"),
    delay: float = typer.Option(2.0, "--delay", "-d", min=0.0, help="Base seconds between downloads (jittered)"),
    scroll_pause: float = typer.Option(1.5, "--scroll-pause", min=0.5, help="Seconds between scrolls"),
    idle_rounds: int = typer.Option(4, "--idle-rounds", min=1, help="Stop after N idle scroll rounds"),
    headful: bool = typer.Option(False, "--headful", help="Show browser window (debug)"),
    cookies: Optional[Path] = typer.Option(None, "--cookies", help="Playwright cookies JSON"),
    proxy: Optional[str] = typer.Option(None, "--proxy", help="HTTP proxy, e.g. http://user:pass@host:port"),
    profile_dir: Optional[Path] = typer.Option(
        None, "--profile-dir", help="Persistent Playwright user-data dir (keeps cookies across runs)"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging"),
) -> None:
    """Scrape the page, then download every video as MP4 (no watermark)."""
    log = setup_logger(verbose)

    if not is_tiktok_collection(music_url):
        typer.secho(
            "URL doesn't look like a TikTok /music/, /tag/, /search, or "
            "/@profile page",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    # The GUI has warned about this since search support landed; the CLI never
    # did, so a cookie-less search/profile run just ended in "no videos found".
    if (is_search_page(music_url) or is_profile_page(music_url)) and not cookies:
        typer.secho(
            "Search and profile pages usually need --cookies (a logged-in "
            "TikTok session); anonymous attempts often return 0 videos.",
            fg=typer.colors.YELLOW,
            err=True,
        )

    refs = scrape_music_page(
        music_url,
        max_videos=max_videos,
        headless=not headful,
        scroll_pause=scroll_pause,
        idle_rounds=idle_rounds,
        cookies_path=str(cookies) if cookies else None,
        proxy=proxy,
        profile_dir=str(profile_dir) if profile_dir else None,
    )

    if not refs:
        # Only this layer knows the page type, so the page-specific hint lives
        # here rather than in the response handler (which also sees /music/).
        if is_tag_page(music_url) or is_search_page(music_url):
            hint = (
                "No video URLs found. An empty-feed warning above means the "
                "server returned no items for this page type, and a /music/ "
                "page may still work. No warning is not an all-clear: it only "
                "means none of the feed endpoints this build watches came back "
                "empty. Run with --verbose to see every /api/ response, or try "
                "--headful or --cookies."
            )
        else:
            hint = "No video URLs found. Try --headful or --cookies."
        typer.secho(hint, fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=1)

    log.info("downloading %d videos → %s", len(refs), output)
    with tqdm(total=len(refs), unit="vid", desc="download") as bar:
        downloaded, skipped, failed = download_all(
            refs, output, delay_seconds=delay, proxy=proxy, progress=bar
        )

    typer.echo("")
    typer.secho(f"  downloaded: {downloaded}", fg=typer.colors.GREEN)
    typer.secho(f"  skipped:    {skipped}", fg=typer.colors.CYAN)
    typer.secho(f"  failed:     {len(failed)}", fg=typer.colors.RED if failed else typer.colors.GREEN)
    if failed:
        typer.echo("  failed ids: " + ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    app()
