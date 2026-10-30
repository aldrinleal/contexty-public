"""Writes data-[ID]/ — the one output directory shape shared by every entrypoint.

``base_dir`` is ``settings.output_dir`` — the current directory for the
local CLI, or a mounted volume path (e.g. ``/data``) for a containerized
deployment.

Called up to twice per pipeline run (audio/video, then the three .md files)
— both calls target the same data-[ID]/ dir and are safe to interleave
since each call only ever adds/overwrites its own filenames.
"""

import shutil
from pathlib import Path


def job_dir(base_dir: Path, id_: str) -> Path:
    """Pure path construction — does NOT create the directory. Use this for
    reads (e.g. app/api.py's file-serving endpoint)."""
    return base_dir / f"data-{id_}"


def data_dir(base_dir: Path, id_: str) -> Path:
    d = job_dir(base_dir, id_)
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_output(
    base_dir: Path, id_: str, files: dict[str, str | bytes | Path]
) -> Path:
    """Writes/overwrites `files` into base_dir/data-{id_}/. Returns that directory.

    Values may be:
    - str: written as UTF-8 text (e.g. the generated .md files)
    - bytes: written as-is
    - Path: copied from (e.g. the audio/video file yt-dlp produced in /tmp)
    """
    d = data_dir(base_dir, id_)
    for name, content in files.items():
        dest = d / name
        if isinstance(content, Path):
            shutil.copyfile(content, dest)
        elif isinstance(content, bytes):
            dest.write_bytes(content)
        else:
            dest.write_text(content, encoding="utf-8")
    return d
