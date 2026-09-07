"""HTTP API for conversion jobs: upload a video from the browser, follow progress, fetch output.

The actual work lives in `jobs.JobStore`; this module holds only the HTTP boundary.
"""

import os
import shutil
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import cv2
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from .fisheye import DEFAULT_FOV, PROJECTIONS
from .jobs import ConvertRequest, Job, JobStore, options_for
from .pipeline import preview_frame
from .quilt import PRESETS
from .sources import Source, SourceStore
from .stereo import FIT_MODES, LAYOUTS
from .video import FfmpegError

JOBS_DIR = Path(os.environ.get("LKG_JOBS_DIR", "out/jobs"))
SOURCES_DIR = JOBS_DIR.parent / "sources"
UPLOAD_CHUNK = 1 << 20
PREVIEW_QUALITY = 82
"""A quilt is a grid of small tiles, which JPEG compresses poorly. 4092 squared exceeds 5 MB,
so the quality is lowered.
"""

_store: JobStore | None = None
_sources: SourceStore | None = None


def store() -> JobStore:
    if _store is None:
        raise HTTPException(status_code=503, detail="サーバーの準備ができていない")
    return _store


def sources() -> SourceStore:
    if _sources is None:
        raise HTTPException(status_code=503, detail="サーバーの準備ができていない")
    return _sources


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _store, _sources
    _sources = SourceStore(SOURCES_DIR)
    _store = JobStore(JOBS_DIR, _sources)
    try:
        yield
    finally:
        _store.close()
        _store = None
        _sources = None


app = FastAPI(title="lkg-quilt-converter", lifespan=_lifespan)


@app.get("/api/options")
def read_options() -> dict[str, Any]:
    """Return the converter's supported values so the UI need not carry its own list."""
    return {
        "layouts": [name for name in LAYOUTS if name != "separate"],
        "projections": list(PROJECTIONS),
        "fovDefault": DEFAULT_FOV,
        "fits": list(FIT_MODES),
        "displays": sorted(PRESETS),
        "presets": {
            name: {
                "columns": spec.columns,
                "rows": spec.rows,
                "width": spec.width,
                "height": spec.height,
                "aspect": spec.aspect,
            }
            for name, spec in PRESETS.items()
        },
    }


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    return [_as_json(job) for job in store().all()]


@app.get("/api/sources")
def list_sources() -> list[dict[str, Any]]:
    """Imported videos. Hundreds of megabytes stay on disk, so the screen can delete them."""
    return [_source_json(source) for source in sources().all()]


@app.delete("/api/sources/{source_id}", status_code=204)
def delete_source(source_id: str) -> None:
    # A running job reads this video mid-conversion; deleting it fails the conversion
    if store().uses_source(source_id):
        raise HTTPException(status_code=409, detail="変換中の素材は消せない")
    if not sources().delete(source_id):
        raise HTTPException(status_code=404, detail="その入力は無い")


@app.post("/api/sources", status_code=201)
async def create_source(
    file: Annotated[UploadFile, File(description="ステレオ動画")],
) -> dict[str, Any]:
    """Upload a video once. Preview and conversion both refer to this id."""
    name = Path(file.filename or "input.mp4").name
    # Hundreds of megabytes arrive, so stream to disk instead of holding it in memory
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=SOURCES_DIR, suffix=".upload") as spooled:
        staged = Path(spooled.name)
        while chunk := await file.read(UPLOAD_CHUNK):
            spooled.write(chunk)
    if staged.stat().st_size == 0:
        staged.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="空のファイルが届いた")
    try:
        return _source_json(sources().add(name, staged))
    except (ValueError, FfmpegError, OSError) as invalid:
        raise HTTPException(status_code=422, detail=f"動画として読めない: {invalid}") from invalid


@app.get("/api/sources/{source_id}")
def read_source(source_id: str) -> dict[str, Any]:
    source = sources().get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="その入力は無い")
    return _source_json(source)


@app.get("/api/sources/{source_id}/preview")
def read_preview(
    source_id: str,
    frame: Annotated[int, Query(ge=0)] = 0,
    layout: str = "sbs",
    display: str = "16",
    fit: str = "crop",
    swap_eyes: bool = False,
    span: float = 2.0,
    convergence: str = "auto",
    projection: str = "flat",
    fov: float = DEFAULT_FOV,
) -> Response:
    """Convert a single frame and return the quilt as JPEG.

    It goes through the same `pipeline` as a full conversion, so **the preview and the final
    output cannot disagree**. The convergence disparity used comes back in the `x-convergence`
    header: `auto` differs per frame, and this lets the value tuned on screen be baked in as is.
    """
    path = sources().path(source_id)
    source = sources().get(source_id)
    if path is None or source is None:
        raise HTTPException(status_code=404, detail="その入力は無い")
    request = _request(
        layout=layout,
        display=display,
        fit=fit,
        swap_eyes=swap_eyes,
        span=span,
        convergence=convergence,
        projection=projection,
        fov=fov,
    )
    options = options_for(request, path, path.parent, stem="preview", start=frame)
    try:
        quilt, used = preview_frame(options)
    except (ValueError, FfmpegError, OSError, StopIteration) as failure:
        raise HTTPException(status_code=422, detail=_preview_error(failure)) from failure
    # cv2 assumes BGR order, so passing rgb24 as is swaps the colours
    ok, encoded = cv2.imencode(
        ".jpg", cv2.cvtColor(quilt, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, PREVIEW_QUALITY]
    )
    if not ok:
        raise HTTPException(status_code=500, detail="プレビューの書き出しに失敗した")
    return Response(
        content=encoded.tobytes(),
        media_type="image/jpeg",
        headers={
            "x-convergence": f"{used:.3f}",
            "cache-control": "no-store",
        },
    )


