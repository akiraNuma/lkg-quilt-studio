"""Where uploaded input videos live.

Kept apart from jobs so preview and conversion reuse the same file. Tying storage to a job would
mean re-uploading hundreds of megabytes for every parameter change.
"""

import json
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from .fisheye import Projection, guess_projection
from .stereo import StereoLayout, guess_layout, split_stereo
from .video import FfmpegError, VideoInfo, probe, read_frames

STATE_FILE = "source.json"


@dataclass(frozen=True)
class Source:
    """One imported input video. `path` is the file on the server."""

    id: str
    name: str
    width: int
    height: int
    fps: float
    """The Fraction probe returns, reduced to float so it fits in JSON."""

    frame_count: int
    has_audio: bool
    created_at: float = 0.0
    """When it was imported, used to list newest first (absent from old state files, hence 0)."""

    suggested_layout: StereoLayout | None = None
    """The guessed eye arrangement. It can be wrong, so the screen only uses it as an initial
    value.
    """

    suggested_projection: Projection | None = None
    """The guessed projection (flat / fisheye), likewise only an initial value."""

    @property
    def stem(self) -> str:
        return Path(self.name).stem


class SourceStore:
    """Store input videos under `root/<id>/` and their metadata in `source.json`."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._sources: dict[str, Source] = {}
        self._restore()

    def add(self, name: str, staged: Path) -> Source:
        """Import the video at `staged`, a temporary file owned by the caller."""
        source_id = uuid.uuid4().hex
        directory = self._root / source_id
        directory.mkdir(parents=True)
        suffix = Path(name).suffix or ".mp4"
        target = directory / f"input{suffix}"
        staged.replace(target)

        # Reject a broken video here. Carrying it to preview or conversion hides the cause
        try:
            info = probe(target)
        except ValueError, FfmpegError, OSError:
            _remove_tree(directory)
            raise
        layout, projection = _inspect(info)

        source = Source(
            id=source_id,
            name=name,
            width=info.width,
            height=info.height,
            fps=float(info.fps),
            frame_count=info.frame_count,
            has_audio=info.has_audio,
            created_at=time.time(),
            suggested_layout=layout,
            suggested_projection=projection,
        )
        self._write(source)
        return source

    def get(self, source_id: str) -> Source | None:
        with self._lock:
            return self._sources.get(source_id)

    def path(self, source_id: str) -> Path | None:
        """Return the imported video file, or None when it is gone."""
        if self.get(source_id) is None:
            return None
        for path in sorted((self._root / source_id).glob("input.*")):
            return path
        return None

    def all(self) -> list[Source]:
        """Return newest first, which is the order the screen lists them in."""
        with self._lock:
            found = list(self._sources.values())
        return sorted(found, key=lambda source: source.created_at, reverse=True)

    def size(self, source_id: str) -> int:
        """Total size of imported videos in bytes. Hundreds of megabytes accumulate, so the
        screen shows it.
        """
        path = self.path(source_id)
        if path is None:
            return 0
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def delete(self, source_id: str) -> bool:
        with self._lock:
            if self._sources.pop(source_id, None) is None:
                return False
        _remove_tree(self._root / source_id)
        return True

    def _write(self, source: Source) -> None:
        with self._lock:
            self._sources[source.id] = source
        directory = self._root / source.id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / STATE_FILE).write_text(
            json.dumps(asdict(source), ensure_ascii=False, indent=2)
        )

    def _restore(self) -> None:
        for state in sorted(self._root.glob(f"*/{STATE_FILE}")):
            try:
                source = Source(**json.loads(state.read_text()))
            # Ignore an old format or broken JSON: that source is simply unusable, which is
            # harmless
            except ValueError, TypeError:
                continue
            self._sources[source.id] = source


SAMPLE_POSITIONS = (0.2, 0.5, 0.8)
"""Frame positions for reading the eye arrangement, taken from the middle to avoid dark
openings and endings.
"""


def _inspect(info: VideoInfo) -> tuple[StereoLayout | None, Projection | None]:
    """Read a few frames to guess the arrangement and projection.

    Gives up when they cannot be read; the screen lets a person choose instead.
    """
    frames = []
    for position in SAMPLE_POSITIONS:
        index = int(info.frame_count * position) if info.frame_count else 0
        try:
            frames.append(next(read_frames(info, start=index, count=1)))
        except ValueError, FfmpegError, OSError, StopIteration:
            continue
    layout = guess_layout(frames)
    if layout is None or layout == "separate":
        return layout, None
    projection = guess_projection([split_stereo(frame, layout)[0] for frame in frames])
    if projection == "flat":
        return layout, projection
    # A fisheye circle is round in pixels, so the input is not one of the squeezed (half)
    # layouts. Reading a half layout as flat stretches it 2x horizontally (measured: real VR180
    # footage was classified as sbs-half)
    return cast(StereoLayout, layout.removesuffix("-half")), projection


def _remove_tree(directory: Path) -> None:
    shutil.rmtree(directory, ignore_errors=True)
