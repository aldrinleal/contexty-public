import json
from types import SimpleNamespace

from app.extractor import Metadata
from app.formatter import (
    build_metadata_json,
    build_metadata_md,
    build_readme_md,
    build_transcript_md,
    build_transcript_md_from_subtitles,
)
from app.subtitles import Cue


def make_metadata(**overrides) -> Metadata:
    defaults = dict(
        id="abc123",
        title="Um Vídeo de Teste",
        uploader="Canal Teste",
        source_url="https://youtu.be/abc123",
        duration_s=125.0,
        upload_date="20260101",
        extractor="youtube",
        description="Descrição de teste.",
    )
    defaults.update(overrides)
    return Metadata(**defaults)


def make_transcript(**overrides) -> SimpleNamespace:
    defaults = dict(
        id="transcript-1", text="Olá mundo.", utterances=None, language_code="pt"
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_build_transcript_md_without_diarization():
    md = build_transcript_md(make_metadata(), make_transcript())
    assert "# Transcrição — Um Vídeo de Teste" in md
    assert "Olá mundo." in md


def test_build_transcript_md_with_diarization():
    utterance = SimpleNamespace(start=65_000, speaker="A", text="Oi, tudo bem?")
    transcript = make_transcript(utterances=[utterance])
    md = build_transcript_md(make_metadata(), transcript)
    assert "**[01:05] Speaker A:** Oi, tudo bem?" in md


def test_build_transcript_md_from_subtitles():
    cues = [Cue(start_ms=0, text="Olá."), Cue(start_ms=5_000, text="Tudo bem?")]
    md = build_transcript_md_from_subtitles(
        make_metadata(), cues, is_auto_generated=True
    )
    assert "legenda automática" in md
    assert "sem diarização" in md
    assert "**[00:00]** Olá." in md
    assert "**[00:05]** Tudo bem?" in md


def test_build_transcript_md_from_subtitles_empty():
    md = build_transcript_md_from_subtitles(
        make_metadata(), [], is_auto_generated=False
    )
    assert "_(transcrição vazia)_" in md


def test_build_metadata_md_assemblyai_source():
    md = build_metadata_md(
        make_metadata(),
        transcript_source="assemblyai",
        transcript_id="transcript-1",
        language="pt",
        keep_audio=True,
        keep_video=False,
    )
    assert "`abc123`" in md
    assert "Fonte da transcrição**: AssemblyAI" in md
    assert "AssemblyAI transcript id**: `transcript-1`" in md
    assert "Áudio mantido (audio.*)**: sim" in md
    assert "Vídeo mantido (video.*)**: não" in md


def test_build_metadata_md_native_subtitles_source_has_no_transcript_id_line():
    md = build_metadata_md(
        make_metadata(),
        transcript_source="native_subtitles",
        transcript_id=None,
        language="en",
        keep_audio=False,
        keep_video=False,
    )
    assert "Fonte da transcrição**: legenda nativa (yt-dlp)" in md
    assert "transcript id" not in md


def test_build_metadata_md_includes_description_section():
    md = build_metadata_md(
        make_metadata(description="Um vídeo sobre testes."),
        transcript_source="native_subtitles",
        transcript_id=None,
        language="en",
        keep_audio=False,
        keep_video=False,
    )
    assert "## Descrição" in md
    assert "Um vídeo sobre testes." in md


def test_build_metadata_md_description_section_falls_back_when_missing():
    md = build_metadata_md(
        make_metadata(description=None),
        transcript_source="native_subtitles",
        transcript_id=None,
        language="en",
        keep_audio=False,
        keep_video=False,
    )
    assert "_(sem descrição)_" in md


def test_build_metadata_json_has_expected_fields():
    raw = build_metadata_json(
        make_metadata(),
        transcript_source="assemblyai",
        transcript_id="transcript-1",
        language="pt",
        keep_audio=True,
        keep_video=False,
        filenames=["README.md", "metadata.md", "metadata.json", "transcript.md"],
        transcript_text="Olá mundo, este é um teste.",
    )
    data = json.loads(raw)

    assert data["id"] == "abc123"
    assert data["source_url"] == "https://youtu.be/abc123"
    assert data["title"] == "Um Vídeo de Teste"
    assert data["description"] == "Descrição de teste."
    assert data["transcript_source"] == "assemblyai"
    assert data["transcript_id"] == "transcript-1"
    assert data["language"] == "pt"
    assert data["keep_audio"] is True
    assert data["keep_video"] is False
    assert data["files"] == [
        "README.md",
        "metadata.json",
        "metadata.md",
        "transcript.md",
    ]
    assert data["summary"] == "Olá mundo, este é um teste."
    assert data["summary_is_ai_generated"] is False
    assert "processed_at" in data


def test_build_metadata_json_truncates_long_summary():
    raw = build_metadata_json(
        make_metadata(),
        transcript_source="native_subtitles",
        transcript_id=None,
        language="en",
        keep_audio=False,
        keep_video=False,
        filenames=[],
        transcript_text="palavra " * 200,
        summary_chars=50,
    )
    data = json.loads(raw)

    assert len(data["summary"]) <= 51  # 50 chars + the truncation ellipsis
    assert data["summary"].endswith("…")


def test_build_readme_md_lists_files_sorted():
    md = build_readme_md(
        make_metadata(), ["metadata.md", "README.md", "transcript.md", "audio.m4a"]
    )
    assert "- `README.md`" in md
    assert "- `audio.m4a`" in md
    assert (
        md.index("README.md`")
        < md.index("audio.m4a`")
        < md.index("metadata.md`")
        < md.index("transcript.md`")
    )