@app.post("/api/jobs", status_code=201)
def create_job(
    source_id: Annotated[str, Form()],
    layout: Annotated[str, Form()] = "sbs",
    display: Annotated[str, Form()] = "16",
    fit: Annotated[str, Form()] = "crop",
    swap_eyes: Annotated[bool, Form()] = False,
    span: Annotated[float, Form()] = 2.0,
    convergence: Annotated[str, Form()] = "auto",
    projection: Annotated[str, Form()] = "flat",
    fov: Annotated[float, Form()] = DEFAULT_FOV,
    start: Annotated[int, Form()] = 0,
    frames: Annotated[int | None, Form()] = None,
    copy_audio: Annotated[bool, Form()] = True,
) -> dict[str, Any]:
    source = sources().get(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="その入力は無い")
    request = _request(
        layout=layout,
        display=display,
        fit=fit,
        swap_eyes=swap_eyes,
        span=span,
        convergence=convergence,
        projection=projection,
        fov=fov,
        start=start,
        frames=frames,
        copy_audio=copy_audio,
    )
    return _as_json(store().submit(source, request))


@app.get("/api/jobs/{job_id}")
def read_job(job_id: str) -> dict[str, Any]:
    job = store().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="そのジョブは無い")
    return _as_json(job)


@app.post("/api/jobs/{job_id}/cancel", status_code=204)
def cancel_job(job_id: str) -> None:
    """Stop a conversion. No partial video is left behind."""
    if not store().cancel(job_id):
        raise HTTPException(status_code=409, detail="もう終わっているジョブは止められない")


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str) -> None:
    if not store().delete(job_id):
        raise HTTPException(status_code=409, detail="実行中か、もう無いジョブは消せない")


# <video> players sometimes send HEAD. Serving only GET would answer 405
@app.api_route("/api/jobs/{job_id}/result/{filename}", methods=["GET", "HEAD"])
def read_result(job_id: str, filename: str) -> FileResponse:
    """Serve the output. The end of the URL keeps the quilt naming convention so the viewer can
    read the layout from it.
    """
    path = store().result_path(job_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="その成果物は無い")
    return FileResponse(path, media_type="video/mp4", filename=filename)


def _request(**fields: Any) -> ConvertRequest:
    """Validate the string-valued options and copy them into settings, answering 422 if invalid."""
    try:
        return ConvertRequest(**fields)
    except ValueError as invalid:
        raise HTTPException(status_code=422, detail=str(invalid)) from invalid


def _preview_error(failure: Exception) -> str:
    if isinstance(failure, StopIteration):
        return "そのフレームは動画の範囲外"
    return str(failure) or failure.__class__.__name__


def _size(path: Path | None) -> int:
    """The output size. **Returns 0 even when it is gone**, since a deletion mid-listing would
    otherwise turn into a 500.
    """
    if path is None:
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _source_json(source: Source) -> dict[str, Any]:
    return {
        "id": source.id,
        "name": source.name,
        "sizeBytes": sources().size(source.id),
        "createdAt": source.created_at,
        "width": source.width,
        "height": source.height,
        "fps": source.fps,
        "frameCount": source.frame_count,
        "hasAudio": source.has_audio,
        "suggestedLayout": source.suggested_layout,
        "suggestedProjection": source.suggested_projection,
    }


def _as_json(job: Job) -> dict[str, Any]:
    result = (
        f"/api/jobs/{job.id}/result/{job.output_name}"
        if job.status == "done" and job.output_name
        else None
    )
    # Building paths is JobStore's job; rebuilding them here would duplicate the layout
    output = store().result_path(job.id, job.output_name) if job.output_name else None
    return {
        "id": job.id,
        "sizeBytes": _size(output),
        "sourceId": job.source_id,
        "sourceName": job.source_name,
        "status": job.status,
        "doneFrames": job.done_frames,
        "totalFrames": job.total_frames,
        "progress": job.progress,
        "outputName": job.output_name,
        "resultUrl": result,
        "error": job.error,
        "createdAt": job.created_at,
        "startedAt": job.started_at,
        "request": {
            "layout": job.request.layout,
            "display": job.request.display,
            "fit": job.request.fit,
            "projection": job.request.projection,
            "fov": job.request.fov,
            "swapEyes": job.request.swap_eyes,
            "span": job.request.span,
            "convergence": job.request.convergence,
            "start": job.request.start,
            "frames": job.request.frames,
            "copyAudio": job.request.copy_audio,
        },
    }


def run() -> None:
    """Entry point for `lkg-quilt-api`."""
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg が見つからない。変換 API は ffmpeg が無いと動かない")
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    uvicorn.run(
        app,
        host=os.environ.get("LKG_API_HOST", "0.0.0.0"),
        port=int(os.environ.get("LKG_API_PORT", "8000")),
    )
