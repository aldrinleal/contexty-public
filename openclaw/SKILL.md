---
name: contexty
description: Downloads and transcribes videos (YouTube and anything else yt-dlp supports) via a contexty server, producing a Markdown transcript. Also checks job status, lists job history and fetches generated files. Use when the user asks to transcribe a video, get a video's transcript, query contexty, list contexty jobs, see transcription history, or fetch the transcript of a specific video. Triggers: contexty, transcribe this video, get the transcript, video transcript, grab the transcript, video context, list jobs, transcription history, process this video.
---

# Contexty — Video → Markdown Transcript

Downloads a video, extracts its audio and produces a Markdown transcript —
from the video's own subtitles when available, otherwise via AssemblyAI
(with speaker diarization). Result: a `data-[ID]/` folder with
`transcript.md`, `metadata.md`, `metadata.json`, `README.md` and optionally
`audio.m4a`/`video.mp4`.

## Configuration

Both values come from the environment — never hardcode the token in this
file or echo it back to the user.

```bash
CONTEXTY_BASE=http://localhost:8000   # wherever your contexty API runs (`make api` / `make container-run`)
CONTEXTY_TOKEN=<your CONTEXTY_API_TOKEN>
```

## API

### Submit a video

```bash
curl -s -X POST "$CONTEXTY_BASE/jobs" \
  -H "Authorization: Bearer $CONTEXTY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source": "<URL or ID>", "keep_audio": false, "language": "<ISO 639-1, optional>"}'
```

Returns 202 with `{id, title, duplicate, status_url}`. `duplicate: true`
means it was already processed in the last 24h — skip straight to fetching.

### Check a job's status

```bash
curl -s "$CONTEXTY_BASE/jobs/<ID>" -H "Authorization: Bearer $CONTEXTY_TOKEN"
```

Status: `processing` → `completed` or `error`. Includes `transcript_source`
(`native_subtitles` or `assemblyai`).

### List recent jobs

```bash
curl -s "$CONTEXTY_BASE/jobs?limit=50" -H "Authorization: Bearer $CONTEXTY_TOKEN"
```

### Fetch a generated file

```bash
curl -s "$CONTEXTY_BASE/jobs/<ID>/files/transcript.md" -H "Authorization: Bearer $CONTEXTY_TOKEN"
curl -s "$CONTEXTY_BASE/jobs/<ID>/files/metadata.md" -H "Authorization: Bearer $CONTEXTY_TOKEN"
```

Available files: `transcript.md`, `metadata.md`, `metadata.json`,
`README.md`, `audio.m4a` (if `keep_audio: true`), `video.mp4` (if
`keep_video: true`).

## Local CLI (alternative)

When processing locally instead of through the API, from a checkout of
this repository:

```bash
pipenv run python main.py "<URL>" [--keep-audio] [--keep-video] [--language pt] [--force-assemblyai]
```

Writes `data-[ID]/` to the current directory.

## Typical workflow

1. Submit via the API (`POST /jobs`) — returns 202 immediately.
2. Wait for processing (transcription can take minutes).
3. Poll `GET /jobs/<ID>` until `status: completed` (or `error`).
4. Fetch the transcript with `GET /jobs/<ID>/files/transcript.md`.

For long videos, submit first and check the status in a later step rather
than blocking on it.

## Important details

- **24h dedup**: the same video isn't reprocessed within 24 hours.
- **Native subtitles first**: tries the source's own subtitles before
  spending an AssemblyAI transcription. If found, uses them directly (no
  diarization, but instant and free).
- **Diarization**: on by default on the AssemblyAI path.
- **Any URL yt-dlp supports** works, not just YouTube.
- Bare IDs (e.g. `dQw4w9WgXcQ`) are treated as YouTube videos.
