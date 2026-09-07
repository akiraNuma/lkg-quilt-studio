"""Accepting and running conversion jobs. Kept apart from HTTP so it can be tested alone.

Conversion saturates the CPU, so a single worker processes jobs in order.
"""

import json
import queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal

from .dibr import SynthesisParams
from .fisheye import DEFAULT_FOV, PROJECTIONS, Projection
from .pipeline import ConvertOptions, convert
from .quilt import PRESETS, QuiltSpec
from .sources import Source, SourceStore
from .stereo import FIT_MODES, LAYOUTS, FitMode, StereoLayout

JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]

STATE_FILE = "job.json"


@dataclass(frozen=True)
class ConvertRequest:
    """Settings received from the UI: the CLI arguments worth touching from a screen."""

    layout: StereoLayout = "sbs"
    display: str = "16"
    fit: FitMode = "crop"
    projection: Projection = "flat"
    fov: float = DEFAULT_FOV
    swap_eyes: bool = False
    span: float = 2.0
    convergence: str = "auto"
    start: int = 0
    frames: int | None = None
    copy_audio: bool = True

    def __post_init__(self) -> None:
        if self.layout not in LAYOUTS:
            raise ValueError(f"layout must be one of {'/'.join(LAYOUTS)} (received: {self.layout})")
        if self.display not in PRESETS:
            raise ValueError(
                f"display must be one of {'/'.join(sorted(PRESETS))} (received: {self.display})"
            )
        if self.projection not in PROJECTIONS:
            raise ValueError(
                f"projection must be one of {'/'.join(PROJECTIONS)} (received: {self.projection})"
            )
        if not 0.0 < self.fov < 180.0:
            raise ValueError(f"fov must be above 0 and below 180 (received: {self.fov})")
        if self.fit not in FIT_MODES:
            raise ValueError(f"fit must be one of {'/'.join(FIT_MODES)} (received: {self.fit})")
        if self.layout == "separate":
            raise ValueError("separate needs two videos, which this screen cannot handle")
        if self.span <= 0:
            raise ValueError(f"span must be positive (received: {self.span})")
        if self.start < 0:
            raise ValueError(f"start must be at least 0 (received: {self.start})")
        if self.frames is not None and self.frames < 1:
            raise ValueError(f"frames must be at least 1 (received: {self.frames})")
        self.convergence_value()

    def convergence_value(self) -> float:
        """Collapse `auto` to 0.0. Whether it was auto is read from `is_auto_convergence`."""
        if self.convergence == "auto":
            return 0.0
        try:
            return float(self.convergence)
        except ValueError as invalid:
            raise ValueError(
                f"convergence takes a number or auto (received: {self.convergence})"
            ) from invalid

    @property
    def is_auto_convergence(self) -> bool:
        return self.convergence == "auto"

    def spec(self) -> QuiltSpec:
        return PRESETS[self.display]


@dataclass(frozen=True)
class Job:
    """One conversion's state, returned to the UI as JSON in this shape."""

    id: str
    source_id: str
    source_name: str
    status: JobStatus
    request: ConvertRequest
    created_at: float
    started_at: float | None = None
    """When the conversion started. Remaining time is measured from here (a single preview
    frame gives a poor estimate).
    """

    done_frames: int = 0
    total_frames: int = 0
    output_name: str | None = None
    error: str | None = None

    @property
    def progress(self) -> float:
        """0.0 to 1.0. Returns 0.0 before the total frame count is known."""
        if self.status == "done":
            return 1.0
        if not self.total_frames:
            return 0.0
        return min(self.done_frames / self.total_frames, 1.0)


class _Cancelled(Exception):
    """The cancellation signal, raised from the progress callback to unwind a conversion."""


