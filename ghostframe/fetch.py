"""Resolve the input (URL or local file) to a video file on disk."""

from __future__ import annotations

import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
_QUIET = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True}


@dataclass
class Source:
    path: Path
    title: str
    id: str
    url: str | None = None  # original URL, if the input was one
    duration: float | None = None
    downloaded: bool = False  # True if we own the file and may delete it
    info: dict = field(default_factory=dict, repr=False)  # yt-dlp metadata, incl. caption tracks


def is_url(s: str) -> bool:
    return urlparse(s).scheme in ("http", "https")


def is_youtube(url: str) -> bool:
    return urlparse(url).hostname in YOUTUBE_HOSTS


def youtube_at(url: str | None, t: float) -> str | None:
    """Link that opens a YouTube video at `t` seconds; None for non-YouTube sources."""
    if not url or not is_youtube(url):
        return None
    return f"{url}{'&' if '?' in url else '?'}t={int(t)}s"


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_")[:60] or "video"


def resolve(inp: str, workdir: Path, max_height: int) -> Source:
    if not is_url(inp):
        p = Path(inp).expanduser()
        if not p.is_file():
            raise SystemExit(f"ghostframe: no such file: {inp}")
        return Source(path=p, title=p.stem, id=slug(p.stem))
    if not is_youtube(inp):
        raise SystemExit("ghostframe: only YouTube URLs are supported so far (or pass a local video file)")
    return _download(inp, workdir, max_height)


def _download(url: str, workdir: Path, max_height: int) -> Source:
    import yt_dlp

    if not shutil.which("deno"):
        print("ghostframe: tip: install deno (winget install DenoLand.Deno) - "
              "without a JS runtime YouTube throttles yt-dlp downloads", file=sys.stderr)
    workdir.mkdir(parents=True, exist_ok=True)
    opts = {
        **_QUIET,
        # Video-only is enough for frames and avoids needing ffmpeg to merge streams.
        # Prefer H.264: AV1/VP9 decode several times slower during scene detection.
        "format": "/".join([
            f"bv*[height<={max_height}][vcodec^=avc1]",
            f"bv*[height<={max_height}]",
            f"b[height<={max_height}]",
            "b",
        ]),
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(info["requested_downloads"][0]["filepath"])
    return Source(
        path=path,
        title=info.get("title") or info["id"],
        id=info["id"],
        url=info.get("webpage_url") or url,
        duration=info.get("duration"),
        downloaded=True,
        info=info,
    )


def download_audio(url: str, workdir: Path) -> Path:
    """Audio-only download for Whisper; the main download is video-only."""
    import yt_dlp

    workdir.mkdir(parents=True, exist_ok=True)
    opts = {**_QUIET, "format": "ba[abr<=160]/ba/b", "outtmpl": str(workdir / "%(id)s.audio.%(ext)s")}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return Path(info["requested_downloads"][0]["filepath"])
