"""コマンドラインの入口。"""

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import cast

import cv2
import numpy as np

from .dibr import SynthesisParams
from .disparity import DisparityParams
from .fisheye import DEFAULT_FOV, PROJECTIONS, Projection
from .pipeline import ConvertOptions, convert, render_single_frame
from .quilt import PRESETS, QuiltSpec
from .stereo import FIT_MODES, LAYOUTS, FitMode, StereoLayout
from .video import FfmpegError


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        options = _options_from_args(args)
        options.output.parent.mkdir(parents=True, exist_ok=True)
        if args.command == "convert":
            convert(options)
        else:
            _write_png(options.output, render_single_frame(options))
            print(f"{options.output} を書き出した", file=sys.stderr)
    # cv2.error は Exception の直下で、OSError も ValueError も継承しない
    except cv2.error as failure:
        print(f"エラー: OpenCV の処理が失敗した: {failure}", file=sys.stderr)
        return 2
    # FileNotFoundError は OSError の派生。ディスクフルや権限なしもここで受ける
    except (ValueError, FfmpegError, OSError) as failure:
        print(f"エラー: {failure}", file=sys.stderr)
        return 2
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lkg-quilt-converter",
        description="ステレオ動画を Looking Glass 用の quilt へ変換する",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_common(subparsers.add_parser("convert", help="quilt 動画を書き出す"))
    _add_common(subparsers.add_parser("frame", help="1 フレームだけ quilt の PNG を書き出す"))
    return parser


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", type=Path, help="入力のステレオ動画")
    parser.add_argument("--right", type=Path, default=None, help="右眼の動画（--layout separate）")
    parser.add_argument("--output-dir", type=Path, default=Path("out"), help="出力先ディレクトリ")
    parser.add_argument("--stem", default=None, help="出力ファイル名の幹（既定は入力名）")

    layout = parser.add_argument_group("入力の並び")
    layout.add_argument("--layout", choices=LAYOUTS, default="sbs", help="左右の入り方")
    layout.add_argument("--swap-eyes", action="store_true", help="左右を入れ替える")
    layout.add_argument(
        "--projection",
        choices=PROJECTIONS,
        default="flat",
        help="入力の写り方。fisheye は VR180 の魚眼を平面へ直してから視差を取る",
    )
    layout.add_argument(
        "--fov",
        type=float,
        default=DEFAULT_FOV,
        help="魚眼を平面へ直すときの水平視野角（度）。狭くするほど中央だけを使うので歪みが減る",
    )
    layout.add_argument(
        "--fit",
        choices=FIT_MODES,
        default="crop",
        help="タイルと縦横比が違うときの収め方。pad は余白を足し、crop は切り落とす",
    )
    layout.add_argument("--start", type=int, default=0, help="開始フレーム番号")
    layout.add_argument("--frames", type=int, default=None, help="処理するフレーム数")

    quilt = parser.add_argument_group("quilt のレイアウト")
    quilt.add_argument("--display", choices=sorted(PRESETS), default="16", help="機種プリセット")
    quilt.add_argument("--columns", type=int, default=None, help="列数（プリセットを上書き）")
    quilt.add_argument("--rows", type=int, default=None, help="行数（プリセットを上書き）")
    quilt.add_argument("--quilt-width", type=int, default=None, help="quilt 全体の幅")
    quilt.add_argument("--quilt-height", type=int, default=None, help="quilt 全体の高さ")
    quilt.add_argument("--aspect", type=float, default=None, help="タイル 1 枚の縦横比")

    views = parser.add_argument_group("視点合成")
    views.add_argument(
        "--span",
        type=float,
        default=2.0,
        help="視点の広がり。1.0 で左右カメラの間だけ、大きいほど外挿して視差が増える",
    )
    views.add_argument(
        "--convergence",
        default="auto",
        help="視差ゼロにする面の視差（画素）。auto は最初のフレームの中央値",
    )
    views.add_argument("--crack-width", type=int, default=2, help="遮蔽と見なさない隙間の幅")
    views.add_argument(
        "--consistency-tolerance",
        type=float,
        default=1.0,
        help="遮蔽判定の視差の許容差。この差までは完全に採用し、2 倍で 0 になる",
    )
    views.add_argument("--inpaint-radius", type=int, default=3, help="穴埋めの参照半径")

    depth = parser.add_argument_group("視差推定")
    depth.add_argument(
        "--max-disparity",
        type=int,
        default=128,
        help="探索する視差の幅。16 の倍数で、quilt のタイル幅より小さくする",
    )
    depth.add_argument(
        "--min-disparity",
        type=int,
        default=-64,
        help="探索する視差の下端。0 にすると画面より手前に出る面を見つけられない",
    )
    depth.add_argument("--block-size", type=int, default=5, help="マッチングの窓サイズ（奇数）")
    depth.add_argument("--downscale", type=int, default=1, help="縮小して推定する倍率")
    depth.add_argument("--wls-lambda", type=float, default=8000.0, help="WLS の平滑化の強さ")
    depth.add_argument("--wls-sigma", type=float, default=1.5, help="WLS の色の効き")
    depth.add_argument(
        "--temporal-weight", type=float, default=0.35, help="今フレームの重み（小さいほど平滑）"
    )
    depth.add_argument(
        "--temporal-threshold", type=float, default=4.0, help="この差を超えたら平滑化しない"
    )

    output = parser.add_argument_group("書き出し")
    output.add_argument("--crf", type=int, default=20, help="libx264 の CRF")
    output.add_argument("--preset", default="slow", help="libx264 のプリセット")
    output.add_argument("--no-audio", action="store_true", help="音声を引き継がない")
    output.add_argument("--work-dir", type=Path, default=None, help="視差キャッシュの置き場所")


