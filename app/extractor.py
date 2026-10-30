"""yt-dlp + ffmpeg/ffprobe wrapper.

Callers are expected to create the working directory themselves (e.g. via
``tempfile.TemporaryDirectory()`` in ``/tmp``) and pass it in — this module
never creates or cleans up its own temp dirs, so the caller controls the
lifetime of downloaded files.

Subprocess pattern (ffprobe validation): explicit timeout on every external
call, ffprobe run in JSON mode, exceptions handled per type
(``FileNotFoundError`` = binary missing, ``CalledProcessError`` = process
failed, ``TimeoutExpired`` = hung).
"""

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from app.config import settings

logger = logging.getLogger(__name__)


class ExtractorError(RuntimeError):
    """Raised when yt-dlp/ffmpeg/ffprobe fails to produce usable media."""


@dataclass
class Metadata:
    id: str
    title: str
    uploader: str | None
    source_url: str
    duration_s: float | None
    upload_date: str | None  # yt-dlp's raw YYYYMMDD string, or None
    extractor: str
    description: str | None = None  # default keeps old Metadata(...) call sites valid


def _normalize_source(source: str) -> str:
    """Bare IDs with no scheme are assumed to be YouTube video IDs."""
    if "://" not in source:
        return f"https://www.youtube.com/watch?v={source}"
    return source


def _cookie_opts() -> dict:
    """yt-dlp cookie options, if configured — see app/config.py's docstrings.

    cookiesfrombrowser (local CLI, real browser profile on disk) wins over
    cookiefile (server, exported cookies.txt) when both are somehow set —
    they're mutually-exclusive use contexts in practice.
    """
    if settings.cookies_from_browser:
        return {"cookiesfrombrowser": (settings.cookies_from_browser,)}
    if settings.cookies_file and settings.cookies_file.exists():
        return {"cookiefile": str(settings.cookies_file)}
    return {}


def _yt_dlp_run(ydl_opts_base: dict, action):
    """Runs a yt_dlp.YoutubeDL action, retrying once without cookies if a
    cookie-authenticated attempt fails.

    A stale/wrong-account cookiefile can make extraction *worse* than no
    cookies at all — an expired or otherwise-broken session can route
    yt-dlp into a client that returns no playable formats for videos that
    would resolve fine anonymously (see CLAUDE.md's YouTube cookies gotcha).
    ``action`` receives the open YoutubeDL instance and performs the actual
    extract/download call.
    """
    cookie_opts = _cookie_opts()
    try:
        with yt_dlp.YoutubeDL({**ydl_opts_base, **cookie_opts}) as ydl:
            return action(ydl)
    except yt_dlp.utils.DownloadError:
        if not cookie_opts:
            raise
        logger.warning(
            "cookie-authenticated yt-dlp call failed, retrying without cookies"
        )
        with yt_dlp.YoutubeDL(ydl_opts_base) as ydl:
            return action(ydl)


def resolve_metadata(source: str) -> Metadata:
    """Cheap metadata-only lookup (no download) — used to derive data-[ID]."""
    url = _normalize_source(source)
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        info = _yt_dlp_run(ydl_opts, lambda ydl: ydl.extract_info(url, download=False))
    except yt_dlp.utils.DownloadError as exc:
        raise ExtractorError(
            f"could not resolve metadata for {source!r}: {exc}"
        ) from exc

    if info is None:
        raise ExtractorError(f"yt-dlp returned no info for {source!r}")

    return Metadata(
        id=info["id"],
        title=info.get("title") or info["id"],
        uploader=info.get("uploader"),
        source_url=info.get("webpage_url", url),
        duration_s=info.get("duration"),
        upload_date=info.get("upload_date"),
        extractor=info.get("extractor", "unknown"),
        description=info.get("description") or None,
    )


