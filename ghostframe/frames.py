"""Scene-change frame extraction, near-duplicate removal and budget capping."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageStat

_PTS = re.compile(r"\[Parsed_showinfo.*?pts_time:\s*([\d.]+)")
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):([\d.]+)")


@dataclass
class Frame:
    path: Path
    t: float  # seconds from start
    hash: int = 0


def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(args: list[str]) -> str:
    proc = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-nostdin", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-8:])
        raise SystemExit(f"ghostframe: ffmpeg failed:\n{tail}")
    return proc.stderr


def probe_duration(video: Path) -> float | None:
    # `ffmpeg -i` with no output exits non-zero but still prints the header.
    proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(video)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = _DURATION.search(proc.stderr)
    if not m:
        return None
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


def _extract(video: Path, outdir: Path, prefix: str, select: str, width: int) -> list[Frame]:
    outdir.mkdir(parents=True, exist_ok=True)
    pattern = outdir / f"{prefix}_%05d.jpg"
    # Scale first so scene scoring runs on small frames (much faster on HD video).
    vf = f"scale={width}:-2,select='{select}',showinfo"
    stderr = _run(["-i", str(video), "-an", "-vf", vf, "-fps_mode", "vfr", "-q:v", "3", str(pattern)])
    times = [float(t) for t in _PTS.findall(stderr)]
    files = sorted(outdir.glob(f"{prefix}_*.jpg"))
    return [Frame(path=f, t=t) for f, t in zip(files, times)]


def scene_frames(video: Path, outdir: Path, threshold: float, width: int) -> list[Frame]:
    """First frame plus every frame whose scene-change score exceeds `threshold`."""
    return _extract(video, outdir, "scene", f"eq(n\\,0)+gt(scene\\,{threshold})", width)


def interval_frames(video: Path, outdir: Path, every: float, width: int) -> list[Frame]:
    """One frame every `every` seconds - fallback for videos with few hard cuts."""
    return _extract(video, outdir, "tick", f"isnan(prev_selected_t)+gte(t-prev_selected_t\\,{every})", width)


def dhash(path: Path, size: int = 8) -> int:
    img = Image.open(path).convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    px = list(img.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            left = px[row * (size + 1) + col]
            right = px[row * (size + 1) + col + 1]
            bits = (bits << 1) | (left > right)
    return bits


def is_blank(path: Path, min_stddev: float = 6.0) -> bool:
    """Near-uniform frames: black intros, fade-outs, solid title cards with no text."""
    return ImageStat.Stat(Image.open(path).convert("L")).stddev[0] < min_stddev


def dedupe(frames: list[Frame], max_distance: int) -> list[Frame]:
    """Drop blank frames and frames whose dHash is within `max_distance` bits of any already-kept frame."""
    kept: list[Frame] = []
    for f in sorted(frames, key=lambda f: f.t):
        if is_blank(f.path):
            continue
        f.hash = dhash(f.path)
        if all(bin(f.hash ^ k.hash).count("1") > max_distance for k in kept):
            kept.append(f)
    return kept


def cap(frames: list[Frame], budget: int) -> list[Frame]:
    """Keep at most `budget` frames, spread evenly across the timeline."""
    if len(frames) <= budget:
        return frames
    if budget == 1:
        return frames[:1]
    step = (len(frames) - 1) / (budget - 1)
    return [frames[round(i * step)] for i in range(budget)]
