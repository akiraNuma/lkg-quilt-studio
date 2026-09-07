"""Row-wise hole filling, used both for invalid disparity pixels and for gaps a forward warp
leaves behind.
"""

import numpy as np
from numpy.typing import NDArray

DisparityMap = NDArray[np.float32]


def fill_horizontal(
    values: DisparityMap,
    valid: NDArray[np.bool_],
    *,
    max_gap: int = 0,
) -> tuple[DisparityMap, NDArray[np.bool_]]:
    """Fill invalid pixels from the values to their left and right in the same row.

    Returns (filled values, pixels still treated as occlusion holes).
    Gaps at most `max_gap` wide are filled by linear interpolation between the two sides and
    dropped from the holes: a forward warp opens 1-2 px gaps wherever a surface is stretched, and
    those are not occlusions. Wider gaps are filled from whichever side has the smaller disparity
    (the farther one). Filling from the foreground disparity smears the nearer surface's colour
    across the region and dissolves the outline.
    """
    if values.shape != valid.shape:
        raise ValueError(f"shapes differ: values={values.shape} valid={valid.shape}")
    if max_gap < 0:
        raise ValueError(f"max_gap must be at least 0 (received: {max_gap})")

    width = values.shape[1]
    columns = np.arange(width, dtype=np.int64)
    # Column of the nearest valid pixel to the left / right of each pixel, or -1 / width
    left_index = np.maximum.accumulate(np.where(valid, columns, -1), axis=1)
    right_index = np.minimum.accumulate(np.where(valid, columns, width)[:, ::-1], axis=1)[:, ::-1]
    has_left = left_index >= 0
    has_right = right_index < width

    left_value = np.take_along_axis(values, np.clip(left_index, 0, width - 1), axis=1)
    right_value = np.take_along_axis(values, np.clip(right_index, 0, width - 1), axis=1)

    both = has_left & has_right
    gap = right_index - left_index - 1
    span = np.where(both, np.maximum(right_index - left_index, 1), 1)
    ratio = (columns[None, :] - left_index) / span
    interpolated = left_value + (right_value - left_value) * ratio
    background = np.minimum(left_value, right_value)

    is_crack = ~valid & both & (gap <= max_gap)
    filled = np.where(
        valid,
        values,
        np.where(
            is_crack,
            interpolated,
            np.where(both, background, np.where(has_left, left_value, right_value)),
        ),
    )
    filled = np.where(has_left | has_right, filled, 0.0)
    return filled.astype(np.float32), ~valid & ~is_crack
