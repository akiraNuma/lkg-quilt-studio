"""Shaping the input stereo video: splitting the eyes and fitting them into one quilt tile."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast, get_args

import cv2
import numpy as np

from .video import Frame

StereoLayout = Literal["sbs", "sbs-half", "tb", "tb-half", "separate"]

LAYOUTS: tuple[str, ...] = get_args(StereoLayout)

FitMode = Literal["pad", "crop"]
"""How to fit an input whose aspect ratio differs from the tile. crop cuts, pad adds margins.

crop is the default. It enlarges the cropped region to fill the screen, which scales disparity by
the same factor and produces stronger depth.
"""

FIT_MODES: tuple[str, ...] = get_args(FitMode)

# The half layouts store one eye squeezed horizontally (or vertically). Undo it with pixel aspect
PIXEL_ASPECT: dict[str, float] = {
    "sbs": 1.0,
    "sbs-half": 2.0,
    "tb": 1.0,
    "tb-half": 0.5,
    "separate": 1.0,
}


def split_stereo(frame: Frame, layout: StereoLayout) -> tuple[Frame, Frame]:
    """Split one frame into the left and right eye."""
    height, width = frame.shape[:2]
    if layout in ("sbs", "sbs-half"):
        if width % 2:
            raise ValueError(f"a side-by-side input needs an even width ({width})")
        middle = width // 2
        return frame[:, :middle], frame[:, middle:]
    if layout in ("tb", "tb-half"):
        if height % 2:
            raise ValueError(f"a top-and-bottom input needs an even height ({height})")
        middle = height // 2
        return frame[:middle], frame[middle:]
    raise ValueError(f"{layout} cannot split the eyes out of a single video")


def guess_layout(frames: Sequence[Frame]) -> StereoLayout | None:
    """Guess how the eyes are arranged from a few frames. Returns None when undecidable.

    In a stereo pair the two halves are the same picture offset by disparity, so their mean
    absolute difference is far smaller than for unrelated pictures. Comparing a horizontal split
    against a vertical one therefore reveals the arrangement. Individual frames can look similar
    by chance, so decide on the average across several frames.

    The squeezed layouts (`sbs-half` / `tb-half`) split the same way and differ only in aspect
    ratio, so they are told apart by whether one eye's aspect ratio looks implausible.
    """
    scores = [_halves_difference(frame) for frame in frames if min(frame.shape[:2]) >= 2]
    if not scores:
        return None
    side_by_side = float(np.mean([score[0] for score in scores]))
    top_bottom = float(np.mean([score[1] for score in scores]))

    # Unless one split falls below 60% of the other, the input cannot be called stereo
    # (an ordinary 2D video splits into unrelated pictures either way, so both stay large)
    if min(side_by_side, top_bottom) > 0.6 * max(side_by_side, top_bottom):
        return None
    height, width = frames[0].shape[:2]
    if side_by_side < top_bottom:
        # The closer one eye is to square, the more it is squeezed. Half of 16:9 is 8:9
        return "sbs-half" if (width / 2) / height < 1.2 else "sbs"
    return "tb-half" if width / (height / 2) > 2.4 else "tb"


def _halves_difference(frame: Frame) -> tuple[float, float]:
    """Return (horizontal split difference, vertical split difference) as mean absolute error."""
    height, width = frame.shape[:2]
    values = frame.astype(np.float32)
    return (
        float(np.abs(values[:, : width // 2] - values[:, width // 2 :]).mean()),
        float(np.abs(values[: height // 2] - values[height // 2 :]).mean()),
    )


@dataclass(frozen=True)
class TileFit:
    """The mapping from one input frame into one tile. Both eyes use the same one."""

    source: tuple[int, int, int, int]
    """The rectangle cropped from the input (x, y, width, height)."""

    content_size: tuple[int, int]
    """The size the picture occupies inside the tile (width, height).

    Disparity estimation and view synthesis run at this resolution.
    """

    offset: tuple[int, int]
    """The top-left coordinate where the picture sits inside the tile (x, y)."""

    tile_size: tuple[int, int]
    """One tile's pixel dimensions (width, height)."""

    @property
    def padded(self) -> bool:
        return self.content_size != self.tile_size


