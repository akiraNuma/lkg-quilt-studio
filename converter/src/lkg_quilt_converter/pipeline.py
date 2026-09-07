"""Assembling the conversion pipeline: disparity, view synthesis, quilt composition, encoding."""

import json
import os
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from dataclasses import dataclass, field, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol, cast

import numpy as np

from .dibr import SynthesisParams, ViewSynthesizer, view_positions
from .disparity import (
    DisparityEstimator,
    DisparityParams,
    SgbmDisparityEstimator,
    photometric_residual,
)
from .fisheye import (
    DEFAULT_FOV,
    FisheyeCircle,
    Projection,
    detect_circle,
    rectify,
    rectilinear_maps,
)
from .holes import DisparityMap
from .quilt import QuiltSpec
from .stereo import (
    PIXEL_ASPECT,
    FitMode,
    StereoLayout,
    TileFit,
    fit_content,
    pad_to_tile,
    plan_fit,
    split_stereo,
)
from .video import (
    FfmpegError,
    Frame,
    QuiltEncoder,
    VideoInfo,
    mux_audio,
    probe,
    read_frames,
)


@dataclass(frozen=True)
class ConvertOptions:
    """Everything one conversion needs."""

    source: Path
    output: Path
    spec: QuiltSpec
    layout: StereoLayout
    fit: FitMode = "crop"
    projection: Projection = "flat"
    fov: float = DEFAULT_FOV
    """Horizontal field of view in degrees when flattening fisheye. Unused when
    `projection="flat"`.
    """

    right_source: Path | None = None
    swap_eyes: bool = False
    start: int = 0
    frames: int | None = None
    span: float = 2.0
    disparity: DisparityParams = field(default_factory=DisparityParams)
    synthesis: SynthesisParams = field(default_factory=SynthesisParams)
    auto_convergence: bool = True
    crf: int = 20
    preset: str = "slow"
    work_dir: Path | None = None
    copy_audio: bool = True


ProgressCallback = Callable[[int, int], None]
"""Receives (frames written, frames planned). The total arrives as 0 when it is unknown."""


def convert(options: ConvertOptions, *, progress: ProgressCallback | None = None) -> Path:
    """Write the quilt video and return its output path.

    `progress`, when given, is called once per written frame. The default prints to stderr.
    """
    report = progress if progress is not None else _report
    sources = _open_sources(options)
    if not (options.copy_audio and sources[0].has_audio):
        _encode_quilt(options, sources, options.output, progress=report)
        _report_done(options.output)
        return options.output

    # Audio is muxed after writing: -t cannot trim until the video's duration is known.
    # The intermediate file goes in a temporary directory beside the output. Writing it straight
    # to the output directory would leave a file matching the quilt naming convention behind on
    # failure, which the viewer would happily open
    with TemporaryDirectory(dir=options.output.parent) as workspace:
        video_only = Path(workspace) / "video.mp4"
        written = _encode_quilt(options, sources, video_only, faststart=False, progress=report)
        try:
            mux_audio(
                video_only,
                options.source,
                options.output,
                start=float(options.start / sources[0].fps),
                duration=float(written / sources[0].fps),
            )
        except FfmpegError as failure:
            # Never discard finished video. Discarding it means redoing every frame
            options.output.unlink(missing_ok=True)
            video_only.replace(options.output)
            print(f"\n警告: {failure}。映像だけを残す", file=sys.stderr)
    _report_done(options.output)
    return options.output


def _encode_quilt(
    options: ConvertOptions,
    sources: list[VideoInfo],
    output: Path,
    *,
    faststart: bool = True,
    progress: ProgressCallback,
) -> int:
    """Turn every frame into a quilt and return how many frames were written."""
    with ExitStack() as stack:
        readers = [
            stack.enter_context(
                closing(read_frames(info, start=options.start, count=options.frames))
            )
            for info in sources
        ]
        total = _planned_frames(sources[0], options)
        encoder = stack.enter_context(
            QuiltEncoder(
                output,
                width=options.spec.width,
                height=options.spec.height,
                fps=sources[0].fps,
                crf=options.crf,
                preset=options.preset,
                faststart=faststart,
            )
        )
        renderer = stack.enter_context(closing(_Renderer(options, sources)))
        for index, frames in enumerate(zip(*readers, strict=False)):
            encoder.write(renderer.render(index, *_eyes(options, frames)))
            progress(index + 1, total)
        return encoder.frames_written


