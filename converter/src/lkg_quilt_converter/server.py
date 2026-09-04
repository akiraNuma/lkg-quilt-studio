"""変換ジョブの HTTP API。ブラウザから動画を投げて、進捗を見て、成果物を取る。

実処理は `jobs.JobStore` にあり、ここは HTTP との境界だけを持つ。
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
"""quilt は細かいタイルの集まりで JPEG が効きにくい。4092² が 5 MB を超えるので落としてある。"""

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
    """UI が選択肢を自前で持たないよう、変換側の対応値を返す。"""
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


@app.post("/api/sources", status_code=201)
async def create_source(
    file: Annotated[UploadFile, File(description="ステレオ動画")],
) -> dict[str, Any]:
    """動画を 1 回だけ上げる。プレビューと変換はこの id を指す。"""
    name = Path(file.filename or "input.mp4").name
    # 数百 MB が来るので、メモリに載せずディスクへ流す
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
    """1 フレームだけ変換して quilt の JPEG を返す。

    変換本体と同じ `pipeline` を通すので、**プレビューと最終出力が食い違わない**。
    使った収束面の視差は `x-convergence` ヘッダで返す。auto はフレームごとに変わるので、
    画面で詰めた値をそのまま焼き込めるようにするため。
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
    # cv2 は BGR 順を前提にするので、rgb24 のまま渡すと色が入れ替わる
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
    """変換を止める。書きかけの動画は残さない。"""
    if not store().cancel(job_id):
        raise HTTPException(status_code=409, detail="もう終わっているジョブは止められない")


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str) -> None:
    if not store().delete(job_id):
        raise HTTPException(status_code=409, detail="実行中か、もう無いジョブは消せない")


# <video> と Bridge は HEAD を投げることがある。GET だけだと 405 を返してしまう
@app.api_route("/api/jobs/{job_id}/result/{filename}", methods=["GET", "HEAD"])
def read_result(job_id: str, filename: str) -> FileResponse:
    """成果物を返す。ビューアと Bridge がレイアウトを読めるよう、
    URL の末尾は quilt の名前規約のままにしてある。"""
    path = store().result_path(job_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="その成果物は無い")
    return FileResponse(path, media_type="video/mp4", filename=filename)


def _request(**fields: Any) -> ConvertRequest:
    """文字列で来た選択肢を検証して設定に写す。不正なら 422 で返す。"""
    try:
        return ConvertRequest(**fields)
    except ValueError as invalid:
        raise HTTPException(status_code=422, detail=str(invalid)) from invalid


def _preview_error(failure: Exception) -> str:
    if isinstance(failure, StopIteration):
        return "そのフレームは動画の範囲外"
    return str(failure) or failure.__class__.__name__


def _source_json(source: Source) -> dict[str, Any]:
    return {
        "id": source.id,
        "name": source.name,
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
    return {
        "id": job.id,
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
    """`lkg-quilt-api` の入口。"""
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg が見つからない。変換 API は ffmpeg が無いと動かない")
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    uvicorn.run(
        app,
        host=os.environ.get("LKG_API_HOST", "0.0.0.0"),
        port=int(os.environ.get("LKG_API_PORT", "8000")),
    )
