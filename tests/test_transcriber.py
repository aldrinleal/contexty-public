from types import SimpleNamespace

import assemblyai as aai

from app import transcriber


def test_check_status_returns_plain_value_not_enum_repr(monkeypatch):
    """Regression test: TranscriptStatus is a (str, Enum) mixin whose __str__
    still renders "TranscriptStatus.completed" instead of the plain value —
    using str(transcript.status) instead of .value silently broke every
    status comparison in the poll loop (it never matched "completed" or
    "error", so the AssemblyAI path never terminated)."""
    fake_transcript = SimpleNamespace(status=aai.TranscriptStatus.completed)
    monkeypatch.setattr(
        aai.Transcript, "get_by_id", lambda transcript_id: fake_transcript
    )

    status = transcriber.check_status("transcript-1")

    assert status == "completed"
    assert "TranscriptStatus" not in status
