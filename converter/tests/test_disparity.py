from collections.abc import Callable

import numpy as np
import pytest

from lkg_quilt_converter.disparity import (
    DisparityParams,
    SgbmDisparityEstimator,
    blend_temporal,
)


def test_defaults_are_valid() -> None:
    assert DisparityParams().max_disparity % 16 == 0


def test_default_search_range_covers_both_signs() -> None:
    """手前に飛び出す面は負の視差になる。下端が 0 だと見つからず奥行きが潰れる。"""
    params = DisparityParams()
    assert params.min_disparity < 0
    assert params.min_disparity + params.max_disparity > 0


@pytest.mark.parametrize(
    "build",
    [
        lambda: DisparityParams(max_disparity=100),
        lambda: DisparityParams(max_disparity=0),
        lambda: DisparityParams(min_disparity=-128),
        lambda: DisparityParams(block_size=4),
        lambda: DisparityParams(block_size=0),
        lambda: DisparityParams(downscale=0),
        lambda: DisparityParams(temporal_weight=0.0),
        lambda: DisparityParams(temporal_weight=1.5),
    ],
)
def test_invalid_params_are_rejected(build: Callable[[], DisparityParams]) -> None:
    with pytest.raises(ValueError):
        build()


def test_first_frame_passes_through() -> None:
    current = np.array([[3.0]], dtype=np.float32)
    assert blend_temporal(current, None, weight=0.5, threshold=1.0) is current


def test_small_change_is_smoothed() -> None:
    current = np.array([[10.0]], dtype=np.float32)
    previous = np.array([[12.0]], dtype=np.float32)
    blended = blend_temporal(current, previous, weight=0.5, threshold=4.0)
    assert blended[0, 0] == pytest.approx(11.0)


def test_large_change_is_kept_as_is() -> None:
    current = np.array([[10.0]], dtype=np.float32)
    previous = np.array([[30.0]], dtype=np.float32)
    blended = blend_temporal(current, previous, weight=0.5, threshold=4.0)
    assert blended[0, 0] == pytest.approx(10.0)


def test_moving_and_still_pixels_are_handled_per_pixel() -> None:
    current = np.array([[10.0, 10.0], [10.0, 10.0]], dtype=np.float32)
    previous = np.array([[12.0, 30.0], [10.0, 11.0]], dtype=np.float32)
    blended = blend_temporal(current, previous, weight=0.5, threshold=4.0)
    # 差が閾値以内の画素だけ混ぜる。跳ねた画素（30）は今フレームの値をそのまま採る
    assert blended.tolist() == [[11.0, 10.0], [10.0, 10.5]]


def test_shape_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError):
        blend_temporal(
            np.zeros((2, 2), dtype=np.float32),
            np.zeros((3, 3), dtype=np.float32),
            weight=0.5,
            threshold=1.0,
        )


def test_search_range_wider_than_the_tile_is_rejected() -> None:
    """探索範囲がタイル幅以上だと SGBM が cv2.error で落ちるので、先に弾く。"""
    estimator = SgbmDisparityEstimator(DisparityParams(max_disparity=128))
    narrow = np.zeros((32, 64, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="探索範囲"):
        estimator.estimate(narrow, narrow)


def _shifted_pair(disparity: int) -> tuple[np.ndarray, np.ndarray]:
    """視差が `disparity` になる左右の画像を作る。

    視差の定義は `left[x] ≒ right[x - d]`。texture を切り出す位置をずらして作る。
    """
    height, width, margin = 96, 256, 48
    generator = np.random.default_rng(7)
    texture = generator.integers(0, 256, (height, width + 2 * margin, 3), dtype=np.uint8)
    left = texture[:, margin : margin + width]
    start = margin + disparity
    right = texture[:, start : start + width]
    return np.ascontiguousarray(left), np.ascontiguousarray(right)


def _centre_median(disparity: np.ndarray) -> float:
    return float(np.median(disparity[24:72, 64:192]))


def test_negative_disparity_is_recovered() -> None:
    """画面より奥の面は負の視差になる。探索の下端を負にしないと見つからない。"""
    left, right = _shifted_pair(-8)
    params = DisparityParams(min_disparity=-32, max_disparity=64, temporal_weight=1.0)
    estimated = SgbmDisparityEstimator(params).estimate(left, right)
    assert _centre_median(estimated) == pytest.approx(-8.0, abs=1.0)


def test_a_zero_lower_bound_flattens_a_negative_disparity() -> None:
    """min_disparity=0 では負の視差が探索範囲の外なので、奥行きが 0 に潰れる。"""
    left, right = _shifted_pair(-8)
    params = DisparityParams(min_disparity=0, max_disparity=64, temporal_weight=1.0)
    estimated = SgbmDisparityEstimator(params).estimate(left, right)
    assert _centre_median(estimated) > -1.0


def test_positive_disparity_is_still_recovered() -> None:
    left, right = _shifted_pair(12)
    params = DisparityParams(min_disparity=-32, max_disparity=64, temporal_weight=1.0)
    estimated = SgbmDisparityEstimator(params).estimate(left, right)
    assert _centre_median(estimated) == pytest.approx(12.0, abs=1.0)
