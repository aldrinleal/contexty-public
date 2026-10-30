"""Minimal WebVTT/SRT parser.

yt-dlp can download subtitle/caption tracks the source already publishes
(mainly YouTube — manual or auto-generated) without needing AssemblyAI at
all. This turns whatever it downloads into a flat list of timestamped
``Cue``s good enough for ``transcript.md`` — small enough not to justify an
extra dependency.
"""

import re
from dataclasses import dataclass
from pathlib import Path

_TIMESTAMP_RE = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})")
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Cue:
    start_ms: int
    text: str


def _parse_timestamp(raw: str) -> int:
    match = _TIMESTAMP_RE.search(raw)
    if not match:
        raise ValueError(f"unrecognized timestamp: {raw!r}")
    hours, minutes, seconds, millis = match.groups()
    return ((int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)) * 1000) + int(
        millis
    )


def parse_subtitle_file(path: Path) -> list[Cue]:
    """Parses a .vtt or .srt file into a de-duplicated, chronological cue list.

    Auto-generated YouTube VTT files use rolling/karaoke-style cues where each
    entry repeats the previous one plus a new word — we collapse those chains
    into a single cue (first start time, final/longest text) instead of
    emitting every intermediate fragment.
    """
    content = path.read_text(encoding="utf-8", errors="replace")

    raw: list[tuple[int, str]] = []
    for block in re.split(r"\n\s*\n", content):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        ts_line = next((line for line in lines if "-->" in line), None)
        if ts_line is None:
            continue
        try:
            start_ms = _parse_timestamp(ts_line.split("-->")[0].strip())
        except ValueError:
            continue

        text_lines = lines[lines.index(ts_line) + 1 :]
        text = " ".join(_TAG_RE.sub("", line).strip() for line in text_lines).strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            raw.append((start_ms, text))

    cues: list[Cue] = []
    for start_ms, text in raw:
        if cues and text.startswith(cues[-1].text):
            cues[-1].text = (
                text  # rolling caption grew — keep original start, extend text
            )
        elif cues and (cues[-1].text.startswith(text) or cues[-1].text == text):
            continue  # shorter/duplicate fragment of what we already have
        else:
            cues.append(Cue(start_ms=start_ms, text=text))

    return cues
