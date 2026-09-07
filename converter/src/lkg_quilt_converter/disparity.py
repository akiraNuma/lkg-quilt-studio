"""Disparity estimation. Returns per-pixel disparity relative to the left image.

Disparity `d` satisfies `left[x] ~= right[x - d]` and grows for nearer surfaces.
**Its sign is not necessarily positive:** surfaces behind the convergence plane (the plane that
appears at screen depth) have negative disparity.

The default is SGBM plus a WLS filter, which needs no model weights. Only the shape of
`DisparityEstimator` is fixed, so a temporally consistent deep model can replace it
(candidates are in `.claude/rules/external-apis.md`).
"""

from dataclasses import dataclass
from typing import Protocol, cast

import cv2
import numpy as np
from numpy.typing import NDArray

from .holes import DisparityMap, fill_horizontal
from .video import Frame

GrayFrame = NDArray[np.uint8]
"""A grayscale image of (height, width)."""


@dataclass(frozen=True)
class DisparityParams:
    """Disparity estimation settings.

    The search covers `[min_disparity, min_disparity + max_disparity)`. Setting `min_disparity`
    to 0 **fails to find surfaces that sit in front of the screen (negative disparity)** and
    collapses their depth to 0. Where the convergence plane sat during capture is unknown, so the
    default searches both signs.
    """

    max_disparity: int = 128
    min_disparity: int = -64
    block_size: int = 5
    downscale: int = 1
    wls_lambda: float = 8000.0
    wls_sigma: float = 1.5
    temporal_weight: float = 0.35
    temporal_threshold: float = 4.0

    def __post_init__(self) -> None:
        # SGBM raises unless numDisparities is a multiple of 16
        if self.max_disparity <= 0 or self.max_disparity % 16:
            raise ValueError(
                f"max_disparity must be a positive multiple of 16 (received: {self.max_disparity})"
            )
        if self.block_size < 1 or self.block_size % 2 == 0:
            raise ValueError(
                f"block_size must be a positive odd number (received: {self.block_size})"
            )
        if self.min_disparity + self.max_disparity <= 0:
            raise ValueError(
                "the top of the search range is at or below 0, so nearer surfaces cannot be found"
                f" (min_disparity={self.min_disparity} max_disparity={self.max_disparity})"
            )
        if self.downscale < 1:
            raise ValueError(f"downscale must be at least 1 (received: {self.downscale})")
        if not 0.0 < self.temporal_weight <= 1.0:
            raise ValueError(
                f"temporal_weight must be above 0 and at most 1 (received: {self.temporal_weight})"
            )


class DisparityEstimator(Protocol):
    """An estimator returning a disparity map from one frame's left and right images."""

    def estimate(self, left: Frame, right: Frame) -> DisparityMap: ...

    def seed(self, disparity: DisparityMap) -> None:
        """Seed the previous frame's disparity from outside.

        Prevents a jump when a cached frame skips `estimate` and breaks the temporal smoothing
        chain.
        """
        ...


def blend_temporal(
    current: DisparityMap,
    previous: DisparityMap | None,
    *,
    weight: float,
    threshold: float,
) -> DisparityMap:
    """Blend with the previous frame's disparity to suppress flicker.

    A plain exponential moving average leaves trails behind a moving subject, so pixels whose
    difference from the previous frame exceeds `threshold` take this frame's value unblended.
    """
    if previous is None:
        return current
    if previous.shape != current.shape:
        raise ValueError(f"shapes differ: current={current.shape} previous={previous.shape}")
    smoothed = weight * current + (1.0 - weight) * previous
    moved = np.abs(current - previous) > threshold
    return np.where(moved, current, smoothed).astype(np.float32)


