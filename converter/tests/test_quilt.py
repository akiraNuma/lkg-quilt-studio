import numpy as np
import pytest

from lkg_quilt_converter.quilt import PRESETS, QuiltSpec


@pytest.fixture
def spec() -> QuiltSpec:
    return QuiltSpec(columns=5, rows=9, width=4096, height=4096, aspect=1.777)


def test_view_count_is_columns_times_rows(spec: QuiltSpec) -> None:
    assert spec.view_count == 45


def test_tile_size_floors_indivisible_resolution(spec: QuiltSpec) -> None:
    assert spec.tile_size == (819, 455)


def test_margin_is_what_the_tile_grid_leaves_over(spec: QuiltSpec) -> None:
    assert spec.margin == (1, 1)
    assert QuiltSpec(columns=8, rows=6, width=3360, height=3360, aspect=0.75).margin == (0, 0)


def test_view_zero_is_bottom_left(spec: QuiltSpec) -> None:
    tile_height = spec.tile_size[1]
    assert spec.tile_origin(0) == (0, spec.height - tile_height)


def test_last_view_is_top_right(spec: QuiltSpec) -> None:
    tile_width, _ = spec.tile_size
    x, y = spec.tile_origin(spec.view_count - 1)
    assert x == (spec.columns - 1) * tile_width
    # 余白は上端に寄るので、最上段のタイルは y=0 ではなく余白の分だけ下がる
    assert y == spec.margin[1]


def test_views_advance_left_to_right_then_upward(spec: QuiltSpec) -> None:
    bottom_row_y = spec.tile_origin(0)[1]
    assert spec.tile_origin(1)[1] == bottom_row_y
    assert spec.tile_origin(1)[0] > 0
    assert spec.tile_origin(spec.columns)[1] < bottom_row_y


@pytest.mark.parametrize("name", sorted(PRESETS))
def test_tiles_cover_every_pixel_outside_the_margin(name: str) -> None:
    """どのタイルにも入らない列・行を作らない（黒い筋として quilt に焼き込まれる）。"""
    spec = PRESETS[name]
    tile_width, tile_height = spec.tile_size
    columns = np.zeros(spec.width, dtype=int)
    rows = np.zeros(spec.height, dtype=int)
    for index in range(spec.view_count):
        x, y = spec.tile_origin(index)
        assert x >= 0 and x + tile_width <= spec.width
        assert y >= 0 and y + tile_height <= spec.height
        columns[x : x + tile_width] += 1
        rows[y : y + tile_height] += 1
    margin_x, margin_y = spec.margin
    # 余白は右端と上端に寄る。それ以外は必ず 1 枚のタイルに覆われる
    assert (columns[: spec.width - margin_x] > 0).all()
    assert (columns[spec.width - margin_x :] == 0).all()
    assert (rows[margin_y:] > 0).all()
    assert (rows[:margin_y] == 0).all()


def test_out_of_range_view_is_rejected(spec: QuiltSpec) -> None:
    with pytest.raises(ValueError):
        spec.tile_origin(spec.view_count)


def test_filename_follows_quilt_convention(spec: QuiltSpec) -> None:
    assert spec.filename("sample") == "sample_qs5x9a1.777.mp4"
    assert spec.filename("sample", "png") == "sample_qs5x9a1.777.png"


def test_presets_cover_known_displays() -> None:
    assert PRESETS["portrait"].view_count == 48
    assert PRESETS["16"].view_count == 45
    assert PRESETS["32"].width == 8192


def test_go_preset_matches_the_hardware() -> None:
    """実機の Bridge が返した defaultQuilt（LKG-E / go_p）と一致させる。"""
    go = PRESETS["go"]
    assert (go.columns, go.rows) == (11, 6)
    assert (go.width, go.height) == (4092, 4092)
    assert go.aspect == 0.5625
    assert go.view_count == 66
    assert go.filename("sample") == "sample_qs11x6a0.5625.mp4"


def test_invalid_layout_is_rejected() -> None:
    with pytest.raises(ValueError):
        QuiltSpec(columns=0, rows=9, width=4096, height=4096, aspect=1.0)
    with pytest.raises(ValueError):
        QuiltSpec(columns=5, rows=9, width=4, height=4096, aspect=1.0)
    with pytest.raises(ValueError):
        QuiltSpec(columns=5, rows=9, width=4096, height=4096, aspect=0.0)


def test_compose_places_each_view_in_its_tile() -> None:
    spec = QuiltSpec(columns=2, rows=2, width=4, height=4, aspect=1.0)
    views = [np.full((2, 2, 3), fill_value=index + 1, dtype=np.uint8) for index in range(4)]
    quilt = spec.compose(views)
    # 視点 0 は左下、視点 3 は右上
    assert quilt[2, 0, 0] == 1
    assert quilt[2, 2, 0] == 2
    assert quilt[0, 0, 0] == 3
    assert quilt[0, 2, 0] == 4


def test_compose_rejects_wrong_view_count_and_shape() -> None:
    spec = QuiltSpec(columns=2, rows=2, width=4, height=4, aspect=1.0)
    view = np.zeros((2, 2, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        spec.compose([view] * 3)
    with pytest.raises(ValueError):
        spec.compose([np.zeros((3, 3, 3), dtype=np.uint8)] * 4)
