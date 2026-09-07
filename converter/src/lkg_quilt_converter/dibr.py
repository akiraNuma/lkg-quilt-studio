"""View synthesis by DIBR (Depth Image Based Rendering).

Builds views at positions other than the two cameras from left-referenced disparity.
`position=0.0` is the left camera and `1.0` the right; below 0 and above 1 extrapolate.

Extrapolation always exposes surfaces the left image does not contain (disocclusions). Those are
taken from the right image, and only pixels missing from both are finally filled by inpainting.
"""

from dataclasses import dataclass
from typing import cast

import cv2
import numpy as np
from numpy.typing import NDArray

from .holes import DisparityMap, fill_horizontal
from .video import Frame


@dataclass(frozen=True)
class SynthesisParams:
    """View synthesis settings."""

    crack_width: int = 2
    convergence: float = 0.0
    consistency_tolerance: float = 1.0
    inpaint_radius: int = 3

    # Loosen the occlusion tolerance in proportion to disparity: larger disparity carries larger
    # estimation error
    tolerance_ratio: float = 0.05

    def __post_init__(self) -> None:
        if self.crack_width < 0:
            raise ValueError(f"crack_width must be at least 0 (received: {self.crack_width})")
        if self.inpaint_radius < 1:
            raise ValueError(f"inpaint_radius must be at least 1 (received: {self.inpaint_radius})")
        if self.tolerance_ratio < 0:
            raise ValueError(
                f"tolerance_ratio must be at least 0 (received: {self.tolerance_ratio})"
            )


MINIMUM_AGREEMENT = 0.05
"""Agreement at or below this is not trusted (dropped to 0 and treated as a hole).

The test applies to the agreement value. Applying it to the blended weight instead would drop
correctly imaged pixels into holes whenever a view sits near an edge and one side's weight is
small.
"""


def view_positions(view_count: int, span: float) -> list[float]:
    """Return each view's camera position from the view count and the span.

    `span=1.0` uses only the range between the two cameras; larger values extrapolate to both
    sides. The stereo baseline is narrower than Looking Glass's view cone, so the default
    extrapolates, but widening it grows the area that must be hole-filled and costs quality.
    """
    if view_count < 1:
        raise ValueError(f"view_count must be at least 1 (received: {view_count})")
    if span <= 0:
        raise ValueError(f"span must be positive (received: {span})")
    if view_count == 1:
        return [0.5]
    return [0.5 + span * (index / (view_count - 1) - 0.5) for index in range(view_count)]


def forward_warp(disparity: DisparityMap, shift: float) -> tuple[DisparityMap, NDArray[np.bool_]]:
    """Forward-warp a disparity map to `x + shift * disparity`.

    When several pixels in a row land on the same column, the larger disparity (the nearer
    surface) wins, which puts the occlusion on the correct side.
    """
    height, width = disparity.shape
    columns = np.arange(width, dtype=np.float32)
    destination = np.rint(columns[None, :] + shift * disparity).astype(np.int64)
    rows = np.broadcast_to(np.arange(height, dtype=np.int64)[:, None], (height, width))
    inside = (destination >= 0) & (destination < width)

    warped = np.full((height, width), -np.inf, dtype=np.float32)
    np.maximum.at(warped, (rows[inside], destination[inside]), disparity[inside])
    valid = np.isfinite(warped)
    return np.where(valid, warped, 0.0).astype(np.float32), valid