class JobStore:
    """Keep job state and output under `root`, converting in order on a single worker.

    State is written to a per-job `job.json` so finished output can still be served after the
    process restarts.
    """

    def __init__(self, root: Path, sources: SourceStore) -> None:
        self._root = root
        self._sources = sources
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._closing = threading.Event()
        self._cancelling: set[str] = set()
        self._restore()

    # --- accepting ------------------------------------------------------

    def submit(self, source: Source, request: ConvertRequest) -> Job:
        """Queue a job pointing at an imported source. The video is not copied."""
        job_id = uuid.uuid4().hex
        (self._root / job_id).mkdir(parents=True)
        job = Job(
            id=job_id,
            source_id=source.id,
            source_name=source.name,
            status="queued",
            request=request,
            created_at=time.time(),
        )
        self._write(job)
        self._queue.put(job_id)
        self._ensure_worker()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        with self._lock:
            jobs = list(self._jobs.values())
        return sorted(jobs, key=lambda job: job.created_at, reverse=True)

    def uses_source(self, source_id: str) -> bool:
        """Whether a queued or running job points at that source. Check before deleting."""
        with self._lock:
            return any(
                job.source_id == source_id and job.status in ("queued", "running")
                for job in self._jobs.values()
            )

    def result_path(self, job_id: str, filename: str) -> Path | None:
        """Return the output file, or None when the job is unfinished or the name differs."""
        job = self.get(job_id)
        if job is None or job.status != "done" or job.output_name != filename:
            return None
        path = self._root / job_id / filename
        return path if path.exists() else None

    def cancel(self, job_id: str) -> bool:
        """Stop a running or queued job. Returns False when it cannot be stopped.

        A running conversion exits once it finishes writing the current frame (seen through the
        progress callback). **No partial video is left behind:** a half-baked quilt has an
        arbitrary duration, and leaving it under a name matching the convention would let the
        viewer open it.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in ("queued", "running"):
                return False
            self._cancelling.add(job_id)
        return True

    def delete(self, job_id: str) -> bool:
        """Delete a queued or finished job. A running job is not deleted."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status == "running":
                return False
            del self._jobs[job_id]
        _remove_tree(self._root / job_id)
        return True

    def close(self) -> None:
        self._closing.set()
        self._queue.put("")
        worker = self._worker
        if worker is not None:
            worker.join(timeout=5.0)

    # --- worker ---------------------------------------------------------

    def _ensure_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._run, name="lkg-convert", daemon=True)
        self._worker.start()

    def _run(self) -> None:
        while not self._closing.is_set():
            job_id = self._queue.get()
            if not job_id or self._closing.is_set():
                return
            job = self.get(job_id)
            if job is None:
                continue
            with self._lock:
                waiting = job_id in self._cancelling
                self._cancelling.discard(job_id)
            if waiting:
                self._mutate(job_id, lambda current: replace(current, status="cancelled"))
                continue
            self._process(job)

    def _process(self, job: Job) -> None:
        self._mutate(
            job.id,
            lambda current: replace(
                current, status="running", done_frames=0, started_at=time.time()
            ),
        )
        directory = self._root / job.id
        options: ConvertOptions | None = None
        try:
            source = self._sources.path(job.source_id)
            if source is None:
                raise ValueError("the input video is missing (deleted, or the server was rebuilt)")
            options = options_for(job.request, source, directory, stem=Path(job.source_name).stem)
            convert(options, progress=lambda done, total: self._progress(job.id, done, total))
            name = options.output.name
            self._mutate(job.id, lambda current: replace(current, status="done", output_name=name))
        except _Cancelled:
            # The no-audio path writes straight to the output, so a partial file remains
            if options is not None:
                options.output.unlink(missing_ok=True)
            self._mutate(job.id, lambda current: replace(current, status="cancelled"))
        # Conversion can fail in OpenCV, ffmpeg, or on disk. The worker must never die
        except Exception as failure:
            message = _message(failure)
            self._mutate(job.id, lambda current: replace(current, status="failed", error=message))
        finally:
            with self._lock:
                self._cancelling.discard(job.id)

    def _progress(self, job_id: str, done: int, total: int) -> None:
        with self._lock:
            if job_id in self._cancelling:
                raise _Cancelled
        # This arrives every frame, so it is not written to a file; recovering a crash as a
        # failure is enough
        self._mutate(
            job_id,
            lambda current: replace(current, done_frames=done, total_frames=total),
            persist=False,
        )

    # --- persisting state -----------------------------------------------

    def _mutate(self, job_id: str, change: Callable[[Job], Job], *, persist: bool = True) -> None:
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None:
                return
            updated = change(current)
            self._jobs[job_id] = updated
        if persist:
            self._write(updated)

    def _write(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job
        directory = self._root / job.id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / STATE_FILE).write_text(json.dumps(asdict(job), ensure_ascii=False, indent=2))

    def _restore(self) -> None:
        for state in sorted(self._root.glob(f"*/{STATE_FILE}")):
            try:
                loaded = json.loads(state.read_text())
                job = Job(**{**loaded, "request": ConvertRequest(**loaded["request"])})
            # Ignore an old format or broken JSON: the output simply cannot be served, which is
            # harmless
            except ValueError, TypeError, KeyError:
                continue
            # State left behind by a crashed process. It cannot resume, so show it as failed and
            # write that back to the file (left as running, a later read would call it in flight)
            if job.status in ("queued", "running"):
                self._write(replace(job, status="failed", error="interrupted by a server restart"))
                continue
            self._jobs[job.id] = job


def options_for(
    request: ConvertRequest,
    source: Path,
    output_dir: Path,
    *,
    stem: str,
    start: int | None = None,
) -> ConvertOptions:
    """Copy UI settings into pipeline settings. `start` swaps the frame for a preview."""
    spec = request.spec()
    return ConvertOptions(
        source=source,
        output=output_dir / spec.filename(stem, "mp4"),
        spec=spec,
        layout=request.layout,
        fit=request.fit,
        projection=request.projection,
        fov=request.fov,
        swap_eyes=request.swap_eyes,
        start=request.start if start is None else start,
        frames=request.frames,
        span=request.span,
        synthesis=SynthesisParams(convergence=request.convergence_value()),
        auto_convergence=request.is_auto_convergence,
        copy_audio=request.copy_audio,
    )


def _message(failure: Exception) -> str:
    text = str(failure).strip()
    return text or failure.__class__.__name__


def _remove_tree(directory: Path) -> None:
    if not directory.exists():
        return
    for path in sorted(directory.rglob("*"), reverse=True):
        path.rmdir() if path.is_dir() else path.unlink()
    directory.rmdir()
