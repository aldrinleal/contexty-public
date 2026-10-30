"""AssemblyAI wrapper.

Uses ``Transcriber().submit()`` (non-blocking — returns as soon as the job is
queued) rather than ``.transcribe()`` (which blocks polling internally and
could run past a Lambda's timeout on long media). The Step Functions state
machine does the waiting via its own Wait/CheckStatus/Choice loop; the CLI's
local pipeline does its own simple poll loop around these same functions.

The audio file is uploaded straight to AssemblyAI by the SDK — no S3
bucket/presigned URL needed for the source audio itself.
"""

import logging
from pathlib import Path

import assemblyai as aai

from app.config import settings

logger = logging.getLogger(__name__)

aai.settings.api_key = settings.assemblyai_api_key


class TranscriberError(RuntimeError):
    """Raised when AssemblyAI reports a failed transcription."""


def submit(
    audio_path: Path, language: str | None = None, diarization: bool = True
) -> str:
    """Submits a transcription job and returns its transcript_id immediately."""
    language = language or settings.transcript_language
    config = aai.TranscriptionConfig(
        speaker_labels=diarization,
        language_code=language,
        language_detection=language is None,
    )
    transcript = aai.Transcriber().submit(str(audio_path), config=config)
    logger.info("submitted transcript job %s for %s", transcript.id, audio_path)
    return transcript.id


def check_status(transcript_id: str) -> str:
    """Returns AssemblyAI's status string: queued | processing | completed | error.

    Must be `.value`, not `str(transcript.status)` — TranscriptStatus is a
    (str, Enum) mixin, but its __str__ still renders "TranscriptStatus.completed"
    rather than the plain value, which silently breaks every status comparison
    in the poll loop (main.py / EvaluateStatus) — always falls through to the
    "keep waiting" branch, and the AssemblyAI path never terminates.
    """
    transcript = aai.Transcript.get_by_id(transcript_id)
    return str(transcript.status.value)


def fetch_transcript(transcript_id: str) -> aai.Transcript:
    """Fetches the completed transcript. Raises TranscriberError if the job errored."""
    transcript = aai.Transcript.get_by_id(transcript_id)
    if transcript.status == aai.TranscriptStatus.error:
        raise TranscriberError(transcript.error or f"transcript {transcript_id} failed")
    return transcript
