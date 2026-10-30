import json
import subprocess

import pytest
import yt_dlp

from app.config import settings
from app.extractor import (
    ExtractorError,
    _cookie_opts,
    _normalize_source,
    _probe,
    _yt_dlp_run,
    download_audio,
)


def test_cookie_opts_empty_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "cookies_from_browser", None)
    monkeypatch.setattr(settings, "cookies_file", None)
    assert _cookie_opts() == {}


def test_cookie_opts_uses_cookies_from_browser_when_set(monkeypatch):
    monkeypatch.setattr(settings, "cookies_from_browser", "chrome")
    monkeypatch.setattr(settings, "cookies_file", None)
    assert _cookie_opts() == {"cookiesfrombrowser": ("chrome",)}


def test_cookie_opts_uses_cookiefile_when_it_exists(monkeypatch, tmp_path):
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setattr(settings, "cookies_from_browser", None)
    monkeypatch.setattr(settings, "cookies_file", cookies_file)
    assert _cookie_opts() == {"cookiefile": str(cookies_file)}


def test_cookie_opts_ignores_configured_but_missing_cookiefile(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "cookies_from_browser", None)
    monkeypatch.setattr(settings, "cookies_file", tmp_path / "does-not-exist.txt")
    assert _cookie_opts() == {}


def test_cookie_opts_prefers_cookies_from_browser_over_cookiefile(
    monkeypatch, tmp_path
):
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setattr(settings, "cookies_from_browser", "firefox")
    monkeypatch.setattr(settings, "cookies_file", cookies_file)
    assert _cookie_opts() == {"cookiesfrombrowser": ("firefox",)}


class _FakeYDL:
    """Minimal stand-in for yt_dlp.YoutubeDL as a context manager."""

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_yt_dlp_run_no_cookies_configured_reraises(monkeypatch):
    monkeypatch.setattr(settings, "cookies_from_browser", None)
    monkeypatch.setattr(settings, "cookies_file", None)
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)

    def action(ydl):
        raise yt_dlp.utils.DownloadError("boom")

    with pytest.raises(yt_dlp.utils.DownloadError):
        _yt_dlp_run({"quiet": True}, action)


def test_yt_dlp_run_retries_without_cookies_on_failure(monkeypatch, tmp_path):
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setattr(settings, "cookies_from_browser", None)
    monkeypatch.setattr(settings, "cookies_file", cookies_file)

    seen_opts = []

    class FakeYDL(_FakeYDL):
        def __init__(self, opts):
            seen_opts.append(opts)
            super().__init__(opts)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)

    calls = {"n": 0}

    def action(ydl):
        calls["n"] += 1
        if "cookiefile" in ydl.opts:
            raise yt_dlp.utils.DownloadError("cookie session broken")
        return "ok"

    result = _yt_dlp_run({"quiet": True}, action)

    assert result == "ok"
    assert calls["n"] == 2
    assert "cookiefile" in seen_opts[0]
    assert "cookiefile" not in seen_opts[1]


def test_yt_dlp_run_reraises_when_fallback_also_fails(monkeypatch, tmp_path):
    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    monkeypatch.setattr(settings, "cookies_from_browser", None)
    monkeypatch.setattr(settings, "cookies_file", cookies_file)
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)

    def action(ydl):
        raise yt_dlp.utils.DownloadError("still broken")

    with pytest.raises(yt_dlp.utils.DownloadError, match="still broken"):
        _yt_dlp_run({"quiet": True}, action)


def test_download_audio_caps_bitrate_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ytdlp_audio_max_abr_kbps", 128)
    captured = {}

    def fake_run(ydl_opts, action):
        captured["format"] = ydl_opts["format"]
        (tmp_path / f"audio.{settings.ytdlp_audio_format}").write_bytes(b"x")

    monkeypatch.setattr("app.extractor._yt_dlp_run", fake_run)
    monkeypatch.setattr("app.extractor._probe", lambda path: {"format": {}})

    download_audio("dQw4w9WgXcQ", tmp_path)

    assert captured["format"] == "bestaudio[abr<=128]/bestaudio/best"


def test_download_audio_uncapped_uses_plain_bestaudio(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ytdlp_audio_max_abr_kbps", None)
    captured = {}

    def fake_run(ydl_opts, action):
        captured["format"] = ydl_opts["format"]
        (tmp_path / f"audio.{settings.ytdlp_audio_format}").write_bytes(b"x")

    monkeypatch.setattr("app.extractor._yt_dlp_run", fake_run)
    monkeypatch.setattr("app.extractor._probe", lambda path: {"format": {}})

    download_audio("dQw4w9WgXcQ", tmp_path)

    assert captured["format"] == "bestaudio/best"


def test_normalize_source_bare_id_assumes_youtube():
    assert (
        _normalize_source("dQw4w9WgXcQ")
        == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )


def test_normalize_source_url_passthrough():
    url = "https://vimeo.com/12345"
    assert _normalize_source(url) == url


def test_probe_raises_when_ffprobe_missing(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ExtractorError, match="ffprobe binary not found"):
        _probe(tmp_path / "audio.m4a")


def test_probe_raises_on_process_error(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "ffprobe", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ExtractorError, match="ffprobe failed"):
        _probe(tmp_path / "audio.m4a")


def test_probe_raises_on_timeout(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=120)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(ExtractorError, match="timed out"):
        _probe(tmp_path / "audio.m4a")


def test_probe_ok(monkeypatch, tmp_path):
    completed = subprocess.CompletedProcess(
        args=["ffprobe"],
        returncode=0,
        stdout=json.dumps({"format": {"duration": "12.3"}}),
        stderr="",
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed)

    probe = _probe(tmp_path / "audio.m4a")
    assert probe["format"]["duration"] == "12.3"


def test_probe_raises_on_empty_format(monkeypatch, tmp_path):
    completed = subprocess.CompletedProcess(
        args=["ffprobe"], returncode=0, stdout=json.dumps({}), stderr=""
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed)

    with pytest.raises(ExtractorError, match="no format info"):
        _probe(tmp_path / "audio.m4a")