def crop_rect(
    width: int, height: int, pixel_aspect: float, target_aspect: float
) -> tuple[int, int, int, int]:
    """Return the centred crop (x, y, width, height) whose displayed aspect matches
    `target_aspect`.
    """
    if width < 1 or height < 1:
        raise ValueError(f"invalid size ({width}x{height})")
    if pixel_aspect <= 0 or target_aspect <= 0:
        raise ValueError(
            f"aspect ratios must be positive (pixel={pixel_aspect} target={target_aspect})"
        )

    displayed = width * pixel_aspect / height
    if displayed > target_aspect:
        cropped = max(1, min(width, round(height * target_aspect / pixel_aspect)))
        return (width - cropped) // 2, 0, cropped, height
    cropped = max(1, min(height, round(width * pixel_aspect / target_aspect)))
    return 0, (height - cropped) // 2, width, cropped


def plan_fit(
    width: int,
    height: int,
    *,
    pixel_aspect: float,
    tile_size: tuple[int, int],
    tile_aspect: float,
    mode: FitMode,
) -> TileFit:
    """Decide the fit from the input size and the tile specification.

    A tile's pixel aspect ratio (the ratio of `tile_size`) and its displayed aspect ratio
    (`tile_aspect`) are not the same. Looking Glass Go divides 4092x4092 into 11x6, so a tile is
    372x682 pixels, yet it displays as 0.5625 (portrait). Padding only comes out right when it is
    computed from the displayed ratio.
    """
    tile_width, tile_height = tile_size
    if tile_width < 1 or tile_height < 1:
        raise ValueError(f"invalid tile size ({tile_width}x{tile_height})")
    if mode == "crop":
        return TileFit(
            source=crop_rect(width, height, pixel_aspect, tile_aspect),
            content_size=tile_size,
            offset=(0, 0),
            tile_size=tile_size,
        )
    if width < 1 or height < 1:
        raise ValueError(f"invalid size ({width}x{height})")
    if pixel_aspect <= 0 or tile_aspect <= 0:
        raise ValueError(
            f"aspect ratios must be positive (pixel={pixel_aspect} tile={tile_aspect})"
        )

    displayed = width * pixel_aspect / height
    if displayed > tile_aspect:
        inner_height = max(1, min(tile_height, round(tile_height * tile_aspect / displayed)))
        content = (tile_width, inner_height)
        offset = (0, (tile_height - inner_height) // 2)
    else:
        inner_width = max(1, min(tile_width, round(tile_width * displayed / tile_aspect)))
        content = (inner_width, tile_height)
        offset = ((tile_width - inner_width) // 2, 0)
    return TileFit(
        source=(0, 0, width, height),
        content_size=content,
        offset=offset,
        tile_size=tile_size,
    )


def fit_content(image: Frame, fit: TileFit) -> Frame:
    """Crop the input and scale it to `content_size`. Padding is not added yet.

    Disparity estimation and view synthesis run without padding. Black padding is identical in
    both eyes, so stereo matching cannot determine its disparity, and it also throws off the
    automatic convergence plane (the median disparity).
    """
    x, y, width, height = fit.source
    content_width, content_height = fit.content_size
    cropped = image[y : y + height, x : x + width]
    # INTER_AREA when shrinking, INTER_CUBIC when enlarging. Some inputs shrink only vertically
    # (tb-half), so decide on area rather than width alone
    shrinking = width * height > content_width * content_height
    interpolation = cv2.INTER_AREA if shrinking else cv2.INTER_CUBIC
    # cv2's type stubs do not preserve dtype, so re-read the return value we know stays rgb24
    return cast(Frame, cv2.resize(cropped, fit.content_size, interpolation=interpolation))


def pad_to_tile(image: Frame, fit: TileFit) -> Frame:
    """Fit a synthesized picture to the tile size. Passes through when no padding is needed."""
    if not fit.padded:
        return image
    tile_width, tile_height = fit.tile_size
    content_width, content_height = fit.content_size
    x, y = fit.offset
    tile = np.zeros((tile_height, tile_width, 3), dtype=image.dtype)
    tile[y : y + content_height, x : x + content_width] = image
    return cast(Frame, tile)
