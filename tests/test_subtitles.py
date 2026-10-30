from pathlib import Path

from app.subtitles import Cue, parse_subtitle_file

VTT_MANUAL = """WEBVTT

00:00:00.000 --> 00:00:02.000
Olá, tudo bem?

00:00:02.500 --> 00:00:05.000
Bem-vindo ao vídeo de teste.
"""

# Auto-generated captions roll: each cue repeats the previous text plus a new
# word — parse_subtitle_file should collapse this into one cue per sentence.
VTT_AUTO_ROLLING = """WEBVTT

00:00:00.000 --> 00:00:01.000
hello

00:00:01.000 --> 00:00:02.000
hello there

00:00:02.000 --> 00:00:03.000
hello there friend
"""

SRT_MANUAL = """1
00:00:00,000 --> 00:00:02,000
Primeira linha.

2
00:00:02,500 --> 00:00:04,000
Segunda linha.
"""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_vtt_manual(tmp_path):
    path = _write(tmp_path, "subs.vtt", VTT_MANUAL)
    cues = parse_subtitle_file(path)
    assert cues == [
        Cue(start_ms=0, text="Olá, tudo bem?"),
        Cue(start_ms=2_500, text="Bem-vindo ao vídeo de teste."),
    ]


def test_parse_vtt_collapses_rolling_auto_captions(tmp_path):
    path = _write(tmp_path, "subs.vtt", VTT_AUTO_ROLLING)
    cues = parse_subtitle_file(path)
    # only one cue survives: earliest start time, final (longest) text
    assert cues == [Cue(start_ms=0, text="hello there friend")]


def test_parse_srt_manual(tmp_path):
    path = _write(tmp_path, "subs.srt", SRT_MANUAL)
    cues = parse_subtitle_file(path)
    assert cues == [
        Cue(start_ms=0, text="Primeira linha."),
        Cue(start_ms=2_500, text="Segunda linha."),
    ]


def test_parse_subtitle_file_empty(tmp_path):
    path = _write(tmp_path, "subs.vtt", "WEBVTT\n\n")
    assert parse_subtitle_file(path) == []
