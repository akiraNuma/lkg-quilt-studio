import numpy as np

from lkg_quilt_converter.holes import fill_horizontal


def test_wide_gap_is_filled_with_the_background_disparity() -> None:
    values = np.array([[10.0, 0.0, 0.0, 0.0, 2.0]], dtype=np.float32)
    valid = np.array([[True, False, False, False, True]])
    filled, holes = fill_horizontal(values, valid, max_gap=2)
    # 手前（10）ではなく奥（2）で埋める。前景の色が穴に伸びるのを防ぐため
    assert filled[0].tolist() == [10.0, 2.0, 2.0, 2.0, 2.0]
    assert holes[0].tolist() == [False, True, True, True, False]


def test_narrow_gap_is_interpolated_and_not_a_hole() -> None:
    values = np.array([[10.0, 0.0, 20.0]], dtype=np.float32)
    valid = np.array([[True, False, True]])
    filled, holes = fill_horizontal(values, valid, max_gap=1)
    assert filled[0, 1] == 15.0
    assert not holes.any()


def test_edge_gap_uses_the_only_available_side() -> None:
    values = np.array([[0.0, 0.0, 7.0, 0.0]], dtype=np.float32)
    valid = np.array([[False, False, True, False]])
    filled, holes = fill_horizontal(values, valid)
    assert filled[0].tolist() == [7.0, 7.0, 7.0, 7.0]
    assert holes[0].tolist() == [True, True, False, True]


def test_row_without_any_valid_pixel_stays_zero() -> None:
    values = np.array([[1.0, 2.0]], dtype=np.float32)
    valid = np.array([[False, False]])
    filled, holes = fill_horizontal(values, valid)
    assert filled[0].tolist() == [0.0, 0.0]
    assert holes.all()


def test_rows_are_independent() -> None:
    values = np.array([[5.0, 0.0], [0.0, 9.0]], dtype=np.float32)
    valid = np.array([[True, False], [False, True]])
    filled, _ = fill_horizontal(values, valid)
    assert filled.tolist() == [[5.0, 5.0], [9.0, 9.0]]