def download_subtitles(
    source: str, workdir: Path, language: str | None
) -> tuple[Path | None, bool, str | None]:
    """Attempts to download an existing subtitle/caption track via yt-dlp.

    Returns (path, is_auto_generated, picked_language). path is None when the
    source has no subtitles in the requested (or "original"/English)
    language — this is a normal, expected outcome for most non-YouTube
    sources, not an error.
    """
    url = _normalize_source(source)
    langs = [language] if language else ["orig", "en"]
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": langs,
        "subtitlesformat": "vtt",
        "outtmpl": str(workdir / "subs.%(ext)s"),
        **_cookie_opts(),
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as exc:
        logger.info("no native subtitles for %r (%s)", source, exc)
        return None, False, None

    candidates = sorted(workdir.glob("subs*.vtt"))
    if not candidates:
        return None, False, None

    requested = (info or {}).get("requested_subtitles") or {}
    manual = (info or {}).get("subtitles") or {}
    picked_lang = next(iter(requested), None)
    is_auto = picked_lang is not None and picked_lang not in manual
    return candidates[0], is_auto, picked_lang


def download_audio(source: str, workdir: Path) -> Path:
    """Downloads best-audio and extracts it to settings.ytdlp_audio_format via ffmpeg.

    Always required — this is the file handed to AssemblyAI.
    """
    url = _normalize_source(source)
    audio_format = "bestaudio/best"
    if settings.ytdlp_audio_max_abr_kbps:
        # Transcription doesn't need the source's highest-fidelity audio
        # track — cap the bitrate to cut download/upload size and time,
        # falling back to plain bestaudio/best if nothing matches (e.g. the
        # source only exposes a single, higher-bitrate audio-only track).
        audio_format = (
            f"bestaudio[abr<={settings.ytdlp_audio_max_abr_kbps}]/bestaudio/best"
        )
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": audio_format,
        "outtmpl": str(workdir / "audio.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": settings.ytdlp_audio_format,
            },
        ],
    }
    try:
        _yt_dlp_run(ydl_opts, lambda ydl: ydl.download([url]))
    except yt_dlp.utils.DownloadError as exc:
        raise ExtractorError(f"audio download failed for {source!r}: {exc}") from exc

    audio_path = workdir / f"audio.{settings.ytdlp_audio_format}"
    if not audio_path.exists():
        raise ExtractorError(
            f"expected {audio_path} after yt-dlp/ffmpeg, but it's missing"
        )

    _probe(audio_path)
    return audio_path


def download_video(source: str, workdir: Path) -> Path:
    """Downloads best combined video+audio. Only called when --keep-video is set."""
    url = _normalize_source(source)
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestvideo+bestaudio/best",
        "outtmpl": str(workdir / "video.%(ext)s"),
        "merge_output_format": "mp4",
    }
    try:
        _yt_dlp_run(ydl_opts, lambda ydl: ydl.download([url]))
    except yt_dlp.utils.DownloadError as exc:
        raise ExtractorError(f"video download failed for {source!r}: {exc}") from exc

    # yt-dlp resolves %(ext)s itself (container depends on merge/remux) —
    # find whatever it actually wrote rather than assuming .mp4.
    candidates = sorted(workdir.glob("video.*"))
    if not candidates:
        raise ExtractorError(
            f"expected a video.* file in {workdir} after yt-dlp, found none"
        )
    video_path = candidates[0]

    _probe(video_path)
    return video_path


def _probe(path: Path) -> dict:
    """Validates a downloaded media file with ffprobe, raising ExtractorError on failure."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration,size",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=settings.ffmpeg_timeout_s,
            check=True,
        )
    except FileNotFoundError as exc:
        raise ExtractorError("ffprobe binary not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise ExtractorError(f"ffprobe failed on {path}: {exc.stderr}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExtractorError(
            f"ffprobe timed out after {settings.ffmpeg_timeout_s}s on {path}"
        ) from exc

    try:
        probe = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ExtractorError(f"ffprobe returned non-JSON output for {path}") from exc

    if not probe.get("format"):
        raise ExtractorError(
            f"ffprobe produced no format info for {path} — file may be corrupt"
        )

    return probe
