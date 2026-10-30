---
name: video-summary
description: Fetches a video's transcript via contexty, writes a Markdown summary with metadata and the links from the video description, and sends it to Joplin (by email or via a Joplin MCP server). Use when the user asks to summarize a video, generate a video summary, send a transcript to Joplin, or process a video. Triggers: summarize this video, video summary, summarize video, send to joplin, process this video, generate a video summary.
---

# Video Summary — Contexty → Markdown → Joplin

Pipeline: video URL → contexty (transcript) → Markdown summary → Joplin.

## Configuration

Values come from the environment — never hardcode tokens in this file or
echo them back to the user.

```bash
CONTEXTY_BASE=http://localhost:8000   # wherever your contexty API runs
CONTEXTY_TOKEN=<your CONTEXTY_API_TOKEN>
```

## 1. Submit the video to contexty

```bash
curl -s -X POST "$CONTEXTY_BASE/jobs" \
  -H "Authorization: Bearer $CONTEXTY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source": "<URL or ID>"}'
```

Returns `{id, title, duplicate, status_url}`. If `duplicate: true`, skip to
step 3.

## 2. Wait for completion

Poll `GET $CONTEXTY_BASE/jobs/{id}` until `status` is `completed` or `error`.

```bash
curl -s "$CONTEXTY_BASE/jobs/<ID>" -H "Authorization: Bearer $CONTEXTY_TOKEN"
```

Interval: 30s. Timeout: 10 min.

## 3. Fetch the generated files

```bash
# Transcript
curl -s "$CONTEXTY_BASE/jobs/<ID>/files/transcript.md" -H "Authorization: Bearer $CONTEXTY_TOKEN"

# Metadata
curl -s "$CONTEXTY_BASE/jobs/<ID>/files/metadata.md" -H "Authorization: Bearer $CONTEXTY_TOKEN"
```

## 4. Write the Markdown summary

From `transcript.md`, produce a structured summary:

````markdown
# [Video Title]

## Metadata
```json
{ ... job metadata or metadata.md ... }
```

## Summary

[Summary of the video's main content — key points, main ideas, topics
covered. Do NOT paste the whole transcript.]

## Links from the Description

- [Link text](URL)
- ...
````

Rules:
- The note title (or email subject) is the video title.
- Put the metadata JSON at the top of the Markdown.
- Extract and list the links from the description/metadata (channels, social
  networks, tools mentioned, etc.).
- Write the summary in the **same language as the video** (from the
  metadata's language field or the content itself). Only change the
  language if the user explicitly asks.

## 5. VALIDATE before sending

Before sending anything, **confirm** the summary is correct:

1. The summary file exists and has real content (not empty, not a
   placeholder).
2. It has at least the title and the summary body.
3. If the content is incomplete or looks wrong, **do NOT send** — tell the
   user.

```bash
if [ ! -s "$SUMMARY_FILE" ] || [ "$(wc -c < "$SUMMARY_FILE")" -lt 100 ]; then
  echo "ERROR: summary empty or too short, aborting"
  exit 1
fi
# Unresolved shell substitutions mean the content was never expanded
grep -q '\$(cat ' "$SUMMARY_FILE" && echo "ERROR: contains a literal \$(cat ...) — do not send" && exit 1
head -20 "$SUMMARY_FILE"  # preview for the user to confirm
```

## 6. Send to Joplin

Send the summary to Joplin using whichever is available:

- **Email** — Joplin Cloud's email-to-note address (subject = video title,
  body = the Markdown summary).
- **Joplin MCP server** — create a note with the video title as its title
  and the Markdown summary as its body.

When building a JSON payload, read the summary file into a variable first
and let `jq` do the escaping — never put a literal `$(cat ...)` inside a
JSON string, or the note arrives with the command text instead of the
content.

## Typical workflow (batch of N videos)

1. Submit all videos via `POST /jobs` in sequence.
2. Wait for them to finish (poll, or check back later).
3. For each: fetch transcript + metadata → write summary → send to Joplin.
4. Notify the user when done.
