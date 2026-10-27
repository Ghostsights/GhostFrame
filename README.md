# ghostframe

Video link in, timestamped contact sheet out.

```
py -m pip install --user -e .
py -m ghostframe "https://youtu.be/dQw4w9WgXcQ"
```

Pipeline: yt-dlp download (≤480p, H.264 preferred, video only) → ffmpeg scene-change
detection (topped up with evenly spaced frames when a video has few cuts) → drop blank
and near-duplicate frames (dHash) → cap to `--budget` frames spread across the timeline →
`contact_sheet.png` + `manifest.json` + `frames/`.

`transcript.md` comes from YouTube captions when the video has them (human captions
first, then auto-generated captions in the video's own language, never YouTube's
machine translations). Otherwise, and always for local files, it's transcribed locally
with [faster-whisper](https://github.com/SYSTRAN/faster-whisper), an optional extra:

```
py -m pip install --user -e ".[whisper]"
```

Paragraphs are ~30s, each headed by a timestamp and the contact-sheet frames it covers.

ffmpeg comes bundled via `imageio-ffmpeg`; a system `ffmpeg` on PATH is used if present.
Installing [deno](https://deno.com) avoids YouTube throttling yt-dlp's downloads.

Supported now: YouTube URLs and local video files. Not yet: Instagram.

`SKILL.md` is the Claude Code skill; copy it to `~/.claude/skills/ghostframe/SKILL.md`.
Run `py -m ghostframe --help` for all options.
