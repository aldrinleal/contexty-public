"""Builds the Markdown (+ metadata.json) files that go into data-[ID]/."""

import json
from datetime import datetime, timezone
from typing import Any

from app.extractor import Metadata
from app.subtitles import Cue


def _fmt_timestamp(ms: int) -> str:
    total_s = ms // 1000
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def build_transcript_md(metadata: Metadata, transcript: Any) -> str:
    """transcript is an assemblyai.Transcript — speaker-labeled if diarization was on."""
    lines = [f"# Transcrição — {metadata.title}", ""]

    utterances = getattr(transcript, "utterances", None)
    if utterances:
        for utterance in utterances:
            ts = _fmt_timestamp(utterance.start)
            lines.append(f"**[{ts}] Speaker {utterance.speaker}:** {utterance.text}")
            lines.append("")
    else:
        lines.append(transcript.text or "_(transcrição vazia)_")

    return "\n".join(lines)


def build_transcript_md_from_subtitles(
    metadata: Metadata, cues: list[Cue], is_auto_generated: bool
) -> str:
    """Built from a yt-dlp-downloaded subtitle track — no speaker diarization."""
    source_note = "legenda automática" if is_auto_generated else "legenda original"
    lines = [
        f"# Transcrição — {metadata.title}",
        "",
        f"_(via {source_note} do yt-dlp — sem diarização de falantes)_",
        "",
    ]

    if cues:
        lines.extend(f"**[{_fmt_timestamp(cue.start_ms)}]** {cue.text}" for cue in cues)
    else:
        lines.append("_(transcrição vazia)_")

    return "\n".join(lines)


def build_metadata_md(
    metadata: Metadata,
    transcript_source: str,
    transcript_id: str | None,
    language: str | None,
    keep_audio: bool,
    keep_video: bool,
) -> str:
    source_label = (
        "legenda nativa (yt-dlp)"
        if transcript_source == "native_subtitles"
        else "AssemblyAI"
    )
    lines = [
        f"# Metadata — {metadata.title}",
        "",
        f"- **ID**: `{metadata.id}`",
        f"- **Fonte**: {metadata.source_url}",
        f"- **Extractor (yt-dlp)**: {metadata.extractor}",
        f"- **Uploader**: {metadata.uploader or '_desconhecido_'}",
        f"- **Duração**: {metadata.duration_s if metadata.duration_s is not None else '?'}s",
        f"- **Data de publicação**: {metadata.upload_date or '?'}",
        f"- **Fonte da transcrição**: {source_label}",
    ]
    if transcript_id:
        lines.append(f"- **AssemblyAI transcript id**: `{transcript_id}`")
    lines.extend(
        [
            f"- **Idioma**: {language or '?'}",
            f"- **Áudio mantido (audio.*)**: {'sim' if keep_audio else 'não'}",
            f"- **Vídeo mantido (video.*)**: {'sim' if keep_video else 'não'}",
            f"- **Processado em**: {datetime.now(timezone.utc).isoformat()}",
        ]
    )
    lines.extend(["", "## Descrição", "", metadata.description or "_(sem descrição)_"])
    return "\n".join(lines) + "\n"


def build_metadata_json(
    metadata: Metadata,
    transcript_source: str,
    transcript_id: str | None,
    language: str | None,
    keep_audio: bool,
    keep_video: bool,
    filenames: list[str],
    transcript_text: str,
    summary_chars: int = 500,
) -> str:
    """Machine-readable twin of metadata.md, for programmatic lookup later
    (`GET /jobs/{id}` already returns the sqlite row, but this travels with
    the files themselves — local disk and S3 both).

    `summary` is a naive whitespace-collapsed excerpt of the transcript, not
    an LLM-generated abstract — there's no summarization step in the
    pipeline (yet). Good enough to preview/grep without opening
    transcript.md; say so explicitly so nobody mistakes it for more.
    """
    collapsed = " ".join(transcript_text.split())
    truncated = len(collapsed) > summary_chars
    summary = collapsed[:summary_chars].strip()
    if truncated:
        summary += "…"

    payload = {
        "id": metadata.id,
        "source_url": metadata.source_url,
        "title": metadata.title,
        "uploader": metadata.uploader,
        "description": metadata.description,
        "duration_s": metadata.duration_s,
        "upload_date": metadata.upload_date,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "files": sorted(filenames),
        "transcript_source": transcript_source,
        "transcript_id": transcript_id,
        "language": language,
        "keep_audio": keep_audio,
        "keep_video": keep_video,
        "summary": summary,
        "summary_is_ai_generated": False,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def build_readme_md(metadata: Metadata, filenames: list[str]) -> str:
    lines = [
        f"# data-{metadata.id}",
        "",
        f"Gerado por [contexty](.) a partir de: {metadata.source_url}",
        "",
        "## Arquivos",
        "",
    ]
    lines.extend(f"- `{name}`" for name in sorted(filenames))
    return "\n".join(lines) + "\n"
