---
name: ghostframe
description: Watch a video by turning it into a timestamped contact sheet of its distinct scenes. Use whenever the user shares a YouTube link (youtube.com/watch, youtu.be, youtube.com/shorts) or a local video file path (.mp4, .mov, .mkv, .webm), or asks what happens in, what is shown in, or to summarize/review/describe a video - even if they don't ask you to "look" at it. Not yet for Instagram or other sites.
---

# ghostframe

`ghostframe` downloads a video, keeps one frame per scene change, drops near-duplicate
and blank frames, caps the result at a frame budget, and renders a single contact sheet
PNG with a `#index  m:ss` badge on every frame. It also writes `transcript.md` from
YouTube's captions, or from local Whisper when the video has none. Reading the sheet plus
the transcript is how you "watch" the video.

## Run it

```bash
py -m ghostframe "<youtube-url-or-video-path>" -o "<scratch-dir>/ghostframe/<short-name>"
```

- On macOS/Linux use `python3 -m ghostframe` (and `python3` in the other commands below).
  Always quote the URL.
- Put output in your scratchpad directory (or wherever the user asks), not the project.
- Downloads take ~30-60s for a few-minute video; run in the background for anything
  over ~10 minutes long.
- stdout is just the contact sheet path; progress goes to stderr.

Useful flags:

| Flag | Default | When to change |
|---|---|---|
| `-n/--budget` | 24 | Raise to 36-48 for long videos or when the user asks about a specific moment; lower to ~12 for a quick gist. |
| `--threshold` | 0.3 | Lower (0.15-0.2) for slides/screen recordings with subtle changes; raise (0.4+) for fast-cut edits. |
| `--dedupe` | 6 | Lower to keep more similar frames (e.g. code changing line by line); 0 disables. |
| `--cols` | 4 | 3 for portrait/Shorts video so frames stay legible. |
| `--keep-video` | off | Keep the download if you'll re-run with different settings. |
| `--lang` | video's language | Only when the user wants a transcript in a specific language. |
| `--whisper` | off | Only if the captions are clearly wrong or garbled; captions are preferred. |
| `--whisper-model` | base | `small` for better accuracy (slower); `tiny` for very long videos. |
| `--no-transcript` | off | When the user only cares about visuals. |

Whisper runs on CPU and only kicks in when there are no captions (and always for local
files). It processes roughly 5-10x faster than real time with `base`, so run anything
over ~10 minutes in the background.

If the user wants a closer look at part of a video, re-run with a higher budget and lower
threshold rather than guessing between frames.

## Read the results

The output directory contains:

- `contact_sheet.png` - **Read this image.** Frames are in time order, left to right,
  top to bottom.
- `transcript.md` - **Read this too.** ~30s paragraphs, each headed by a timestamp (a
  link to that moment for YouTube) and the contact-sheet frames that fall in it, e.g.
  `**[1:09](...)** · frames #10–#11`. Use those to tie what is said to what is shown.
  The header line says where the text came from: human captions, auto-generated
  captions, or Whisper.
- `manifest.json` - per frame: `index`, `timestamp`, `file` (full-size JPEG) and, for
  YouTube, a `link` that opens the video at that moment.
- `frames/` - the individual frames, if a detail on the sheet is too small to make out.

## Answer

- Describe what the frames actually show. Cite moments as `[m:ss](link)` using the
  manifest links so the user can jump straight there.
- The sheet is a sample, not the full video: say "around 1:16" rather than claiming an
  exact cut, and say so if something the user asks about may fall between frames.
- Quote speech only from `transcript.md`. Auto-generated captions and Whisper both
  mishear words (especially names and jargon); when a word looks wrong, say it may be a
  transcription error rather than repeating it as fact.
- If `transcript.md` says no transcript is available, say so; don't infer dialogue
  from the frames.

## If it fails

- `only YouTube URLs are supported so far` - Instagram/other hosts aren't supported yet;
  tell the user, or ask them to download the file and pass the local path.
- `No module named ghostframe` - install it: `py -m pip install --user -e <path to the ghostframe repo>`.
- `Whisper is not installed` (in transcript.md) - the sheet is still fine. Tell the user
  they can enable it with `py -m pip install --user faster-whisper`; don't install it yourself.
- Slow downloads print a tip about `deno`; pass it on to the user once, don't install it yourself.
- Age-restricted, private or members-only videos fail in yt-dlp; tell the user rather than retrying.
