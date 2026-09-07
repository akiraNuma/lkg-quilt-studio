"""Job acceptance and state transitions. Conversion itself is covered by the pipeline tests."""

import json
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import pytest

from lkg_quilt_converter.jobs import ConvertRequest, Job, JobStore
from lkg_quilt_converter.pipeline import ConvertOptions
from lkg_quilt_converter.sources import Source, SourceStore

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "bbb_stereo_tb.mp4"
"""Real footage with two views stacked vertically, used to cancel mid-conversion for real."""


def _store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path / "jobs", SourceStore(tmp_path / "sources"))


def _broken_source(tmp_path: Path, name: str = "movie.mp4") -> Source:
    """Plant a source without going through probe, to exercise the path that fails during
    conversion.
    """
    source = Source(
        id=uuid.uuid4().hex,
        name=name,
        width=0,
        height=0,
        fps=0.0,
        frame_count=0,
        has_audio=False,
    )
    directory = tmp_path / "sources" / source.id
    directory.mkdir(parents=True)
    (directory / f"input{Path(name).suffix}").write_bytes(b"broken")
    (directory / "source.json").write_text(json.dumps(asdict(source), ensure_ascii=False))
    return source


def test_layout_separate_is_rejected() -> None:
    with pytest.raises(ValueError, match="separate"):
        ConvertRequest(layout="separate")


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ConvertRequest(layout="nope"),  # type: ignore[arg-type]
        lambda: ConvertRequest(display="nope"),
        lambda: ConvertRequest(fit="nope"),  # type: ignore[arg-type]
        lambda: ConvertRequest(span=0.0),
        lambda: ConvertRequest(start=-1),
        lambda: ConvertRequest(frames=0),
        lambda: ConvertRequest(convergence="まんなか"),
        lambda: ConvertRequest(projection="nope"),  # type: ignore[arg-type]
        lambda: ConvertRequest(fov=0.0),
        lambda: ConvertRequest(fov=180.0),
    ],
)
def test_invalid_settings_are_rejected(factory: object) -> None:
    with pytest.raises(ValueError):
        factory()  # type: ignore[operator]


def test_convergence_auto_becomes_zero() -> None:
    request = ConvertRequest(convergence="auto")
    assert request.is_auto_convergence
    assert request.convergence_value() == 0.0


def test_convergence_number_is_kept() -> None:
    request = ConvertRequest(convergence="-12.5")
    assert not request.is_auto_convergence
    assert request.convergence_value() == -12.5


