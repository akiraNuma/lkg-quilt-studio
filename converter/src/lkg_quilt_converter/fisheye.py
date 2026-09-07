"""Flattening fisheye (VR180) input: circle detection and reprojection of the central field
to a rectilinear projection.

VR180 footage holds a 180-degree fisheye image as a circle per eye. **This is not a planar stereo
pair.** Stereo matching searches only horizontally, assuming corresponding points share a row,
but fisheye offsets them vertically the farther they sit from the centre, so the search fails.
Building views from that disparity looks blurred.

Reprojecting to a rectilinear image puts corresponding points on the same row, given parallel
optical axes and a horizontal baseline. The circle centre is measured per eye, so a difference
between the two optical axes is absorbed here as well.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast, get_args

import cv2
import numpy as np
from numpy.typing import NDArray

from .video import Frame

Projection = Literal["flat", "fisheye"]
"""How the input was captured. `flat` is a planar stereo pair, `fisheye` is VR180 fisheye."""

PROJECTIONS: tuple[str, ...] = get_args(Projection)

SOURCE_FOV = 180.0
"""The fisheye field of view in degrees. VR180 footage is de facto 180-degree equidistant."""

DEFAULT_FOV = 60.0
"""Horizontal field of view in degrees when flattening. Narrower uses only the centre and
distorts less.
"""

BLACK_LEVEL = 8
"""Luminance at or below this counts as outside the circle (the black border).

Compression noise keeps it from reaching pure black, so this is not 0.
"""

MIN_FILL = 0.3
MAX_FILL = 0.95
"""The fraction of area holding picture. A fisheye circle falls between 30% and 90%
(measured: 65% at 960x1080).
"""

ROUNDNESS = 0.25
"""Tolerance on the outline's aspect ratio. Far from 1 means it is not a circle."""


@dataclass(frozen=True)
class FisheyeCircle:
    """The fisheye circle in one eye's frame, in pixels. `radius` corresponds to theta=90°."""

    center_x: float
    center_y: float
    radius: float

    def __post_init__(self) -> None:
        if self.radius <= 0:
            raise ValueError(f"radius は正の数（受け取った値: {self.radius}）")


def detect_circle(images: Sequence[Frame]) -> FisheyeCircle | None:
    """Measure the fisheye circle from one eye's frames. Returns None when no circle is found.

    The radius comes from **the widest row and the tallest column**. A least-squares circle fit to
    the boundary is not used: the measured source outline was taller than a true circle (a
    superellipse), and fitting a circle inflated the radius from 437 px to 469 px. Differences
    between sources are absorbed by the field of view (`fov`).
    """
    mask = _content_mask(images)
    if mask is None:
        return None
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    width = int(xs.max() - xs.min()) + 1
    height = int(ys.max() - ys.min()) + 1
    # A non-round outline is not fisheye (for instance a landscape two-view frame passed as is)
    if abs(width / height - 1.0) > ROUNDNESS:
        return None
    fill = float(mask.sum()) / mask.size
    if not MIN_FILL <= fill <= MAX_FILL:
        return None
    widest = int(mask.sum(axis=1).max())
    tallest = int(mask.sum(axis=0).max())
    return FisheyeCircle(
        center_x=float(xs.min() + xs.max()) / 2.0,
        center_y=float(ys.min() + ys.max()) / 2.0,
        radius=(widest + tallest) / 4.0,
    )


def guess_projection(images: Sequence[Frame]) -> Projection:
    """Guess the projection from one eye's frames. A circle means fisheye."""
    return "fisheye" if detect_circle(images) is not None else "flat"


