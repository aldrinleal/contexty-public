"""The whole contexty pipeline, as one blocking function.

Replaces the old Step Functions split (Submit/CheckStatus/Finalize/
MarkFailed as separate Lambda invocations) — now that this runs as a
long-lived server instead of Lambda, there's no 15-minute-per-invocation
timeout forcing that split, so it's just a normal function again.

Callers (main.py's CLI, app/api.py's POST /jobs) are responsible for
resolving metadata and claiming the dedup guard *before* calling
run_pipeline() — that split lets the API return a job id/duplicate-or-not
answer immediately, handing only the (potentially slow) download+transcribe
work to a background thread, without resolving/claiming twice.
"""

import logging
import tempfile
import time
from pathlib import Path
from typing import Any

from app import jobstore
from app.config import settings
from app.extractor import Metadata, download_audio, download_subtitles, download_video
from app.formatter import (
    build_metadata_json,
    build_metadata_md,
    build_readme_md,
    build_transcript_md,
    build_transcript_md_from_subtitles,
)
from app.output import write_output
from app.s3sync import s3_prefix, sync_to_s3
from app.subtitles import parse_subtitle_file
from app.transcriber import TranscriberError, check_status, fetch_transcript
from app.transcriber import submit as submit_transcript

logger = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    """Raised (after jobstore.mark_failed) on any failure past the claim step."""


def run_pipeline(
    metadata: Metadata,
    source: str,
    keep_audio: bool = False,
    keep_video: bool = False,
    language: str | None = None,
    prefer_native_subtitles: bool | None = None,
) -> dict[str, Any]:
    """Downloads/transcribes/writes for an already-resolved+claimed job.

    Returns {"id", "data_dir", "transcript_source"} on success.
    Raises PipelineError on failure (after recording it via jobstore.mark_failed).
    """
    prefer_native = (
        settings.prefer_native_subtitles
        if prefer_native_subtitles is None
        else prefer_native_subtitles
    )

    try:
        written_files: list[str] = []
        cues = None
        is_auto = False
        subtitle_language = None
        transcript_id = None

        with tempfile.TemporaryDirectory(prefix=f"contexty-{metadata.id}-") as tmp:
            workdir = Path(tmp)

            subtitle_path = None
            if prefer_native:
                subtitle_path, is_auto, subtitle_language = download_subtitles(
                    source, workdir, language
                )

            # Audio is only strictly needed when there's no subtitle track to
            # fall back on — but download it anyway if asked to keep it.
            need_audio = keep_audio or subtitle_path is None
            audio_path = download_audio(source, workdir) if need_audio else None

            if keep_audio and audio_path is not None:
                write_output(
                    settings.output_dir, metadata.id, {audio_path.name: audio_path}
                )
                written_files.append(audio_path.name)

            if keep_video:
                video_path = download_video(source, workdir)
                write_output(
                    settings.output_dir, metadata.id, {video_path.name: video_path}
                )
                written_files.append(video_path.name)

            if subtitle_path is not None:
                cues = parse_subtitle_file(subtitle_path)
                transcript_source = "native_subtitles"
            else:
                assert (
                    audio_path is not None
                )  # need_audio was True whenever subtitle_path is None
                transcript_id = submit_transcript(audio_path, language=language)
                transcript_source = "assemblyai"
        # tempdir (and any downloaded audio/video) is gone from here on — the
        # AssemblyAI wait below can take minutes and doesn't need it anymore.

        if transcript_source == "native_subtitles":
            resolved_transcript_id = None
            resolved_language = subtitle_language
            transcript_text = " ".join(cue.text for cue in (cues or []))
            transcript_md = build_transcript_md_from_subtitles(
                metadata, cues or [], is_auto
            )
            metadata_md = build_metadata_md(
                metadata,
                transcript_source,
                resolved_transcript_id,
                resolved_language,
                keep_audio,
                keep_video,
            )
        else:
            assert (
                transcript_id is not None
            )  # set above whenever transcript_source == "assemblyai"
            status = check_status(transcript_id)
            while status not in ("completed", "error"):
                logger.info(
                    "job %s: AssemblyAI status=%s — waiting %ss",
                    metadata.id,
                    status,
                    settings.poll_interval_s,
                )
                time.sleep(settings.poll_interval_s)
                status = check_status(transcript_id)
            if status == "error":
                raise TranscriberError(
                    f"AssemblyAI transcription failed for {transcript_id}"
                )
            transcript = fetch_transcript(transcript_id)
            resolved_transcript_id = transcript.id
            resolved_language = getattr(transcript, "language_code", None)
            transcript_text = transcript.text or ""
            transcript_md = build_transcript_md(metadata, transcript)
            metadata_md = build_metadata_md(
                metadata,
                transcript_source,
                resolved_transcript_id,
                resolved_language,
                keep_audio,
                keep_video,
            )

        readme_names = written_files + [
            "transcript.md",
            "metadata.md",
            "metadata.json",
            "README.md",
        ]
        metadata_json = build_metadata_json(
            metadata,
            transcript_source,
            resolved_transcript_id,
            resolved_language,
            keep_audio,
            keep_video,
            readme_names,
            transcript_text,
        )
        readme_md = build_readme_md(metadata, readme_names)
        data_dir = write_output(
            settings.output_dir,
            metadata.id,
            {
                "transcript.md": transcript_md,
                "metadata.md": metadata_md,
                "metadata.json": metadata_json,
                "README.md": readme_md,
            },
        )

        s3_uri = None
        if settings.enable_s3_sync:
            s3_uri = s3_prefix(metadata.id)
            sync_to_s3(data_dir, s3_uri)

        if settings.enable_history_guard:
            jobstore.mark_completed(
                metadata.id, transcript_source, str(data_dir), s3_uri
            )

        logger.info("job %s: done -> %s", metadata.id, data_dir)
        return {
            "id": metadata.id,
            "data_dir": str(data_dir),
            "transcript_source": transcript_source,
            "s3_uri": s3_uri,
        }
    except Exception as exc:
        logger.exception("job %s: pipeline failed", metadata.id)
        if settings.enable_history_guard:
            jobstore.mark_failed(metadata.id, str(exc))
        raise PipelineError(str(exc)) from exc