def test_submit_points_at_the_source_without_copying_it(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source = _broken_source(tmp_path)

    job = store.submit(source, ConvertRequest(frames=1))

    assert job.status == "queued"
    assert job.source_id == source.id
    assert job.source_name == "movie.mp4"
    # Videos do not live under a job, so hundreds of megabytes are not copied each time
    assert not list((tmp_path / "jobs" / job.id).glob("input.*"))
    store.close()


def test_broken_input_fails_the_job_without_killing_the_worker(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for name in ("first.mp4", "second.mp4"):
        store.submit(_broken_source(tmp_path, name), ConvertRequest(frames=1))

    for job in store.all():
        _wait_until_settled(store, job.id)

    assert [job.status for job in store.all()] == ["failed", "failed"]
    assert all(job.error for job in store.all())
    store.close()


def test_missing_source_fails_the_job(tmp_path: Path) -> None:
    """A missing source shows up as a failure instead of crashing."""
    store = _store(tmp_path)
    source = _broken_source(tmp_path)
    job = store.submit(source, ConvertRequest(frames=1))
    SourceStore(tmp_path / "sources").delete(source.id)
    _wait_until_settled(store, job.id)

    assert store.get(job.id) is not None
    assert store.get(job.id).status == "failed"  # type: ignore[union-attr]
    store.close()


def test_cancel_is_rejected_after_the_job_settled(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = store.submit(_broken_source(tmp_path), ConvertRequest(frames=1))
    _wait_until_settled(store, job.id)

    assert not store.cancel(job.id)
    assert not store.cancel("nope")
    store.close()


@pytest.mark.skipif(not SAMPLE.exists(), reason="サンプル動画が無い")
def test_cancel_stops_the_conversion_and_leaves_no_output(tmp_path: Path) -> None:
    """A cancelled job leaves no partial video, and nothing matching the naming convention."""
    sources = SourceStore(tmp_path / "sources")
    staged = tmp_path / "staged.upload"
    staged.write_bytes(SAMPLE.read_bytes())
    source = sources.add(SAMPLE.name, staged)
    store = JobStore(tmp_path / "jobs", sources)

    job = store.submit(source, ConvertRequest(layout="tb", display="go"))
    deadline = time.time() + 60.0
    while time.time() < deadline:
        current = store.get(job.id)
        assert current is not None
        if current.status == "running" and current.done_frames >= 1:
            break
        time.sleep(0.05)

    assert store.cancel(job.id)
    _wait_until_settled(store, job.id)

    settled = store.get(job.id)
    assert settled is not None
    assert settled.status == "cancelled"
    assert settled.output_name is None
    assert list((tmp_path / "jobs" / job.id).glob("*.mp4")) == []
    store.close()


def test_result_path_is_none_until_the_job_is_done(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = store.submit(_broken_source(tmp_path), ConvertRequest(frames=1))
    _wait_until_settled(store, job.id)

    assert store.result_path(job.id, "movie_qs5x9a1.777.mp4") is None
    store.close()


def test_delete_removes_the_directory(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = store.submit(_broken_source(tmp_path), ConvertRequest(frames=1))
    _wait_until_settled(store, job.id)

    assert store.delete(job.id)
    assert not (tmp_path / "jobs" / job.id).exists()
    assert store.get(job.id) is None
    store.close()


def test_uses_source_only_while_the_job_is_unfinished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deleting a source mid-conversion fails it partway, so this is checked before deleting.

    Conversion itself is stubbed: with the real thing, the window for catching it "in flight" is
    too short to observe the true case.
    """
    running = threading.Event()
    finish = threading.Event()

    def fake_convert(
        options: ConvertOptions,
        *,
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        running.set()
        finish.wait(timeout=10.0)

    monkeypatch.setattr("lkg_quilt_converter.jobs.convert", fake_convert)
    # Plant the source first: JobStore's SourceStore reads at startup, so a source added later
    # fails as "not found" and never reaches conversion
    source = _broken_source(tmp_path)
    store = _store(tmp_path)
    job = store.submit(source, ConvertRequest(frames=1))

    assert running.wait(timeout=10.0)
    assert store.uses_source(source.id)
    assert not store.uses_source("nope")

    finish.set()
    _wait_until_settled(store, job.id)
    assert not store.uses_source(source.id)
    store.close()


def test_restore_marks_interrupted_jobs_as_failed(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    directory = root / "abc123"
    directory.mkdir(parents=True)
    _write_state(directory, status="running")

    restored = JobStore(root, SourceStore(tmp_path / "sources")).get("abc123")
    assert restored is not None
    assert restored.status == "failed"
    assert restored.error == "サーバーの再起動で中断した"


def test_progress_is_zero_before_the_total_is_known() -> None:
    job = Job(
        id="x",
        source_id="s",
        source_name="movie.mp4",
        status="running",
        request=ConvertRequest(),
        created_at=0.0,
    )
    assert job.progress == 0.0


def _write_state(directory: Path, *, status: str) -> None:
    job = Job(
        id=directory.name,
        source_id="s",
        source_name="movie.mp4",
        status=status,  # type: ignore[arg-type]
        request=ConvertRequest(),
        created_at=0.0,
    )
    (directory / "job.json").write_text(json.dumps(asdict(job), ensure_ascii=False))


def _wait_until_settled(store: JobStore, job_id: str, *, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = store.get(job_id)
        if job is not None and job.status in ("done", "failed", "cancelled"):
            return
        time.sleep(0.05)
    raise AssertionError(f"{job_id} が終わらなかった")