class SgbmDisparityEstimator:
    """Disparity estimation with SGBM plus a WLS filter, smoothed across frames by
    `blend_temporal`.
    """

    def __init__(self, params: DisparityParams) -> None:
        self._params = params
        self._previous: DisparityMap | None = None

        block = params.block_size
        self._left_matcher = cv2.StereoSGBM.create(
            minDisparity=_search_start(params),
            numDisparities=_search_range(params),
            blockSize=block,
            # P1 / P2 penalise disparity changes. OpenCV samples use 8/32 x channels x window area
            P1=8 * block * block,
            P2=32 * block * block,
            disp12MaxDiff=1,
            uniquenessRatio=10,
            speckleWindowSize=100,
            speckleRange=2,
            preFilterCap=63,
            mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
        )
        self._right_matcher = cv2.ximgproc.createRightMatcher(self._left_matcher)
        self._filter = cv2.ximgproc.createDisparityWLSFilter(self._left_matcher)
        self._filter.setLambda(params.wls_lambda)
        self._filter.setSigmaColor(params.wls_sigma)

    def seed(self, disparity: DisparityMap) -> None:
        self._previous = disparity

    def estimate(self, left: Frame, right: Frame) -> DisparityMap:
        if left.shape != right.shape:
            raise ValueError(
                f"the eyes have different shapes: left={left.shape} right={right.shape}"
            )
        scale = self._params.downscale
        # When the search range approaches the image width, SGBM asks for an enormous internal
        # buffer and fails with cv2.error (Insufficient memory). Fail earlier, with the reason
        search = _search_range(self._params)
        usable_width = max(left.shape[1] // scale, 1)
        if search >= usable_width:
            raise ValueError(
                f"the disparity search range of {search} px reaches the tile width of"
                f" {usable_width} px, so stereo matching cannot run."
                " Lower --max-disparity or raise the quilt resolution"
            )
        small_left = _to_gray(left, scale)
        small_right = _to_gray(right, scale)

        raw_left = self._left_matcher.compute(small_left, small_right)
        raw_right = self._right_matcher.compute(small_right, small_left)
        filtered = self._filter.filter(raw_left, small_left, None, raw_right)

        # SGBM / WLS return disparity as fixed point scaled by 16
        disparity = filtered.astype(np.float32) / 16.0
        # SGBM marks pixels it could not match with (minDisparity - 1). The bottom of the search
        # range is itself a valid value, so treat only what falls below it as invalid
        valid = disparity >= float(_search_start(self._params))
        disparity, _ = fill_horizontal(disparity, valid)

        if scale > 1:
            height, width = left.shape[:2]
            upscaled = cv2.resize(disparity, (width, height), interpolation=cv2.INTER_LINEAR)
            disparity = cast(DisparityMap, upscaled) * float(scale)

        disparity = blend_temporal(
            disparity,
            self._previous,
            weight=self._params.temporal_weight,
            threshold=self._params.temporal_threshold,
        )
        self._previous = disparity
        return disparity


def photometric_residual(left: Frame, right: Frame, disparity: DisparityMap) -> float:
    """Mean absolute error after warping the right image back to the left viewpoint.

    A single number for judging whether disparity is plausible. With the eyes swapped, no
    disparity explains the image, so the value comes out large.
    """
    height, width = disparity.shape
    columns = np.arange(width, dtype=np.float32)[None, :]
    rows = np.broadcast_to(np.arange(height, dtype=np.float32)[:, None], (height, width))
    sampled_x = np.ascontiguousarray(columns - disparity, dtype=np.float32)
    warped = cv2.remap(
        right,
        sampled_x,
        np.ascontiguousarray(rows, dtype=np.float32),
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    inside = (sampled_x >= 0.0) & (sampled_x <= float(width - 1))
    difference = np.abs(left.astype(np.float32) - warped.astype(np.float32)).mean(axis=2)
    return float(difference[inside].mean())


def _search_range(params: DisparityParams) -> int:
    """Narrow the search range by the estimation downscale, rounded to a multiple of 16.

    SGBM raises unless numDisparities is a multiple of 16.
    """
    return max(16, round(params.max_disparity / params.downscale / 16.0) * 16)


def _search_start(params: DisparityParams) -> int:
    """Shift the bottom of the search range by the estimation downscale as well."""
    return round(params.min_disparity / params.downscale)


def _to_gray(frame: Frame, scale: int) -> GrayFrame:
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    if scale == 1:
        return cast(GrayFrame, gray)
    height, width = gray.shape[:2]
    size = (max(width // scale, 1), max(height // scale, 1))
    return cast(GrayFrame, cv2.resize(gray, size, interpolation=cv2.INTER_AREA))
