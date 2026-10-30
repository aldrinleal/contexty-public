"""Publishes a local data-[ID]/ directory to S3 via the `aws s3 sync` CLI
rather than hand-rolling
per-object PutObject calls with boto3.

Runs once per job, after the whole pipeline (subtitles/audio/video/
transcript/metadata) has already finished writing everything to the local
volume — there's no longer a reason to split this into two sync calls like
the old Lambda-per-stage design needed, since app/pipeline.py runs start to
finish in one background thread now.
"""

import logging
import subprocess
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


class S3SyncError(RuntimeError):
    """Raised when `aws s3 sync` fails or the awscli isn't available."""


def s3_prefix(id_: str) -> str:
    return f"s3://{settings.s3_bucket}/data/{id_}/"


def sync_to_s3(local_dir: Path, s3_uri: str) -> None:
    try:
        subprocess.run(
            ["aws", "s3", "sync", str(local_dir), s3_uri, "--only-show-errors"],
            capture_output=True,
            text=True,
            timeout=settings.s3_sync_timeout_s,
            check=True,
        )
    except FileNotFoundError as exc:
        raise S3SyncError("aws CLI not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise S3SyncError(
            f"aws s3 sync failed ({local_dir} -> {s3_uri}): {exc.stderr}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise S3SyncError(
            f"aws s3 sync timed out after {settings.s3_sync_timeout_s}s ({local_dir} -> {s3_uri})"
        ) from exc

    logger.info("synced %s -> %s", local_dir, s3_uri)
