"""変換パイプラインの組み立て。視差推定 → 視点合成 → quilt 合成 → エンコード。"""

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
    """1 回の変換に必要な設定のすべて。"""

    source: Path
    output: Path
    spec: QuiltSpec
    layout: StereoLayout
    fit: FitMode = "crop"
    projection: Projection = "flat"
    fov: float = DEFAULT_FOV
    """魚眼を平面へ直すときの水平視野角（度）。`projection="flat"` では使わない。"""

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
"""(書き終えたフレーム数, 予定のフレーム数) を受け取る。総数が不明なら 0 が来る。"""


def convert(options: ConvertOptions, *, progress: ProgressCallback | None = None) -> Path:
    """quilt 動画を書き出し、その出力パスを返す。

    `progress` を渡すと、フレームを 1 枚書くたびに呼ばれる。既定は標準エラーへの表示。
    """
    report = progress if progress is not None else _report
    sources = _open_sources(options)
    if not (options.copy_audio and sources[0].has_audio):
        _encode_quilt(options, sources, options.output, progress=report)
        _report_done(options.output)
        return options.output

    # 音声は書き出し後に重ねる。映像の尺が確定していないと -t で切れない。
    # 中間ファイルは出力と同じ場所の一時ディレクトリに置く。出力先に直接置くと、
    # 失敗したときに quilt の名前規約に一致するファイル（ビューアが開けてしまう）が残る
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
            # 変換し終えた映像は絶対に捨てない。捨てると全フレームやり直しになる
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
    """全フレームを quilt にして書き出し、書いたフレーム数を返す。"""
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
    """1 フレームだけ quilt に合成して返す。画質の当たりを取るのに使う。"""
    return preview_frame(options)[0]


def preview_frame(options: ConvertOptions) -> tuple[Frame, float]:
    """1 フレームの quilt と、そのフレームで決まった収束面の視差を返す。

    収束面を `auto` にしていると値はフレームごとに変わる。画面で詰めた値を
    そのまま焼き込めるよう、使われた値を返す。
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
    """フレーム 1 枚を quilt 1 枚に変換する。視差の中間成果はここでキャッシュする。

    視点合成はフレームの 95% を占める（Go の 66 視点で実測 1.60 s / 1.66 s）ので、
    視点ごとに並列に走らせる。視点はお互いに依存しないので順番は結果に効かない。
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
        """実際に使った収束面の視差。`auto` なら最初のフレームから決めた値。"""
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
            # キャッシュから読んだ分も推定器へ戻す。渡さないと次のフレームで
            # 時間方向の平滑化の連鎖が切れて、そこだけ視差が跳ねる
            disparity = cached
            self._estimator.seed(disparity)

        if index == 0:
            _report_disparity(fitted_left, fitted_right, disparity)
            if self._options.auto_convergence:
                # 収束面はフレームごとに求め直すと場面全体が前後に泳ぐので、最初の 1 枚で固定する
                self._synthesis = replace(self._synthesis, convergence=float(np.median(disparity)))

        synthesizer = ViewSynthesizer(fitted_left, fitted_right, disparity, self._synthesis)

        def compose(position: float) -> Frame:
            return framing.to_tile(synthesizer.view(position))

        return self._options.spec.compose(list(self._pool.map(compose, self._positions)))


def _view_workers() -> int:
    """視点合成に使うスレッド数。cv2 と numpy は GIL を離すので実測で 4.5 倍まで縮んだ。"""
    return max(os.cpu_count() or 1, 1)


class _Framing(Protocol):
    """入力フレーム 1 枚をタイル 1 枚の絵へ収める写像。左右の眼で同じ設定を使う。"""

    def prepare(self, left: Frame, right: Frame) -> tuple[Frame, Frame]:
        """視差推定と視点合成を行う解像度まで左右を整える。"""
        ...

    def to_tile(self, view: Frame) -> Frame:
        """合成した視点をタイルの大きさに合わせる。"""
        ...


class _FlatFraming:
    """平面のステレオ対を切り出し（または余白を足し）てタイルへ収める。"""

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
    """魚眼（VR180）を片眼ずつ透視投影へ直してタイルへ収める。

    円の中心は片眼ごとに測る。左右で光軸の位置が違う素材（実測で縦に 1.0 px ずれていた）でも、
    それぞれの中心を基準に写すのでずれが残らない。
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
        # 再投影がタイルの大きさで出るので余白は要らない
        return view


def _build_framing(options: ConvertOptions, sources: Sequence[VideoInfo], left: Frame) -> _Framing:
    if options.projection == "flat":
        return _FlatFraming(options, left.shape[1], left.shape[0])
    return _FisheyeFraming(options, _detect_circles(options, sources))


SAMPLE_POSITIONS = (0.2, 0.5, 0.8)
"""魚眼の円を測るコマの位置。真っ暗な冒頭や終端を避けるため中ほどから取る。"""


def _detect_circles(
    options: ConvertOptions, sources: Sequence[VideoInfo]
) -> tuple[FisheyeCircle, FisheyeCircle]:
    """動画の何コマかから左右の魚眼の円を測る。

    黒枠は動画の間ずっと同じ位置にあるので、離れた 3 コマの明るいほうを取れば足りる。
    1 コマだけだと暗い場面で被写体の影を黒枠と読み違える。
    """
    lefts: list[Frame] = []
    rights: list[Frame] = []
    for position in SAMPLE_POSITIONS:
        index = int(sources[0].frame_count * position) if sources[0].frame_count else 0
        try:
            frames = tuple(next(read_frames(info, start=index, count=1)) for info in sources)
        # 読めないコマは飛ばす。3 コマのうち 1 コマでも読めれば測れる
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
    """フレームごとの視差を `work_dir` に置く。設定が変わったキャッシュは使わない。"""

    def __init__(self, options: ConvertOptions) -> None:
        self._directory: Path | None = None
        if options.work_dir is None:
            return
        directory = options.work_dir / "disparity"
        directory.mkdir(parents=True, exist_ok=True)
        signature = {
            # 同じパスで中身が差し替わったキャッシュを使わないよう、大きさと更新時刻も見る
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
            # float16 で十分（視差は画素単位で数百まで）。フレーム数が多いので容量を優先する
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
    """視差の分布と、それが画像をどれだけ説明できているかを出す。

    左右が逆に入っていても正負の両側を探せば同じくらい画像を説明できてしまう
    （入れ替えた対は「奥行きが反転した場面」の正しいステレオ対になる）。
    絵から機械的には判定できないので、実機で見て `--swap-eyes` を切り替える。
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