def render_single_frame(options: ConvertOptions) -> Frame:
    """Compose a single frame into a quilt and return it, for judging quality."""
    return preview_frame(options)[0]


def preview_frame(options: ConvertOptions) -> tuple[Frame, float]:
    """Return one frame's quilt and the convergence disparity chosen for that frame.

    With convergence set to `auto` the value differs per frame. The value actually used is
    returned so the value tuned on screen can be baked in as is.
    """
    sources = _open_sources(options)
    with ExitStack() as stack:
        readers = [
            stack.enter_context(closing(read_frames(info, start=options.start, count=1)))
            for info in sources
        ]
        frames = tuple(next(reader) for reader in readers)
        renderer = stack.enter_context(closing(_Renderer(options, sources)))
        return renderer.render(0, *_eyes(options, frames)), renderer.convergence


class _Renderer:
    """Convert one frame into one quilt, caching the intermediate disparity here.

    View synthesis takes 95% of a frame (measured 1.60 s of 1.66 s for Go's 66 views), so views
    run in parallel. Views do not depend on each other, so their order does not affect the result.
    """

    def __init__(self, options: ConvertOptions, sources: Sequence[VideoInfo]) -> None:
        self._options = options
        self._sources = sources
        self._estimator: DisparityEstimator = SgbmDisparityEstimator(options.disparity)
        self._synthesis = options.synthesis
        self._positions = view_positions(options.spec.view_count, options.span)
        self._cache = _DisparityCache(options)
        self._framing: _Framing | None = None
        self._pool = ThreadPoolExecutor(max_workers=_view_workers(), thread_name_prefix="lkg-view")

    def close(self) -> None:
        self._pool.shutdown(wait=True)

    @property
    def convergence(self) -> float:
        """The convergence disparity actually used. With `auto`, decided from the first frame."""
        return self._synthesis.convergence

    def render(self, index: int, left: Frame, right: Frame) -> Frame:
        framing = self._framing
        if framing is None:
            framing = _build_framing(self._options, self._sources, left)
            self._framing = framing
        fitted_left, fitted_right = framing.prepare(left, right)

        cached = self._cache.load(index)
        if cached is None:
            disparity = self._estimator.estimate(fitted_left, fitted_right)
            self._cache.store(index, disparity)
        else:
            # Feed cached disparity back into the estimator. Without it, the next frame breaks
            # the temporal smoothing chain and disparity jumps at that point
            disparity = cached
            self._estimator.seed(disparity)

        if index == 0:
            _report_disparity(fitted_left, fitted_right, disparity)
            if self._options.auto_convergence:
                # Recomputing convergence every frame makes the whole scene drift back and
                # forth, so fix it on the first frame
                self._synthesis = replace(self._synthesis, convergence=float(np.median(disparity)))

        synthesizer = ViewSynthesizer(fitted_left, fitted_right, disparity, self._synthesis)

        def compose(position: float) -> Frame:
            return framing.to_tile(synthesizer.view(position))

        return self._options.spec.compose(list(self._pool.map(compose, self._positions)))


def _view_workers() -> int:
    """Threads for view synthesis. cv2 and numpy release the GIL, measured 4.5x faster."""
    return max(os.cpu_count() or 1, 1)


class _Framing(Protocol):
    """The mapping from one input frame into one tile. Both eyes use the same settings."""

    def prepare(self, left: Frame, right: Frame) -> tuple[Frame, Frame]:
        """Bring both eyes to the resolution disparity and view synthesis run at."""
        ...

    def to_tile(self, view: Frame) -> Frame:
        """Fit a synthesized view to the tile size."""
        ...


