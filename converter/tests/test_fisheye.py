"""魚眼の円の検出と、透視投影への再投影。"""

import math

import numpy as np
import pytest

from lkg_quilt_converter.fisheye import (
    FisheyeCircle,
    detect_circle,
    guess_projection,
    rectify,
    rectilinear_maps,
)
from lkg_quilt_converter.video import Frame


def _fisheye_frame(
    width: int = 240,
    height: int = 270,
    center: tuple[float, float] = (120.0, 135.0),
    radius: float = 110.0,
) -> Frame:
    """円の中だけに滑らかな模様が入ったコマを作る。外は真っ黒。"""
    ys, xs = np.mgrid[0:height, 0:width]
    inside = (xs - center[0]) ** 2 + (ys - center[1]) ** 2 <= radius**2
    pattern = 128 + 100 * np.sin(xs / 9.0) * np.cos(ys / 11.0)
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[inside] = np.clip(pattern, 20, 255).astype(np.uint8)[inside][:, None]
    return frame


def test_detects_the_circle_from_one_frame() -> None:
    circle = detect_circle([_fisheye_frame()])
    assert circle is not None
    assert circle.center_x == pytest.approx(120.0, abs=1.0)
    assert circle.center_y == pytest.approx(135.0, abs=1.0)
    assert circle.radius == pytest.approx(110.0, abs=1.5)


def test_dark_frames_do_not_shrink_the_circle() -> None:
    """暗い場面が混ざっても、複数コマの明るいほうを取るので円は縮まない。"""
    dark = _fisheye_frame() // 40
    circle = detect_circle([dark, _fisheye_frame()])
    assert circle is not None
    assert circle.radius == pytest.approx(110.0, abs=1.5)


def test_full_frame_content_is_not_fisheye() -> None:
    filled = np.full((270, 240, 3), 200, dtype=np.uint8)
    assert detect_circle([filled]) is None
    assert guess_projection([filled]) == "flat"


def test_flat_stereo_half_is_not_fisheye() -> None:
    """黒帯が上下にあるだけの平面素材を魚眼と読み違えない（外形が丸くない）。"""
    frame = np.zeros((270, 240, 3), dtype=np.uint8)
    frame[40:230] = 180
    assert detect_circle([frame]) is None


def test_no_frames_is_not_fisheye() -> None:
    assert detect_circle([]) is None


def test_negative_radius_is_rejected() -> None:
    with pytest.raises(ValueError):
        FisheyeCircle(0.0, 0.0, 0.0)


def test_center_of_the_tile_looks_at_the_center_of_the_circle() -> None:
    circle = FisheyeCircle(100.0, 200.0, 90.0)
    map_x, map_y = rectilinear_maps(circle, tile_size=(11, 21), tile_aspect=0.5625, fov=60.0)
    assert map_x[10, 5] == pytest.approx(100.0, abs=0.01)
    assert map_y[10, 5] == pytest.approx(200.0, abs=0.01)


def test_view_angle_maps_to_the_equidistant_radius() -> None:
    """タイルの端が指す半径が、等距離射影の `ρ = radius * θ / 90°` に一致する。"""
    circle = FisheyeCircle(0.0, 0.0, 180.0)
    fov = 60.0
    width, height = 100, 100
    map_x, _ = rectilinear_maps(circle, tile_size=(width, height), tile_aspect=1.0, fov=fov)
    # 右端の画素の中心は水平視野角の半分より半画素だけ内側を向く
    edge = (width / 2 - 0.5) / (width / 2)
    theta = math.atan(edge * math.tan(math.radians(fov) / 2))
    expected = circle.radius * theta / (math.pi / 2)
    assert map_x[height // 2, width - 1] == pytest.approx(expected, rel=1e-3)


@pytest.mark.parametrize("fov", [0.0, -10.0, 180.0, 200.0])
def test_view_angle_outside_the_fisheye_is_rejected(fov: float) -> None:
    with pytest.raises(ValueError):
        rectilinear_maps(FisheyeCircle(10.0, 10.0, 5.0), tile_size=(4, 4), tile_aspect=1.0, fov=fov)


def test_rectify_returns_the_tile_size() -> None:
    frame = _fisheye_frame()
    circle = detect_circle([frame])
    assert circle is not None
    maps = rectilinear_maps(circle, tile_size=(31, 57), tile_aspect=0.5625)
    rectified = rectify(frame, maps)
    assert rectified.shape == (57, 31, 3)
    # 中央視野だけを拾うので黒枠は入らない
    assert rectified.min() > 0