def rectilinear_maps(
    circle: FisheyeCircle,
    *,
    tile_size: tuple[int, int],
    tile_aspect: float,
    fov: float = DEFAULT_FOV,
    source_fov: float = SOURCE_FOV,
) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    """Return the `cv2.remap` maps that build one tile's rectilinear projection from fisheye.

    Assumes an equidistant projection (`rho = f * theta`), the de facto standard for VR180
    footage, where the circle radius corresponds to theta=90 degrees.

    A tile's pixels are not square as displayed (Go shows 372x682 px at an aspect ratio of
    0.5625). Computing the field of view from the pixel ratio stretches the result horizontally,
    so it uses the displayed ratio.
    """
    tile_width, tile_height = tile_size
    if tile_width < 1 or tile_height < 1:
        raise ValueError(f"タイルの大きさが不正（{tile_width}x{tile_height}）")
    if tile_aspect <= 0:
        raise ValueError(f"tile_aspect は正の数（受け取った値: {tile_aspect}）")
    if not 0.0 < fov < source_fov:
        raise ValueError(f"fov は 0 より大きく {source_fov} 未満（受け取った値: {fov}）")

    # One pixel's displayed width / height. Lengths below are in units of "vertical pixels"
    pixel_aspect = tile_aspect / (tile_width / tile_height)
    focal = (tile_width * pixel_aspect / 2.0) / math.tan(math.radians(fov) / 2.0)

    u = (np.arange(tile_width, dtype=np.float32) + 0.5 - tile_width / 2.0) * pixel_aspect
    v = np.arange(tile_height, dtype=np.float32) + 0.5 - tile_height / 2.0
    grid_u, grid_v = np.meshgrid(u, v)
    distance = np.hypot(grid_u, grid_v)
    theta = np.arctan2(distance, focal)

    limit = math.radians(source_fov) / 2.0
    if float(theta.max()) > limit:
        raise ValueError(
            f"視野角 {fov}° ではタイルの隅が魚眼の外（{math.degrees(float(theta.max())):.0f}° > "
            f"{source_fov / 2:.0f}°）を指す。fov を下げる"
        )

    rho = circle.radius * theta / limit
    # distance is 0 at the centre, so floor it before dividing (rho is 0 too, so the value stays
    # at the centre)
    unit = rho / np.maximum(distance, 1e-6)
    map_x = (circle.center_x + unit * grid_u).astype(np.float32)
    map_y = (circle.center_y + unit * grid_v).astype(np.float32)
    return map_x, map_y


def rectify(image: Frame, maps: tuple[NDArray[np.float32], NDArray[np.float32]]) -> Frame:
    """Flatten one frame with the maps from `rectilinear_maps`."""
    map_x, map_y = maps
    return cast(
        Frame,
        cv2.remap(image, map_x, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE),
    )


def _content_mask(images: Sequence[Frame]) -> NDArray[np.bool_] | None:
    """A boolean map of where picture is present. Returns None when there is no black border.

    A pixel that was bright at least once counts as valid; from those, **only the largest
    connected component** is kept and filled row by row. Picking up a logo or subtitle floating in
    the black border throws the circle far off, and mistaking a shadow inside the picture for the
    boundary inflates the radius (measured: a 437 px circle became 466 px).
    """
    if not images:
        return None
    grays = [cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) for image in images]
    brightest = np.maximum.reduce(grays)
    lit = (brightest > BLACK_LEVEL).astype(np.uint8)
    # An entirely bright frame has no black border, so it is not fisheye
    if not lit.size or bool(lit.all()):
        return None
    count, labels = cv2.connectedComponents(lit, connectivity=4)
    if count < 2:
        return None
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    body = labels == int(np.argmax(sizes))
    return _fill_rows(body)


def _fill_rows(mask: NDArray[np.bool_]) -> NDArray[np.bool_]:
    """Fill between the leftmost and rightmost pixel of each row.

    For a circle, the filled shape is the circle itself.
    """
    filled = np.zeros_like(mask)
    columns = np.arange(mask.shape[1])
    for index, row in enumerate(mask):
        if not row.any():
            continue
        hit = columns[row]
        filled[index, hit[0] : hit[-1] + 1] = True
    return filled