class _FlatFraming:
    """Crop (or pad) a planar stereo pair into the tile."""

    def __init__(self, options: ConvertOptions, width: int, height: int) -> None:
        self._fit = plan_fit(
            width,
            height,
            pixel_aspect=PIXEL_ASPECT[options.layout],
            tile_size=options.spec.tile_size,
            tile_aspect=options.spec.aspect,
            mode=options.fit,
        )
        _report_fit(self._fit)

    def prepare(self, left: Frame, right: Frame) -> tuple[Frame, Frame]:
        return fit_content(left, self._fit), fit_content(right, self._fit)

    def to_tile(self, view: Frame) -> Frame:
        return pad_to_tile(view, self._fit)


class _FisheyeFraming:
    """Flatten fisheye (VR180) per eye to a rectilinear projection and fit it into the tile.

    The circle centre is measured per eye, so footage whose optical axes differ between the eyes
    (measured: 1.0 px vertically) leaves no offset, because each eye maps from its own centre.
    """

    def __init__(
        self, options: ConvertOptions, circles: tuple[FisheyeCircle, FisheyeCircle]
    ) -> None:
        self._maps = tuple(
            rectilinear_maps(
                circle,
                tile_size=options.spec.tile_size,
                tile_aspect=options.spec.aspect,
                fov=options.fov,
            )
            for circle in circles
        )
        _report_circles(circles, options.fov)

    def prepare(self, left: Frame, right: Frame) -> tuple[Frame, Frame]:
        return rectify(left, self._maps[0]), rectify(right, self._maps[1])

    def to_tile(self, view: Frame) -> Frame:
        # The reprojection already comes out at tile size, so no padding is needed
        return view


def _build_framing(options: ConvertOptions, sources: Sequence[VideoInfo], left: Frame) -> _Framing:
    if options.projection == "flat":
        return _FlatFraming(options, left.shape[1], left.shape[0])
    return _FisheyeFraming(options, _detect_circles(options, sources))


SAMPLE_POSITIONS = (0.2, 0.5, 0.8)
"""Frame positions for measuring the fisheye circle, taken from the middle to avoid dark
openings and endings.
"""


def _detect_circles(
    options: ConvertOptions, sources: Sequence[VideoInfo]
) -> tuple[FisheyeCircle, FisheyeCircle]:
    """Measure both fisheye circles from a few frames of the video.

    The black border stays in the same place throughout, so the brighter of three spaced frames
    is enough. A single frame risks mistaking a subject's shadow in a dark scene for the border.
    """
    lefts: list[Frame] = []
    rights: list[Frame] = []
    for position in SAMPLE_POSITIONS:
        index = int(sources[0].frame_count * position) if sources[0].frame_count else 0
        try:
            frames = tuple(next(read_frames(info, start=index, count=1)) for info in sources)
        # Skip unreadable frames; one readable frame out of three is enough to measure
        except FfmpegError, OSError, StopIteration:
            continue
        eye_left, eye_right = _eyes(options, frames)
        lefts.append(eye_left)
        rights.append(eye_right)

    circles = (detect_circle(lefts), detect_circle(rights))
    if circles[0] is None or circles[1] is None:
        raise ValueError(
            "魚眼の円が見つからない（黒い縁が無い）。入力が魚眼でないなら投影を flat にする"
        )
    return (circles[0], circles[1])


class _DisparityCache:
    """Store per-frame disparity under `work_dir`, ignoring caches whose settings changed."""

    def __init__(self, options: ConvertOptions) -> None:
        self._directory: Path | None = None
        if options.work_dir is None:
            return
        directory = options.work_dir / "disparity"
        directory.mkdir(parents=True, exist_ok=True)
        signature = {
            # Also compare size and mtime, so a cache swapped out behind the same path is unused
            "source": _file_signature(options.source),
            "right_source": _file_signature(options.right_source),
            "layout": options.layout,
            "fit": options.fit,
            "swap_eyes": options.swap_eyes,
            "start": options.start,
            "tile_size": list(options.spec.tile_size),
            "aspect": options.spec.aspect,
            "disparity": vars(options.disparity),
        }
        marker = directory / "settings.json"
        if marker.exists() and json.loads(marker.read_text()) != signature:
            print(f"設定が変わったので {directory} の視差キャッシュを作り直す", file=sys.stderr)
            for stale in directory.glob("*.npy"):
                stale.unlink()
        marker.write_text(json.dumps(signature, ensure_ascii=False, indent=2))
        self._directory = directory

    def load(self, index: int) -> DisparityMap | None:
        path = self._path(index)
        if path is None or not path.exists():
            return None
        return cast(DisparityMap, np.load(path).astype(np.float32))

    def store(self, index: int, disparity: DisparityMap) -> None:
        path = self._path(index)
        if path is not None:
            # float16 is enough (disparity reaches a few hundred pixels); with many frames,
            # size wins
            np.save(path, disparity.astype(np.float16))

    def _path(self, index: int) -> Path | None:
        if self._directory is None:
            return None
        return self._directory / f"frame_{index:06d}.npy"