class ViewSynthesizer:
    """Synthesize a view at an arbitrary position from one frame's images and disparity.

    Right-referenced disparity is produced by forward-warping the left disparity to the right
    viewpoint, prepared once per frame and reused across views.

    Stereo matching can supply right-referenced disparity directly (the output of
    `cv2.ximgproc.createRightMatcher` works once its sign is flipped), but **using it lowers
    quality**. The agreement test assumes the two disparity maps are mutually consistent, and two
    independently estimated maps disagree beyond the tolerance. Measured, the hole ratio worsened
    from 0.51% on average to 5.51% (19% at worst) with --display 16 / --span 2.0 and all
    tolerances at their defaults. Producing it by forward warping guarantees consistency
    structurally.

    In exchange, the amount of holes is asymmetric between the two camera positions (under the
    same conditions, 0.00% at position 0.0 against 0.78% at position 1.0), because the warp
    itself opens holes that make the test on the right side stricter.
    """

    def __init__(
        self, left: Frame, right: Frame, disparity: DisparityMap, params: SynthesisParams
    ) -> None:
        if left.shape != right.shape:
            raise ValueError(
                f"the eyes have different shapes: left={left.shape} right={right.shape}"
            )
        if disparity.shape != left.shape[:2]:
            raise ValueError(
                f"disparity shape differs from the image: {disparity.shape} vs {left.shape[:2]}"
            )
        self._left = left
        self._right = right
        self._params = params
        self._disparity_left = disparity
        warped, valid = forward_warp(disparity, -1.0)
        self._disparity_right, _ = fill_horizontal(warped, valid, max_gap=params.crack_width)

    def view(self, position: float) -> Frame:
        """Synthesize the single view seen from `position`."""
        params = self._params
        height, width = self._disparity_left.shape
        columns = np.arange(width, dtype=np.float32)[None, :]
        rows = np.arange(height, dtype=np.float32)[:, None]
        row_map = np.broadcast_to(rows, (height, width)).astype(np.float32)

        # Offset disparity so the convergence plane (where disparity == convergence) lands at the
        # same place in every view
        shifted = self._disparity_left - params.convergence
        warped, warp_valid = forward_warp(shifted, -position)
        target, _ = fill_horizontal(warped, warp_valid, max_gap=params.crack_width)
        assumed = target + params.convergence

        left_x = (columns + position * target).astype(np.float32)
        right_x = (columns - (1.0 - position) * target - params.convergence).astype(np.float32)

        left_color, left_valid = self._sample(
            self._left, self._disparity_left, left_x, row_map, assumed
        )
        right_color, right_valid = self._sample(
            self._right, self._disparity_right, right_x, row_map, assumed
        )

        left_weight = np.clip(1.0 - position, 0.0, 1.0) * left_valid
        right_weight = np.clip(position, 0.0, 1.0) * right_valid
        total = left_weight + right_weight
        blended = np.zeros((height, width, 3), dtype=np.float32)
        usable = total > 0.0
        np.divide(
            left_color * left_weight[..., None] + right_color * right_weight[..., None],
            total[..., None],
            out=blended,
            where=usable[..., None],
        )

        composed = np.clip(blended, 0.0, 255.0).astype(np.uint8)
        holes = (~usable).astype(np.uint8)
        if holes.any():
            filled = cv2.inpaint(composed, holes, params.inpaint_radius, cv2.INPAINT_TELEA)
            composed = cast(Frame, filled)
        return composed

    def _sample(
        self,
        image: Frame,
        reference: DisparityMap,
        map_x: DisparityMap,
        map_y: DisparityMap,
        assumed: DisparityMap,
    ) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
        """Sample colour at `map_x`, also returning how well that surface agrees with the
        expected disparity.

        A pixel whose sampled disparity disagrees with the expectation is hidden behind another
        surface in this view. Without the agreement test, the colour of an occluded surface is
        stretched into the result.

        The weight is not binary. A boundary that jumps by a pixel from view to view makes
        outlines flicker during playback, so it falls off smoothly over twice the tolerance.
        """
        params = self._params
        sampled_x = np.ascontiguousarray(map_x, dtype=np.float32)
        color = cv2.remap(
            image, sampled_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
        ).astype(np.float32)
        found = cast(
            DisparityMap,
            cv2.remap(
                reference, sampled_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
            ),
        )
        tolerance = params.consistency_tolerance + params.tolerance_ratio * np.abs(assumed)
        error = np.abs(found - assumed)
        agreement = np.clip(2.0 - error / np.maximum(tolerance, 1e-6), 0.0, 1.0)
        # Do not let a trace of agreement count a hole as filled. Without dropping it, a few
        # pixels at a depth boundary escape inpainting and smear the occluded colour
        agreement = np.where(agreement > MINIMUM_AGREEMENT, agreement, 0.0)
        inside = (sampled_x >= 0.0) & (sampled_x <= float(image.shape[1] - 1))
        return color, (agreement * inside).astype(np.float32)
