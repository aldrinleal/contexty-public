import sqlite3

import pytest

from app import jobstore


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute(jobstore._SCHEMA)
    c.commit()
    return c


def test_claim_succeeds_first_time(conn):
    assert (
        jobstore.claim("abc123", "https://youtu.be/abc123", "Title", conn=conn) is True
    )


def test_claim_fails_on_duplicate(conn):
    assert jobstore.claim("abc123", "src", "title", conn=conn) is True
    assert jobstore.claim("abc123", "src", "title", conn=conn) is False


def test_claim_succeeds_again_after_ttl_expiry(conn):
    assert jobstore.claim("abc123", "src", "title", conn=conn) is True
    # simulate an expired row
    conn.execute("UPDATE jobs SET expires_at = 1 WHERE id = ?", ("abc123",))
    conn.commit()
    assert jobstore.claim("abc123", "src", "title", conn=conn) is True


def test_mark_completed_updates_status(conn):
    jobstore.claim("abc123", "src", "title", conn=conn)
    jobstore.mark_completed("abc123", "assemblyai", "/data/data-abc123", conn=conn)

    job = jobstore.get("abc123", conn=conn)
    assert job["status"] == "completed"
    assert job["transcript_source"] == "assemblyai"
    assert job["data_dir"] == "/data/data-abc123"
    assert job["s3_uri"] is None


def test_mark_completed_stores_s3_uri(conn):
    jobstore.claim("abc123", "src", "title", conn=conn)
    jobstore.mark_completed(
        "abc123",
        "assemblyai",
        "/data/data-abc123",
        "s3://example-contexty-bucket/data/abc123/",
        conn=conn,
    )

    job = jobstore.get("abc123", conn=conn)
    assert job["s3_uri"] == "s3://example-contexty-bucket/data/abc123/"


def test_mark_failed_upserts_even_without_prior_claim(conn):
    jobstore.mark_failed("neverclaimed", "boom", conn=conn)

    job = jobstore.get("neverclaimed", conn=conn)
    assert job["status"] == "error"
    assert job["error_message"] == "boom"


def test_get_missing_returns_none(conn):
    assert jobstore.get("missing", conn=conn) is None


def test_list_recent_orders_by_updated_at_desc(conn):
    jobstore.claim("first", "src", "title", conn=conn)
    jobstore.claim("second", "src", "title", conn=conn)

    jobs = jobstore.list_recent(conn=conn)
    ids = [j["id"] for j in jobs]
    assert ids == ["second", "first"]
