import subprocess

import pytest

from app.s3sync import S3SyncError, s3_prefix, sync_to_s3


def test_s3_prefix():
    assert s3_prefix("abc123") == "s3://example-contexty-bucket/data/abc123/"


def test_sync_to_s3_raises_when_aws_cli_missing(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(S3SyncError, match="aws CLI not found"):
        sync_to_s3(tmp_path, "s3://bucket/prefix/")


def test_sync_to_s3_raises_on_process_error(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "aws", stderr="access denied")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(S3SyncError, match="aws s3 sync failed"):
        sync_to_s3(tmp_path, "s3://bucket/prefix/")


def test_sync_to_s3_raises_on_timeout(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="aws", timeout=180)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(S3SyncError, match="timed out"):
        sync_to_s3(tmp_path, "s3://bucket/prefix/")


def test_sync_to_s3_ok(monkeypatch, tmp_path):
    completed = subprocess.CompletedProcess(
        args=["aws"], returncode=0, stdout="", stderr=""
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: completed)

    sync_to_s3(tmp_path, "s3://bucket/prefix/")  # no exception raised
