from collections.abc import Callable

import numpy as np
import pytest

from lkg_quilt_converter.dibr import (
    SynthesisParams,
    ViewSynthesizer,
    forward_warp,
    view_positions,
)
from lkg_quilt_converter.quilt import PRESETS


def test_span_one_spans_exactly_the_two_cameras() -> None:
    assert view_positions(3, 1.0) == pytest.approx([0.0, 0.5, 1.0])


def test_span_two_extrapolates_to_both_sides() -> None:
    assert view_positions(3, 2.0) == pytest.approx([-0.5, 0.5, 1.5])


def test_single_view_sits_in_the_middle() -> None:
    assert view_positions(1, 2.0) == [0.5]


@pytest.mark.parametrize(("count", "span"), [(0, 1.0), (5, 0.0), (5, -1.0)])
def test_invalid_view_layout_is_rejected(count: int, span: float) -> None:
    with pytest.raises(ValueError):
        view_positions(count, span)


def test_view_zero_is_the_leftmost_camera_and_lands_bottom_left() -> None:
    """Pin the mapping: view 0 is the leftmost viewpoint and lands in the quilt's bottom-left
    tile.
    """
    spec = PRESETS["16"]
    positions = view_positions(spec.view_count, span=2.0)
    assert positions[0] == min(positions)
    assert positions[-1] == max(positions)
    assert spec.tile_origin(0) == (0, spec.height - spec.tile_size[1])


def test_forward_warp_shifts_by_the_disparity() -> None:
    disparity = np.full((1, 8), 3.0, dtype=np.float32)
    warped, valid = forward_warp(disparity, -1.0)
    # Everything shifts 3 px left, so nothing lands in the rightmost 3 px
    assert valid[0].tolist() == [True] * 5 + [False] * 3
    assert warped[0, 0] == pytest.approx(3.0)


def test_forward_warp_keeps_the_nearest_surface() -> None:
    disparity = np.array([[0.0, 2.0]], dtype=np.float32)
    # Both land on column 0; the nearer one (disparity 2) wins
    warped, valid = forward_warp(disparity, -0.5)
    assert valid[0, 0]
    assert warped[0, 0] == pytest.approx(2.0)


def _plane(width: int, disparity: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A surface at constant disparity: the right image is the left shifted by disparity."""
    ramp = (np.arange(width + disparity, dtype=np.float32) * 2.0).astype(np.uint8)
    left = np.repeat(ramp[None, :width], 4, axis=0)[..., None].repeat(3, axis=2)
    right = np.repeat(ramp[None, disparity : disparity + width], 4, axis=0)[..., None].repeat(
        3, axis=2
    )
    return left, right, np.full((4, width), float(disparity), dtype=np.float32)


def test_position_zero_reproduces_the_left_image() -> None:
    left, right, disparity = _plane(32, 4)
    view = ViewSynthesizer(left, right, disparity, SynthesisParams()).view(0.0)
    assert np.abs(view[:, 8:24].astype(int) - left[:, 8:24].astype(int)).max() <= 1


def test_position_one_reproduces_the_right_image() -> None:
    left, right, disparity = _plane(32, 4)
    view = ViewSynthesizer(left, right, disparity, SynthesisParams()).view(1.0)
    assert np.abs(view[:, 8:24].astype(int) - right[:, 8:24].astype(int)).max() <= 1


def test_middle_position_lands_halfway_between_the_cameras() -> None:
    left, right, disparity = _plane(32, 4)
    view = ViewSynthesizer(left, right, disparity, SynthesisParams()).view(0.5)
    expected = left[:, 10:26].astype(int)  # Half the shift of a disparity-4 surface is 2 px
    assert np.abs(view[:, 8:24].astype(int) - expected).max() <= 2


def test_mismatched_shapes_are_rejected() -> None:
    left, right, disparity = _plane(32, 4)
    with pytest.raises(ValueError):
        ViewSynthesizer(left, right[:, :16], disparity, SynthesisParams())
    with pytest.raises(ValueError):
        ViewSynthesizer(left, right, disparity[:, :16], SynthesisParams())


@pytest.mark.parametrize(
    "build",
    [lambda: SynthesisParams(crack_width=-1), lambda: SynthesisParams(inpaint_radius=0)],
)
def test_invalid_synthesis_params_are_rejected(build: Callable[[], SynthesisParams]) -> None:
    with pytest.raises(ValueError):
        build()
