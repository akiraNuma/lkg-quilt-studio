"""Command-line entry point."""

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
            print(f"wrote {options.output}", file=sys.stderr)
    # cv2.error sits directly under Exception and inherits neither OSError nor ValueError
    except cv2.error as failure:
        print(f"error: OpenCV failed: {failure}", file=sys.stderr)
        return 2
    # FileNotFoundError derives from OSError; a full disk or missing permission lands here too
    except (ValueError, FfmpegError, OSError) as failure:
        print(f"error: {failure}", file=sys.stderr)
        return 2
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lkg-quilt-converter",
        description="Convert stereo video into a quilt for Looking Glass",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_common(subparsers.add_parser("convert", help="write the quilt video"))
    _add_common(subparsers.add_parser("frame", help="write a single frame as a quilt PNG"))
    return parser


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", type=Path, help="the input stereo video")
    parser.add_argument(
        "--right", type=Path, default=None, help="the right-eye video (--layout separate)"
    )
    parser.add_argument("--output-dir", type=Path, default=Path("out"), help="output directory")
    parser.add_argument(
        "--stem", default=None, help="stem of the output filename (defaults to the input name)"
    )

    layout = parser.add_argument_group("input arrangement")
    layout.add_argument(
        "--layout", choices=LAYOUTS, default="sbs", help="how the eyes are arranged"
    )
    layout.add_argument("--swap-eyes", action="store_true", help="swap the eyes")
    layout.add_argument(
        "--projection",
        choices=PROJECTIONS,
        default="flat",
        help="how the input was captured; fisheye flattens VR180 before estimating disparity",
    )
    layout.add_argument(
        "--fov",
        type=float,
        default=DEFAULT_FOV,
        help="horizontal field of view in degrees when flattening fisheye;"
        " narrower uses only the centre and distorts less",
    )
    layout.add_argument(
        "--fit",
        choices=FIT_MODES,
        default="crop",
        help="how to fit an aspect ratio differing from the tile; pad adds margins, crop cuts",
    )
    layout.add_argument("--start", type=int, default=0, help="first frame number")
    layout.add_argument("--frames", type=int, default=None, help="how many frames to process")

    quilt = parser.add_argument_group("quilt layout")
    quilt.add_argument("--display", choices=sorted(PRESETS), default="16", help="device preset")
    quilt.add_argument("--columns", type=int, default=None, help="columns (overrides the preset)")
    quilt.add_argument("--rows", type=int, default=None, help="rows (overrides the preset)")
    quilt.add_argument("--quilt-width", type=int, default=None, help="width of the whole quilt")
    quilt.add_argument("--quilt-height", type=int, default=None, help="height of the whole quilt")
    quilt.add_argument("--aspect", type=float, default=None, help="aspect ratio of one tile")

    views = parser.add_argument_group("view synthesis")
    views.add_argument(
        "--span",
        type=float,
        default=2.0,
        help="the view span; 1.0 spans the two cameras,"
        " larger extrapolates and increases disparity",
    )
    views.add_argument(
        "--convergence",
        default="auto",
        help="disparity of the zero-disparity plane in pixels;"
        " auto takes the median of the first frame",
    )
    views.add_argument(
        "--crack-width", type=int, default=2, help="width of a gap not treated as an occlusion"
    )
    views.add_argument(
        "--consistency-tolerance",
        type=float,
        default=1.0,
        help="disparity tolerance of the occlusion test;"
        " accepted fully up to this, zero at twice it",
    )
    views.add_argument(
        "--inpaint-radius", type=int, default=3, help="reference radius for hole filling"
    )

    depth = parser.add_argument_group("disparity estimation")
    depth.add_argument(
        "--max-disparity",
        type=int,
        default=128,
        help="width of the disparity search; a multiple of 16, below the quilt tile width",
    )
    depth.add_argument(
        "--min-disparity",
        type=int,
        default=-64,
        help="bottom of the disparity search; 0 cannot find surfaces in front of the screen",
    )
    depth.add_argument("--block-size", type=int, default=5, help="matching window size (odd)")
    depth.add_argument("--downscale", type=int, default=1, help="downscale factor for estimation")
    depth.add_argument("--wls-lambda", type=float, default=8000.0, help="WLS smoothing strength")
    depth.add_argument(
        "--wls-sigma", type=float, default=1.5, help="how strongly WLS follows colour"
    )
    depth.add_argument(
        "--temporal-weight",
        type=float,
        default=0.35,
        help="weight of the current frame (smaller is smoother)",
    )
    depth.add_argument(
        "--temporal-threshold",
        type=float,
        default=4.0,
        help="skip smoothing beyond this difference",
    )

    output = parser.add_argument_group("output")
    output.add_argument("--crf", type=int, default=20, help="libx264 CRF")
    output.add_argument("--preset", default="slow", help="libx264 preset")
    output.add_argument("--no-audio", action="store_true", help="do not carry the audio over")
    output.add_argument(
        "--work-dir", type=Path, default=None, help="where to keep the disparity cache"
    )


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
        raise ValueError(f"--convergence takes a number or auto (received: {value})") from invalid


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
    # cv2.imwrite assumes BGR order, so passing rgb24 as is swaps the colours
    if not cv2.imwrite(str(path), cv2.cvtColor(quilt, cv2.COLOR_RGB2BGR)):
        raise ValueError(f"could not write {path}")
