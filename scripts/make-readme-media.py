"""Rebuild the figures and GIF shown in the README.

They are conversion output, so rebuild them after changing the pipeline.
Usage (from the repository root; prepare the source with scripts/fetch-sample.sh):

    converter/.venv/bin/python scripts/make-readme-media.py

Run it with the Python in converter/.venv. cv2, numpy, and the editable install of
lkg_quilt_converter exist only there.

Labels are written in English so README.md and README.ja.md share one image rather than one per
language (cv2.putText can only draw ASCII anyway).
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

import cv2
import numpy as np
from lkg_quilt_converter.disparity import DisparityParams, SgbmDisparityEstimator
from lkg_quilt_converter.pipeline import ConvertOptions, render_single_frame
from lkg_quilt_converter.quilt import PRESETS
from lkg_quilt_converter.stereo import PIXEL_ASPECT, fit_content, plan_fit, split_stereo
from lkg_quilt_converter.video import Frame, probe, read_frames

ROOT = Path(__file__).resolve().parents[1]
DISPLAY = "go"
LAYOUT = "tb"
SPAN = 1.2
CARD = (255, 255, 255)
INK = (47, 41, 36)  # BGR, matching GitHub's body colour #24292f
LABEL = cv2.FONT_HERSHEY_DUPLEX
PANEL = 300
"""Height in pixels of each panel's image area, so the row lines up side by side."""

BAR = 24
"""Height of the label bar. A panel's image area sits below it."""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "samples/bbb_stereo_tb.mp4")
    parser.add_argument("--frame", type=int, default=0, help="which frame of the source to use")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/media")
    args = parser.parse_args()

    if not args.source.exists():
        print(f"no source: {args.source} (run scripts/fetch-sample.sh)", file=sys.stderr)
        return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)

    options = ConvertOptions(
        source=args.source,
        # Only one frame is drawn, so the output path is unused; ConvertOptions merely requires
        # it. Keep it out of the output directory so it never points inside tracked files
        output=Path("unused.mp4"),
        spec=PRESETS[DISPLAY],
        layout=LAYOUT,
        span=SPAN,
        start=args.frame,
    )
    quilt = render_single_frame(options)
    left, right = eye_frames(args.source, args.frame)

    write_wiggle(quilt, args.output_dir / "wiggle.gif")
    write_pipeline(left, right, quilt, args.output_dir / "pipeline.jpg")
    return 0


def eye_frames(source: Path, index: int) -> tuple[Frame, Frame]:
    """Return the left and right eye after fitting to the tile, exactly what the estimator sees.

    The fit is decided with the same arguments as the pipeline's `_FlatFraming`. Change this when
    that changes.
    """
    info = probe(source)
    reader = read_frames(info, start=index, count=1)
    try:
        frame = next(reader)
    finally:
        reader.close()
    left, right = split_stereo(frame, LAYOUT)
    spec = PRESETS[DISPLAY]
    fit = plan_fit(
        left.shape[1],
        left.shape[0],
        pixel_aspect=PIXEL_ASPECT[LAYOUT],
        tile_size=spec.tile_size,
        tile_aspect=spec.aspect,
        mode="crop",
    )
    return fit_content(left, fit), fit_content(right, fit)


def write_wiggle(quilt: Frame, path: Path, *, width: int = 300, samples: int = 11) -> None:
    """A GIF cycling through the quilt's views, the closest still substitute for the hardware.

    All 66 views one by one push the GIF past 3 MB, and GIF compresses a high-frequency picture
    such as grass poorly, so it is thinned to 11 views including both ends, giving 20 frames.
    """
    spec = PRESETS[DISPLAY]
    tile_width, tile_height = spec.tile_size
    height = round(width * tile_height / tile_width / 2) * 2
    views = sweep_views(spec.view_count, samples)

    with tempfile.TemporaryDirectory() as work:
        for position, index in enumerate(views):
            x, y = spec.tile_origin(index)
            tile = quilt[y : y + tile_height, x : x + tile_width]
            save(
                Path(work) / f"{position:03d}.png",
                cv2.resize(to_bgr(tile), (width, height), interpolation=cv2.INTER_AREA),
            )
        palette = f"{work}/palette.png"
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-framerate",
                "12",
                "-i",
                f"{work}/%03d.png",
                "-vf",
                "palettegen=max_colors=128:stats_mode=full",
                "-y",
                palette,
            ]
        )
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-framerate",
                "12",
                "-i",
                f"{work}/%03d.png",
                "-i",
                palette,
                "-lavfi",
                "paletteuse=dither=bayer:bayer_scale=3",
                "-loop",
                "0",
                "-y",
                str(path),
            ]
        )
    report(path, f"{len(views)} frames / {width}x{height}")