def _file_signature(path: Path | None) -> str | None:
    if path is None:
        return None
    stat = path.stat()
    return f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"


def _report_fit(fit: TileFit) -> None:
    if not fit.padded:
        return
    content_width, content_height = fit.content_size
    tile_width, tile_height = fit.tile_size
    print(
        f"タイル {tile_width}x{tile_height} px に {content_width}x{content_height} px で収める"
        "（縦横比が違うので余白が入る。切り落として画面いっぱいに使うなら --fit crop）",
        file=sys.stderr,
    )


def _report_circles(circles: tuple[FisheyeCircle, FisheyeCircle], fov: float) -> None:
    def describe(circle: FisheyeCircle) -> str:
        return f"中心 ({circle.center_x:.1f}, {circle.center_y:.1f}) 半径 {circle.radius:.1f} px"

    print(
        f"魚眼として読む: 左 {describe(circles[0])} / 右 {describe(circles[1])} / "
        f"水平視野角 {fov:.0f}°",
        file=sys.stderr,
    )


def _report_disparity(left: Frame, right: Frame, disparity: DisparityMap) -> None:
    """Report the disparity distribution and how well it explains the image.

    With both signs searched, swapped eyes explain the image just as well (a swapped pair is a
    valid stereo pair for a scene with reversed depth). No mechanical test on the images decides
    it, so judge on hardware and toggle `--swap-eyes`.
    """
    low, high = np.percentile(disparity, (10, 90))
    print(
        f"視差: 中央値 {float(np.median(disparity)):.2f} px / "
        f"10〜90 パーセンタイル {float(low):.2f}〜{float(high):.2f} px / "
        f"測光残差 {photometric_residual(left, right, disparity):.2f}",
        file=sys.stderr,
    )


def _open_sources(options: ConvertOptions) -> list[VideoInfo]:
    left = probe(options.source)
    if options.layout != "separate":
        if options.right_source is not None:
            raise ValueError(f"layout={options.layout} では右眼の動画を別に渡せない")
        return [left]
    if options.right_source is None:
        raise ValueError("layout=separate では右眼の動画（--right）が必要")
    right = probe(options.right_source)
    if (left.width, left.height) != (right.width, right.height):
        raise ValueError(
            f"左右の解像度が違う: {left.width}x{left.height} / {right.width}x{right.height}"
        )
    if left.fps != right.fps:
        raise ValueError(f"左右のフレームレートが違う: {left.fps} / {right.fps}")
    return [left, right]


def _eyes(options: ConvertOptions, frames: tuple[Frame, ...]) -> tuple[Frame, Frame]:
    left, right = frames if len(frames) == 2 else split_stereo(frames[0], options.layout)
    return (right, left) if options.swap_eyes else (left, right)


def _planned_frames(info: VideoInfo, options: ConvertOptions) -> int:
    available = max(info.frame_count - options.start, 0) if info.frame_count else 0
    if options.frames is None:
        return available
    return min(options.frames, available) if available else options.frames


def _report(done: int, total: int) -> None:
    goal = str(total) if total else "?"
    print(f"\r{done} / {goal} フレーム", end="", file=sys.stderr, flush=True)


def _report_done(output: Path) -> None:
    print(f"\n{output} を書き出した", file=sys.stderr)
