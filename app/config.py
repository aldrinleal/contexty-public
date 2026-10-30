"""App-wide settings, loaded from environment variables (and a local .env in dev).

Uses the ``Settings(BaseSettings)`` singleton pattern: one class, one module-level instance,
imported everywhere as ``from app.config import settings``.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # AssemblyAI. No CONTEXTY_ prefix — this is the name AssemblyAI's own docs
    # use, so it's the one people reach for by habit.
    assemblyai_api_key: str = Field(default="", validation_alias="ASSEMBLYAI_API_KEY")

    # Root directory under which data-[ID]/ folders are created.
    # Local CLI: defaults to the current directory.
    # API/k8s: set to a mounted volume path (e.g. /data) via the ConfigMap
    # so output survives container restarts.
    output_dir: Path = Field(default=Path("."), validation_alias="CONTEXTY_OUTPUT_DIR")

    # sqlite file backing app/jobstore.py (dedup guard + job history). Lives
    # alongside output_dir by default so both persist on the same volume.
    db_path: Path = Field(
        default=Path("contexty.db"), validation_alias="CONTEXTY_DB_PATH"
    )

    # Bearer token required on every app/api.py request except /healthz.
    # No default — the API refuses to start without one (see app/api.py).
    api_token: str = Field(default="", validation_alias="CONTEXTY_API_TOKEN")

    # uvicorn bind host/port — only read by main.py/local dev; the
    # Containerfile's CMD hardcodes 0.0.0.0:8000 for the deployed image.
    host: str = Field(default="0.0.0.0", validation_alias="CONTEXTY_HOST")
    port: int = Field(default=8000, validation_alias="CONTEXTY_PORT")

    # Thread pool size for background job execution (app/api.py). Each slot
    # is one concurrently-running yt-dlp/ffmpeg/AssemblyAI pipeline.
    max_workers: int = Field(default=2, validation_alias="CONTEXTY_MAX_WORKERS")

    # Toggle the dedup-guard/history writes — set to false for pure-local
    # dev/testing without wanting a contexty.db file created.
    enable_history_guard: bool = Field(
        default=True, validation_alias="CONTEXTY_ENABLE_HISTORY_GUARD"
    )

    # Every completed job's data-[ID]/ dir is synced to
    # s3://{s3_bucket}/data/{id}/ via `aws s3 sync` (app/s3sync.py), in
    # addition to staying on the local/hostPath volume. Needs
    # AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY/AWS_DEFAULT_REGION in the
    # environment (ideally credentials scoped to only this
    # bucket). Off by default — set CONTEXTY_ENABLE_S3_SYNC=true to use it.
    s3_bucket: str = Field(
        default="example-contexty-bucket", validation_alias="CONTEXTY_S3_BUCKET"
    )
    enable_s3_sync: bool = Field(
        default=False, validation_alias="CONTEXTY_ENABLE_S3_SYNC"
    )
    s3_sync_timeout_s: int = Field(
        default=180, validation_alias="CONTEXTY_S3_SYNC_TIMEOUT_S"
    )

    # Container yt-dlp/ffmpeg extracts audio to (must be an AssemblyAI-supported format).
    ytdlp_audio_format: str = Field(
        default="m4a", validation_alias="CONTEXTY_YTDLP_AUDIO_FORMAT"
    )

    # Caps the audio-only track yt-dlp picks for download_audio() to this
    # bitrate (kbps) or lower, falling back to bestaudio/best if nothing
    # matches. Speech transcription doesn't need the source's highest-
    # fidelity audio track — capping this cuts download/upload size and
    # time (sometimes by 2x+ on sources with a high-bitrate audio-only
    # track) with no meaningful accuracy cost. None/0 disables the cap.
    ytdlp_audio_max_abr_kbps: int | None = Field(
        default=128, validation_alias="CONTEXTY_YTDLP_AUDIO_MAX_ABR_KBPS"
    )

    # Force a transcript language (ISO 639-1). None => AssemblyAI auto-detect.
    transcript_language: str | None = Field(
        default=None, validation_alias="CONTEXTY_TRANSCRIPT_LANGUAGE"
    )

    # Enable AssemblyAI speaker diarization by default.
    diarization: bool = Field(default=True, validation_alias="CONTEXTY_DIARIZATION")

    # Try the source's own subtitles/captions (via yt-dlp) before falling back
    # to AssemblyAI. Saves the AssemblyAI job entirely when subs already exist
    # (common on YouTube) — at the cost of no speaker diarization for that path.
    prefer_native_subtitles: bool = Field(
        default=True, validation_alias="CONTEXTY_PREFER_NATIVE_SUBTITLES"
    )

    # Timeout (seconds) applied to every yt-dlp/ffmpeg/ffprobe subprocess call.
    ffmpeg_timeout_s: int = Field(
        default=120, validation_alias="CONTEXTY_FFMPEG_TIMEOUT_S"
    )

    # Netscape-format cookies.txt for yt-dlp's `cookiefile` option — the only
    # cookie mechanism that works on the deployed server (a headless
    # container with no browser of its own). Refreshed via PUT /cookies
    # (app/api.py) or scripts/upload-cookies.sh; points at the persistent
    # /data volume so it survives container restarts.
    cookies_file: Path | None = Field(
        default=None, validation_alias="CONTEXTY_COOKIES_FILE"
    )

    # Browser name (chrome/firefox/edge/brave/safari/...) for yt-dlp's
    # `cookiesfrombrowser` option — only meaningful for the local CLI
    # (main.py --cookies-from-browser), which runs on a machine with a real
    # browser profile to read. No-op on the deployed server. Wins over
    # cookies_file when both are set (see app/extractor.py::_cookie_opts()).
    cookies_from_browser: str | None = Field(
        default=None, validation_alias="CONTEXTY_COOKIES_FROM_BROWSER"
    )

    # How often (seconds) the pipeline's internal poll loop checks AssemblyAI.
    poll_interval_s: int = Field(
        default=30, validation_alias="CONTEXTY_POLL_INTERVAL_S"
    )


settings = Settings()