def _options_from_args(args: argparse.Namespace) -> ConvertOptions:
    spec = _spec_from_args(args)
    extension = "mp4" if args.command == "convert" else "png"
    stem = args.stem or args.source.stem

    synthesis = SynthesisParams(
        crack_width=args.crack_width,
        convergence=_convergence(args.convergence),
        consistency_tolerance=args.consistency_tolerance,
        inpaint_radius=args.inpaint_radius,
    )
    return ConvertOptions(
        source=args.source,
        output=args.output_dir / spec.filename(stem, extension),
        spec=spec,
        layout=cast(StereoLayout, args.layout),
        fit=cast(FitMode, args.fit),
        projection=cast(Projection, args.projection),
        fov=args.fov,
        right_source=args.right,
        swap_eyes=args.swap_eyes,
        start=args.start,
        frames=args.frames,
        span=args.span,
        disparity=DisparityParams(
            max_disparity=args.max_disparity,
            min_disparity=args.min_disparity,
            block_size=args.block_size,
            downscale=args.downscale,
            wls_lambda=args.wls_lambda,
            wls_sigma=args.wls_sigma,
            temporal_weight=args.temporal_weight,
            temporal_threshold=args.temporal_threshold,
        ),
        synthesis=synthesis,
        auto_convergence=args.convergence == "auto",
        crf=args.crf,
        preset=args.preset,
        work_dir=args.work_dir,
        copy_audio=not args.no_audio,
    )


def _convergence(value: str) -> float:
    if value == "auto":
        return 0.0
    try:
        return float(value)
    except ValueError as invalid:
        raise ValueError(f"--convergence は数値か auto（受け取った値: {value}）") from invalid


def _spec_from_args(args: argparse.Namespace) -> QuiltSpec:
    preset = PRESETS[args.display]
    return replace(
        preset,
        columns=args.columns if args.columns is not None else preset.columns,
        rows=args.rows if args.rows is not None else preset.rows,
        width=args.quilt_width if args.quilt_width is not None else preset.width,
        height=args.quilt_height if args.quilt_height is not None else preset.height,
        aspect=args.aspect if args.aspect is not None else preset.aspect,
    )


def _write_png(path: Path, quilt: np.ndarray) -> None:
    # cv2.imwrite は BGR 順を前提にするので、rgb24 のまま渡すと色が入れ替わる
    if not cv2.imwrite(str(path), cv2.cvtColor(quilt, cv2.COLOR_RGB2BGR)):
        raise ValueError(f"{path} に書き出せなかった")
