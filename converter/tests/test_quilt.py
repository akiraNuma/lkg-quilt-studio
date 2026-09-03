import pytest

from lkg_quilt_converter.quilt import PRESETS, QuiltSpec


@pytest.fixture
def spec() -> QuiltSpec:
    return QuiltSpec(columns=5, rows=9, width=4096, height=4096, aspect=1.777)


def test_view_count_is_columns_times_rows(spec: QuiltSpec) -> None:
    assert spec.view_count == 45


def test_view_zero_is_bottom_left(spec: QuiltSpec) -> None:
    x, y = spec.tile_origin(0)
    assert x == 0
    assert y == pytest.approx(spec.height - spec.tile_height)


def test_last_view_is_top_right(spec: QuiltSpec) -> None:
    x, y = spec.tile_origin(spec.view_count - 1)
    assert x == pytest.approx(spec.width - spec.tile_width)
    assert y == 0


def test_views_advance_left_to_right_then_upward(spec: QuiltSpec) -> None:
    first_row_y = spec.tile_origin(0)[1]
    next_x, next_y = spec.tile_origin(1)
    assert next_x == pytest.approx(spec.tile_width)
    assert next_y == pytest.approx(first_row_y)
    assert spec.tile_origin(spec.columns)[1] == pytest.approx(first_row_y - spec.tile_height)


def test_out_of_range_view_is_rejected(spec: QuiltSpec) -> None:
    with pytest.raises(ValueError):
        spec.tile_origin(spec.view_count)


def test_filename_follows_quilt_convention(spec: QuiltSpec) -> None:
    assert spec.filename("sample") == "sample_qs5x9a1.777.mp4"


def test_presets_cover_known_displays() -> None:
    assert PRESETS["portrait"].view_count == 48
    assert PRESETS["16"].view_count == 45
    assert PRESETS["32"].width == 8192
