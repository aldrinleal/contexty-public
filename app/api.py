"""Mini HTTP API: submit / confirm / list jobs.

Auth: every route except GET /healthz requires
``Authorization: Bearer <CONTEXTY_API_TOKEN>``.

Async model: POST /jobs resolves metadata and claims the dedup guard
*synchronously* (fast — one yt-dlp metadata lookup) so it can answer
"already processed" immediately, then hands the (possibly slow)
download+transcribe work to a small in-process thread pool and returns
202 right away. No external queue/broker — matches this tool's volume
(a personal/small-team utility, not a high-throughput service).

    submit:  POST /jobs            -> {id, duplicate, status_url}
    confirm: GET  /jobs/{id}       -> the jobstore row (status: processing|completed|error)
    list:    GET  /jobs            -> recent jobs (history/filtering)
    fetch:   GET  /jobs/{id}/files/{filename} -> the actual .md/audio/video file
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app import jobstore
from app.config import settings
from app.extractor import ExtractorError, resolve_metadata
from app.output import job_dir
from app.pipeline import PipelineError, run_pipeline

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="contexty", version="1.0.0")
_executor = ThreadPoolExecutor(
    max_workers=settings.max_workers, thread_name_prefix="contexty-job"
)
_security = HTTPBearer(auto_error=False)


def require_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> None:
    if not settings.api_token:
        # Fail closed, not open — an unset token must never mean "no auth required".
        raise HTTPException(500, "CONTEXTY_API_TOKEN is not configured on the server")
    if credentials is None or credentials.credentials != settings.api_token:
        raise HTTPException(401, "invalid or missing bearer token")


class SubmitRequest(BaseModel):
    source: str
    keep_audio: bool = False
    keep_video: bool = False
    language: str | None = None
    prefer_native_subtitles: bool | None = None


# Real cookies.txt exports are a few KB even with many domains — this is a
# generous ceiling against a mistaken/oversized upload, not a tight budget.
MAX_COOKIES_BYTES = 512 * 1024


def _looks_like_netscape_cookies(text: str) -> bool:
    """Loose format check: first non-blank line is a comment or a tab-delimited row.

    Deliberately not strict about the full 7-field Netscape schema — export
    formats vary slightly across browser extensions; this just rejects
    obvious garbage (HTML error pages, empty files, etc).
    """
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        return line.startswith("#") or "\t" in line
    return False


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/jobs", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_token)]
)
def submit_job(body: SubmitRequest) -> dict[str, Any]:
    try:
        metadata = resolve_metadata(body.source)
    except ExtractorError as exc:
        raise HTTPException(422, f"could not resolve {body.source!r}: {exc}") from exc

    claimed = True
    if settings.enable_history_guard:
        claimed = jobstore.claim(metadata.id, body.source, metadata.title)

    if claimed:

        def _run() -> None:
            try:
                run_pipeline(
                    metadata,
                    body.source,
                    body.keep_audio,
                    body.keep_video,
                    body.language,
                    body.prefer_native_subtitles,
                )
            except PipelineError:
                pass  # already recorded in the jobstore by run_pipeline

        _executor.submit(_run)

    return {
        "id": metadata.id,
        "title": metadata.title,
        "duplicate": not claimed,
        "status_url": f"/jobs/{metadata.id}",
    }


@app.get("/jobs", dependencies=[Depends(require_token)])
def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    return jobstore.list_recent(limit=limit)


@app.get("/jobs/{job_id}", dependencies=[Depends(require_token)])
def get_job(job_id: str) -> dict[str, Any]:
    job = jobstore.get(job_id)
    if job is None:
        raise HTTPException(404, f"no job with id {job_id!r}")
    return job


@app.get("/jobs/{job_id}/files/{filename}", dependencies=[Depends(require_token)])
def get_job_file(job_id: str, filename: str) -> FileResponse:
    if "/" in filename or filename in (".", ".."):
        raise HTTPException(400, "invalid filename")

    path = job_dir(settings.output_dir, job_id) / filename
    if not path.is_file():
        raise HTTPException(404, f"no file {filename!r} for job {job_id!r}")
    return FileResponse(path)


@app.put("/cookies", dependencies=[Depends(require_token)])
async def upload_cookies(request: Request) -> dict[str, Any]:
    """Replaces the server-side cookies.txt (settings.cookies_file) — see
    app/config.py and scripts/upload-cookies.sh. Body is the raw cookies.txt
    content (Netscape format), not JSON.
    """
    if not settings.cookies_file:
        raise HTTPException(
            500, "CONTEXTY_COOKIES_FILE is not configured on the server"
        )

    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")
    if len(body) > MAX_COOKIES_BYTES:
        raise HTTPException(400, f"cookies.txt too large (> {MAX_COOKIES_BYTES} bytes)")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(400, f"not valid UTF-8: {exc}") from exc
    if not _looks_like_netscape_cookies(text):
        raise HTTPException(400, "doesn't look like a Netscape-format cookies.txt")

    path = settings.cookies_file
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic swap — an in-flight yt-dlp read must never see a half-written file.
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)

    return {"size_bytes": len(body), "written_to": str(path)}


@app.get("/cookies", dependencies=[Depends(require_token)])
def cookies_status() -> dict[str, Any]:
    """Status only — never echoes the cookie values themselves back."""
    if not settings.cookies_file:
        return {
            "configured": False,
            "exists": False,
            "size_bytes": None,
            "modified_at": None,
        }
    if not settings.cookies_file.is_file():
        return {
            "configured": True,
            "exists": False,
            "size_bytes": None,
            "modified_at": None,
        }
    st = settings.cookies_file.stat()
    return {
        "configured": True,
        "exists": True,
        "size_bytes": st.st_size,
        "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
    }
