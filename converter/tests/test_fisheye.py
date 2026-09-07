"""Fisheye circle detection and reprojection to a rectilinear image."""

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
    """Build a frame with a smooth pattern only inside the circle; outside is pure black."""
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
    """A dark scene in the mix does not shrink the circle, since the brighter frame wins."""
    dark = _fisheye_frame() // 40
    circle = detect_circle([dark, _fisheye_frame()])
    assert circle is not None
    assert circle.radius == pytest.approx(110.0, abs=1.5)


def test_full_frame_content_is_not_fisheye() -> None:
    filled = np.full((270, 240, 3), 200, dtype=np.uint8)
    assert detect_circle([filled]) is None
    assert guess_projection([filled]) == "flat"


def test_flat_stereo_half_is_not_fisheye() -> None:
    """Flat footage with only letterbox bars is not mistaken for fisheye (its outline is not
    round).
    """
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
    """The radius a tile edge points at matches the equidistant projection
    `rho = radius * theta / 90 degrees`.
    """
    circle = FisheyeCircle(0.0, 0.0, 180.0)
    fov = 60.0
    width, height = 100, 100
    map_x, _ = rectilinear_maps(circle, tile_size=(width, height), tile_aspect=1.0, fov=fov)
    # The centre of the rightmost pixel points half a pixel inside half the horizontal field
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
    # Only the central field is sampled, so no black border enters
    assert rectified.min() > 0
