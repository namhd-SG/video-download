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
    is_tiktok_collection,
    setup_logger,
)

app = typer.Typer(
    add_completion=False,
    help="Download all watermark-free MP4 videos from a TikTok music, search, or profile page.",
)


@app.command()
def main(
    music_url: str = typer.Argument(..., help="TikTok music, search, or profile (/@user) URL"),
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
    """Scrape music page, then download every video as MP4 (no watermark)."""
    log = setup_logger(verbose)

    if not is_tiktok_collection(music_url):
        typer.secho(
            "URL doesn't look like a TikTok /music/, /search?q=…, or /@profile page",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)

    if (is_search_page(music_url) or is_profile_page(music_url)) and not cookies:
        typer.secho(
            "⚠ Search/profile pages usually need --cookies (logged-in TikTok "
            "session) to load all videos; anonymous runs often return few or 0.",
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
        typer.secho("No video URLs found. Try --headful or --cookies.", fg=typer.colors.YELLOW, err=True)
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
