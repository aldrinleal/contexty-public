import time

import pytest
from fastapi.testclient import TestClient

from app import api as api_module
from app import jobstore
from app.config import settings
from app.extractor import Metadata

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "test-token")
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "contexty.db")
    monkeypatch.setattr(
        jobstore, "_conn", None
    )  # force a fresh sqlite connection per test
    return TestClient(api_module.app)


def _fake_metadata(id_: str = "abc123", title: str = "Title") -> Metadata:
    return Metadata(
        id=id_,
        title=title,
        uploader=None,
        source_url="https://x",
        duration_s=1.0,
        upload_date=None,
        extractor="youtube",
    )


def _wait_until(predicate, timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition never became true")


def test_healthz_no_auth_needed(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_jobs_requires_token(client):
    assert client.get("/jobs").status_code == 401


def test_jobs_rejects_wrong_token(client):
    resp = client.get("/jobs", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_submit_job_schedules_background_and_returns_id(client, monkeypatch):
    monkeypatch.setattr(api_module, "resolve_metadata", lambda source: _fake_metadata())
    calls = []
    monkeypatch.setattr(
        api_module, "run_pipeline", lambda *a, **k: calls.append((a, k))
    )

    resp = client.post(
        "/jobs", json={"source": "https://youtu.be/abc123"}, headers=AUTH
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body == {
        "id": "abc123",
        "title": "Title",
        "duplicate": False,
        "status_url": "/jobs/abc123",
    }
    _wait_until(lambda: len(calls) == 1)


def test_submit_job_duplicate_does_not_schedule_again(client, monkeypatch):
    monkeypatch.setattr(api_module, "resolve_metadata", lambda source: _fake_metadata())
    calls = []
    monkeypatch.setattr(
        api_module, "run_pipeline", lambda *a, **k: calls.append((a, k))
    )

    client.post("/jobs", json={"source": "https://youtu.be/abc123"}, headers=AUTH)
    _wait_until(lambda: len(calls) == 1)

    resp = client.post(
        "/jobs", json={"source": "https://youtu.be/abc123"}, headers=AUTH
    )

    assert resp.json()["duplicate"] is True
    time.sleep(0.1)
    assert len(calls) == 1  # second submission never ran the pipeline


def test_get_job_not_found(client):
    assert client.get("/jobs/doesnotexist", headers=AUTH).status_code == 404


def test_get_job_after_submit(client, monkeypatch):
    monkeypatch.setattr(api_module, "resolve_metadata", lambda source: _fake_metadata())
    monkeypatch.setattr(api_module, "run_pipeline", lambda *a, **k: None)

    client.post("/jobs", json={"source": "https://youtu.be/abc123"}, headers=AUTH)

    resp = client.get("/jobs/abc123", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["status"] == "processing"


def test_list_jobs_includes_submitted(client, monkeypatch):
    monkeypatch.setattr(api_module, "resolve_metadata", lambda source: _fake_metadata())
    monkeypatch.setattr(api_module, "run_pipeline", lambda *a, **k: None)

    client.post("/jobs", json={"source": "https://youtu.be/abc123"}, headers=AUTH)

    resp = client.get("/jobs", headers=AUTH)
    assert resp.status_code == 200
    assert [j["id"] for j in resp.json()] == ["abc123"]


def test_get_job_file_rejects_path_traversal(client):
    # %2e%2e (not literal "..") so the HTTP client doesn't collapse it away
    # client-side before the request even reaches our handler.
    resp = client.get("/jobs/abc123/files/%2e%2e", headers=AUTH)
    assert resp.status_code == 400


def test_get_job_file_404_when_missing(client):
    assert (
        client.get("/jobs/abc123/files/transcript.md", headers=AUTH).status_code == 404
    )


def test_get_job_file_serves_existing_file(client):
    job_dir = settings.output_dir / "data-abc123"
    job_dir.mkdir(parents=True)
    (job_dir / "transcript.md").write_text("hello", encoding="utf-8")

    resp = client.get("/jobs/abc123/files/transcript.md", headers=AUTH)
    assert resp.status_code == 200
    assert resp.text == "hello"


NETSCAPE_COOKIES = (
    "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tfoo\tbar\n"
)


def test_cookies_status_when_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "cookies_file", None)
    resp = client.get("/cookies", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {
        "configured": False,
        "exists": False,
        "size_bytes": None,
        "modified_at": None,
    }


def test_cookies_status_when_configured_but_missing(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "cookies_file", tmp_path / "cookies.txt")
    resp = client.get("/cookies", headers=AUTH)
    assert resp.json() == {
        "configured": True,
        "exists": False,
        "size_bytes": None,
        "modified_at": None,
    }


def test_upload_cookies_rejects_when_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "cookies_file", None)
    resp = client.put(
        "/cookies",
        content=NETSCAPE_COOKIES,
        headers={**AUTH, "Content-Type": "text/plain"},
    )
    assert resp.status_code == 500


def test_upload_cookies_rejects_empty_body(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "cookies_file", tmp_path / "cookies.txt")
    resp = client.put(
        "/cookies", content=b"", headers={**AUTH, "Content-Type": "text/plain"}
    )
    assert resp.status_code == 400


def test_upload_cookies_rejects_garbage(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "cookies_file", tmp_path / "cookies.txt")
    resp = client.put(
        "/cookies",
        content="<html>not a cookie file</html>",
        headers={**AUTH, "Content-Type": "text/plain"},
    )
    assert resp.status_code == 400


def test_upload_cookies_rejects_oversized(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "cookies_file", tmp_path / "cookies.txt")
    huge = "# Netscape HTTP Cookie File\n" + ("a" * (513 * 1024))
    resp = client.put(
        "/cookies", content=huge, headers={**AUTH, "Content-Type": "text/plain"}
    )
    assert resp.status_code == 400


def test_upload_cookies_writes_file_and_status_reflects_it(
    client, monkeypatch, tmp_path
):
    cookies_file = tmp_path / "cookies.txt"
    monkeypatch.setattr(settings, "cookies_file", cookies_file)

    resp = client.put(
        "/cookies",
        content=NETSCAPE_COOKIES,
        headers={**AUTH, "Content-Type": "text/plain"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["size_bytes"] == len(NETSCAPE_COOKIES.encode("utf-8"))
    assert body["written_to"] == str(cookies_file)
    assert cookies_file.read_text(encoding="utf-8") == NETSCAPE_COOKIES
    assert not cookies_file.with_suffix(".tmp").exists()

    status_resp = client.get("/cookies", headers=AUTH)
    status = status_resp.json()
    assert status["configured"] is True
    assert status["exists"] is True
    assert status["size_bytes"] == len(NETSCAPE_COOKIES.encode("utf-8"))
    assert status["modified_at"] is not None