def sweep_views(count: int, samples: int) -> list[int]:
    """Return evenly thinned view indices that turn around at the ends.

    Both extremes (view 0 and the last view) are always included. The extrapolated edge views are
    where hole filling looks rough, so a GIF that hides them would flatter the hardware.
    """
    if count < 2 or not 2 <= samples <= count:
        raise ValueError(f"invalid view thinning (count={count} samples={samples})")
    picks = [round(position * (count - 1) / (samples - 1)) for position in range(samples)]
    return picks + picks[-2:0:-1]


def write_pipeline(left: Frame, right: Frame, quilt: Frame, path: Path) -> None:
    """A figure placing stereo input, disparity, and the quilt in one row of equal-height panels.

    Disparity is computed before the colour order is swapped: the estimator expects rgb24.
    """
    spec = PRESETS[DISPLAY]
    depth = colorize(disparity(left, right))
    eyes = beside([scaled(to_bgr(left), PANEL), scaled(to_bgr(right), PANEL)], gap=6)
    figure = row(
        [
            labelled(eyes, "Stereo input (left / right)"),
            labelled(scaled(depth, PANEL), "Disparity"),
            labelled(
                scaled(to_bgr(quilt), PANEL),
                f"Quilt {spec.columns}x{spec.rows} ({spec.view_count} views)",
            ),
        ],
        captions=["stereo matching", "view synthesis"],
    )
    save(path, figure, cv2.IMWRITE_JPEG_QUALITY, 92)
    report(path, f"{figure.shape[1]}x{figure.shape[0]}")


def disparity(left: Frame, right: Frame) -> np.ndarray:
    return cast(np.ndarray, SgbmDisparityEstimator(DisparityParams()).estimate(left, right))


def colorize(values: np.ndarray) -> np.ndarray:
    """Map disparity to colour.

    Stretched over the 5th-95th percentile so outliers do not flatten it.
    """
    low, high = np.percentile(values, (5, 95))
    span = max(high - low, 1e-6)
    normalized = np.clip((values - low) / span, 0.0, 1.0)
    # cv2's type stubs return Any, so re-read it as the type we know it is
    return cast(
        np.ndarray, cv2.applyColorMap((normalized * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    )


def scaled(image: np.ndarray, height: int) -> np.ndarray:
    width = round(height * image.shape[1] / image.shape[0])
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)


def labelled(image: np.ndarray, text: str) -> np.ndarray:
    """Add a label bar above the image."""
    height, width = image.shape[:2]
    card = np.full((height + BAR, width, 3), CARD, dtype=np.uint8)
    card[BAR:] = image
    cv2.putText(card, text, (0, BAR - 9), LABEL, 0.4, INK, 1, cv2.LINE_AA)
    return card


def beside(images: list[np.ndarray], *, gap: int) -> np.ndarray:
    height = max(image.shape[0] for image in images)
    width = sum(image.shape[1] for image in images) + gap * (len(images) - 1)
    card = np.full((height, width, 3), CARD, dtype=np.uint8)
    left = 0
    for image in images:
        card[: image.shape[0], left : left + image.shape[1]] = image
        left += image.shape[1] + gap
    return card


def row(panels: list[np.ndarray], *, captions: list[str], gap: int = 92) -> np.ndarray:
    """Place panels in a row with an arrow and a step name between them, the arrow centred on
    the image area.
    """
    margin = 14
    height = max(panel.shape[0] for panel in panels) + margin * 2
    width = sum(panel.shape[1] for panel in panels) + gap * (len(panels) - 1) + margin * 2
    card = np.full((height, width, 3), CARD, dtype=np.uint8)
    middle = margin + BAR + PANEL // 2
    left = margin
    for position, panel in enumerate(panels):
        card[margin : margin + panel.shape[0], left : left + panel.shape[1]] = panel
        left += panel.shape[1]
        if position < len(captions):
            cv2.arrowedLine(
                card,
                (left + 14, middle),
                (left + gap - 14, middle),
                INK,
                1,
                cv2.LINE_AA,
                tipLength=0.22,
            )
            text = captions[position]
            (text_width, _), _ = cv2.getTextSize(text, LABEL, 0.36, 1)
            cv2.putText(
                card,
                text,
                (left + gap // 2 - text_width // 2, middle - 12),
                LABEL,
                0.36,
                INK,
                1,
                cv2.LINE_AA,
            )
            left += gap
    return card


def to_bgr(frame: Frame) -> np.ndarray:
    """The pipeline works in rgb24, but cv2 writes assuming BGR order."""
    return cast(np.ndarray, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))


def save(path: Path, image: np.ndarray, *params: int) -> None:
    # cv2.imwrite returns False instead of raising, and moving on silently fails obscurely in
    # ffmpeg
    if not cv2.imwrite(str(path), image, list(params)):
        raise ValueError(f"could not write {path}")


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def report(path: Path, detail: str) -> None:
    shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    print(f"wrote {shown} ({detail} / {path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    sys.exit(main())
