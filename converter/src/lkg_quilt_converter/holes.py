"""行ごとの穴埋め。視差マップの無効画素と、前進ワープで空いた隙間の両方に使う。"""

import numpy as np
from numpy.typing import NDArray

DisparityMap = NDArray[np.float32]


def fill_horizontal(
    values: DisparityMap,
    valid: NDArray[np.bool_],
    *,
    max_gap: int = 0,
) -> tuple[DisparityMap, NDArray[np.bool_]]:
    """無効画素を同じ行の左右の値から埋める。

    戻り値は (埋めた値, 埋めた後も遮蔽の穴として扱う画素)。
    幅が `max_gap` 以下の隙間は左右の線形補間で埋めて穴から外す。前進ワープは
    面が引き伸ばされる場所に 1〜2 px の隙間を作るが、これは遮蔽ではないため。
    それより広い隙間は左右のうち視差が小さい方（＝奥）で埋める。前景の視差で
    埋めると、埋めた領域に手前の面の色が伸びて輪郭が溶ける。
    """
    if values.shape != valid.shape:
        raise ValueError(f"形が違う: values={values.shape} valid={valid.shape}")
    if max_gap < 0:
        raise ValueError(f"max_gap は 0 以上（受け取った値: {max_gap}）")

    width = values.shape[1]
    columns = np.arange(width, dtype=np.int64)
    # 各画素から見て左側／右側で最も近い有効画素の列番号。無ければ -1 / width
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
