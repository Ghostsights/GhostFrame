"""ghostframe: video link -> timestamped contact sheet."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from ghostframe import __version__, fetch, frames, sheet, transcript


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="ghostframe",
        description="Download a video, keep one frame per scene, and render a timestamped contact sheet.",
    )
    p.add_argument("input", help="YouTube URL or path to a local video file")
    p.add_argument("-o", "--out", type=Path, help="output directory (default: ./ghostframe_out/<video id>)")
    p.add_argument("-n", "--budget", type=int, default=24, help="max frames on the sheet (default: 24)")
    p.add_argument("--threshold", type=float, default=0.3,
                   help="ffmpeg scene-change score 0-1; lower = more cuts detected (default: 0.3)")
    p.add_argument("--dedupe", type=int, default=6,
                   help="drop frames within this many dHash bits (0-64) of a kept frame; 0 disables (default: 6)")
    p.add_argument("--cols", type=int, default=4, help="contact sheet columns (default: 4)")
    p.add_argument("--width", type=int, default=480, help="thumbnail width in px (default: 480)")
    p.add_argument("--max-height", type=int, default=480, help="max download resolution (default: 480)")
    p.add_argument("--keep-video", action="store_true", help="keep the downloaded video file")
    t = p.add_argument_group("transcript (YouTube captions first, local Whisper if there are none)")
    t.add_argument("--no-transcript", action="store_true", help="skip transcript.md")
    t.add_argument("--whisper", action="store_true", help="use Whisper even if captions exist")
    t.add_argument("--whisper-model", default="base",
                   help="faster-whisper model: tiny, base, small, medium, large-v3 (default: base)")
    t.add_argument("--lang", help="transcript language code, e.g. en (default: the video's own language)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args(argv)


def log(msg: str) -> None:
    print(f"ghostframe: {msg}", file=sys.stderr, flush=True)


def make_transcript(args: argparse.Namespace, src: fetch.Source, final: list, out: Path, dl_dir: Path) -> Path:
    t, note = None, None
    if not args.whisper and src.info:
        t = transcript.from_youtube(src.info, args.lang)
        if t:
            log(f"transcript from {t.label}")
    if not t:
        if not transcript.whisper_available():
            note = ("No captions available and Whisper is not installed. "
                    "Install it with: py -m pip install --user faster-whisper")
            log(note)
        else:
            log("no captions; falling back to Whisper" if not args.whisper else "using Whisper")
            media = fetch.download_audio(src.url, dl_dir) if src.downloaded else src.path
            t = transcript.from_whisper(media, args.whisper_model, args.lang, log)
            if not t.cues:
                note = "Whisper found no speech in this video."
    return transcript.write_markdown(out / "transcript.md", t, src.title, src.url, final, note)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.budget < 1:
        raise SystemExit("ghostframe: --budget must be >= 1")

    tmp_root = Path(args.out or "ghostframe_out")
    dl_dir = tmp_root / "_download"
    try:
        return run(args, tmp_root, dl_dir)
    finally:  # also on failure, so a crash doesn't strand a downloaded video
        if fetch.is_url(args.input) and not args.keep_video:
            shutil.rmtree(dl_dir, ignore_errors=True)


def run(args: argparse.Namespace, tmp_root: Path, dl_dir: Path) -> int:
    log(f"resolving {args.input}")
    src = fetch.resolve(args.input, dl_dir, args.max_height)
    out = args.out or tmp_root / fetch.slug(src.id)
    out.mkdir(parents=True, exist_ok=True)

    duration = src.duration or frames.probe_duration(src.path)
    work = out / "_work"
    shutil.rmtree(work, ignore_errors=True)

    log(f"detecting scene changes (threshold {args.threshold})")
    found = frames.scene_frames(src.path, work, args.threshold, args.width)

    # Talking heads and screen recordings have few hard cuts: top up with evenly spaced frames.
    if len(found) < args.budget // 2 and duration:
        every = max(duration / args.budget, 1.0)
        log(f"only {len(found)} scene changes; adding a frame every {every:.1f}s")
        found += frames.interval_frames(src.path, work, every, args.width)

    kept = frames.dedupe(found, args.dedupe if args.dedupe > 0 else -1)
    if not kept:  # every frame was blank; show something rather than nothing
        kept = sorted(found, key=lambda f: f.t)[:1]
    final = frames.cap(kept, args.budget)
    log(f"{len(found)} candidates -> {len(kept)} after dedupe -> {len(final)} on sheet")

    # Move the chosen frames somewhere stable, named by timestamp.
    frame_dir = out / "frames"
    shutil.rmtree(frame_dir, ignore_errors=True)
    frame_dir.mkdir()
    for i, f in enumerate(final, 1):
        dest = frame_dir / f"{i:03d}_{sheet.fmt_ts(f.t).replace(':', '-')}.jpg"
        shutil.move(f.path, dest)
        f.path = dest
    shutil.rmtree(work, ignore_errors=True)

    subtitle = " · ".join(filter(None, [
        src.url or str(src.path),
        f"duration {sheet.fmt_ts(duration)}" if duration else None,
        f"{len(final)} frames",
    ]))
    sheet_path = sheet.render(final, out / "contact_sheet.png", src.title, subtitle, args.cols, args.width)
    transcript_path = None if args.no_transcript else make_transcript(args, src, final, out, dl_dir)

    manifest = {
        "title": src.title,
        "source": src.url or str(src.path.resolve()),
        "duration": duration,
        "contact_sheet": str(sheet_path.resolve()),
        "transcript": str(transcript_path.resolve()) if transcript_path else None,
        "frames": [
            {"index": i, "time": round(f.t, 2), "timestamp": sheet.fmt_ts(f.t),
             "file": str(f.path.resolve()), "link": fetch.youtube_at(src.url, f.t)}
            for i, f in enumerate(final, 1)
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    log("done")
    print(sheet_path.resolve())  # stdout carries only the result path, for scripting
    return 0
