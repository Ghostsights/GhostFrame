"""Transcripts: YouTube captions when they exist, local Whisper otherwise, rendered to markdown."""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import warnings
from dataclasses import dataclass
from pathlib import Path

from ghostframe.fetch import youtube_at
from ghostframe.frames import Frame, ffmpeg_exe
from ghostframe.sheet import fmt_ts


@dataclass
class Cue:
    start: float
    text: str


@dataclass
class Transcript:
    cues: list[Cue]
    label: str  # human-readable origin, e.g. "YouTube captions (manual, en)"


# --- YouTube captions ---------------------------------------------------------

def _lang_match(key: str, lang: str) -> bool:
    return key == lang or key.split("-")[0] == lang.split("-")[0]


def pick_track(info: dict, lang: str | None) -> tuple[str, str, list[dict]] | None:
    """Choose (kind, key, formats). Human captions beat ASR; ASR in the spoken
    language beats YouTube's machine-translated auto tracks."""
    manual = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat"}
    auto = info.get("automatic_captions") or {}
    want = lang or info.get("language") or "en"

    for key, fmts in manual.items():
        if _lang_match(key, want):
            return "manual", key, fmts
    # "<lang>-orig" is the ASR of the original audio; plain keys may be translations.
    for key in (f"{want}-orig", want):
        if key in auto:
            return "auto", key, auto[key]
    if not lang and manual:  # no preference given: any human captions beat Whisper
        key = next(iter(manual))
        return "manual", key, manual[key]
    return None


def _parse_json3(raw: str) -> list[Cue]:
    cues = []
    for ev in json.loads(raw).get("events", []):
        text = "".join(s.get("utf8", "") for s in ev.get("segs") or [])
        text = " ".join(text.split())
        if text:
            cues.append(Cue(ev.get("tStartMs", 0) / 1000, text))
    return cues


_VTT_TIME = re.compile(r"(?:(\d+):)?(\d+):(\d+)\.(\d+)\s+-->")
_TAG = re.compile(r"<[^>]+>")


def _parse_vtt(raw: str) -> list[Cue]:
    cues: list[Cue] = []
    prev_lines: set[str] = set()
    for block in re.split(r"\n\s*\n", raw.replace("\r\n", "\n")):
        lines = block.strip().split("\n")
        idx = next((i for i, l in enumerate(lines) if _VTT_TIME.search(l)), None)
        if idx is None:
            continue
        h, m, s, ms = _VTT_TIME.search(lines[idx]).groups()
        start = int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
        text_lines = [html.unescape(_TAG.sub("", l)).strip() for l in lines[idx + 1:]]
        text_lines = [l for l in text_lines if l]
        # Auto-caption VTT repeats the previous line in each cue ("rolling" captions).
        new = [l for l in text_lines if l not in prev_lines]
        prev_lines = set(text_lines)
        if new:
            cues.append(Cue(start, " ".join(new)))
    return cues


def from_youtube(info: dict, lang: str | None) -> Transcript | None:
    track = pick_track(info, lang)
    if not track:
        return None
    kind, key, fmts = track
    by_ext = {f["ext"]: f for f in fmts}
    fmt = by_ext.get("json3") or by_ext.get("vtt")
    if not fmt:
        return None

    import yt_dlp

    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        get = lambda u: ydl.urlopen(u).read().decode("utf-8", errors="replace")  # noqa: E731
        raw = get(fmt["url"])
        # Some tracks are served as an HLS playlist of caption segments rather than the file itself.
        if raw.startswith("#EXTM3U"):
            segs = [l.strip() for l in raw.splitlines() if l.strip() and not l.startswith("#")]
            raw = "\n\n".join(get(s) for s in segs)
    cues = _parse_json3(raw) if fmt["ext"] == "json3" else _parse_vtt(raw)
    if not cues:
        return None
    what = "captions" if kind == "manual" else "auto-generated captions"
    return Transcript(cues, f"YouTube {what} ({key.removesuffix('-orig')})")


# --- Whisper fallback -----------------------------------------------------------

def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def _load_audio(media: Path):
    """16 kHz mono float32, decoded with our ffmpeg rather than faster-whisper's PyAV,
    whose API drifts between versions."""
    import numpy as np

    proc = subprocess.run(
        [ffmpeg_exe(), "-nostdin", "-loglevel", "error", "-i", str(media),
         "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"ghostframe: could not decode audio: {proc.stderr.decode(errors='replace').strip()}")
    return np.frombuffer(proc.stdout, np.int16).astype(np.float32) / 32768.0


def from_whisper(media: Path, model_name: str, lang: str | None, log) -> Transcript:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")
    warnings.filterwarnings("ignore", module="huggingface_hub")
    from faster_whisper import WhisperModel

    log(f"loading Whisper '{model_name}' (first run downloads the model)")
    model = WhisperModel(model_name, device="auto", compute_type="int8")
    audio = _load_audio(media)
    if audio.size == 0:
        return Transcript([], f"Whisper `{model_name}`, run locally")
    segments, info = model.transcribe(audio, language=lang, vad_filter=True)
    log(f"transcribing {fmt_ts(info.duration)} of audio (language: {info.language})")
    cues, next_report = [], 60.0
    for seg in segments:  # a generator: transcription happens while iterating
        if seg.text.strip():
            cues.append(Cue(seg.start, seg.text.strip()))
        if seg.end >= next_report:
            log(f"  ...{fmt_ts(seg.end)} / {fmt_ts(info.duration)}")
            next_report += 60
    return Transcript(cues, f"Whisper `{model_name}`, run locally (language: {info.language})")


# --- Markdown -----------------------------------------------------------------

def paragraphs(cues: list[Cue], target: float = 30.0, hard_max: float = 45.0, gap: float = 4.0) -> list[list[Cue]]:
    """Group cues into ~30s paragraphs, preferring sentence ends and pauses as breaks."""
    paras: list[list[Cue]] = []
    cur: list[Cue] = []
    for cue in cues:
        if cur:
            span = cue.start - cur[0].start
            paused = cue.start - cur[-1].start > gap and span >= 8
            sentence_end = cur[-1].text.rstrip().endswith((".", "?", "!", "]", "♪"))
            if span >= hard_max or (span >= target and sentence_end) or paused:
                paras.append(cur)
                cur = []
        cur.append(cue)
    if cur:
        paras.append(cur)
    return paras


def _frame_refs(nums: list[int]) -> str:
    if not nums:
        return ""
    if len(nums) == 1:
        return f" · frame #{nums[0]}"
    return f" · frames #{nums[0]}–#{nums[-1]}"


def write_markdown(out: Path, t: Transcript | None, title: str, url: str | None,
                   frames: list[Frame], note: str | None = None) -> Path:
    lines = [f"# {title}", ""]
    if url:
        lines.append(f"- Source: {url}")
    lines.append(f"- Transcript: {t.label if t else 'none'}")
    lines.append("- Frames: `contact_sheet.png` (frame numbers below refer to its #badges)")
    lines += ["", "---", ""]

    if not t or not t.cues:
        lines.append(f"_{note or 'No transcript available.'}_")
    else:
        paras = paragraphs(t.cues)
        starts = [p[0].start for p in paras]
        owners: dict[int, list[int]] = {}
        for n, f in enumerate(frames, 1):
            i = max((k for k, s in enumerate(starts) if s <= f.t), default=0)
            owners.setdefault(i, []).append(n)
        for i, para in enumerate(paras):
            ts = fmt_ts(para[0].start)
            link = youtube_at(url, para[0].start)
            head = f"[{ts}]({link})" if link else ts
            lines.append(f"**{head}**{_frame_refs(owners.get(i, []))}  ")
            lines.append(" ".join(c.text for c in para))
            lines.append("")

    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return out
