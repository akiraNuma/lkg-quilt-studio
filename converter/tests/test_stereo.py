import cv2
import numpy as np
import pytest

from lkg_quilt_converter.stereo import (
    crop_rect,
    fit_content,
    guess_layout,
    pad_to_tile,
    plan_fit,
    split_stereo,
)


def test_side_by_side_splits_into_halves() -> None:
    frame = np.zeros((4, 8, 3), dtype=np.uint8)
    frame[:, 4:] = 255
    left, right = split_stereo(frame, "sbs")
    assert left.shape == (4, 4, 3)
    assert left.max() == 0
    assert right.min() == 255


def test_top_bottom_splits_into_halves() -> None:
    frame = np.zeros((4, 8, 3), dtype=np.uint8)
    frame[2:] = 255
    left, right = split_stereo(frame, "tb")
    assert left.shape == (2, 8, 3)
    assert right.min() == 255


def test_separate_layout_cannot_be_split() -> None:
    with pytest.raises(ValueError):
        split_stereo(np.zeros((4, 8, 3), dtype=np.uint8), "separate")


def test_odd_size_is_rejected() -> None:
    with pytest.raises(ValueError):
        split_stereo(np.zeros((4, 7, 3), dtype=np.uint8), "sbs")


def test_crop_trims_width_when_the_source_is_too_wide() -> None:
    assert crop_rect(200, 100, 1.0, 1.0) == (50, 0, 100, 100)


def test_crop_trims_height_when_the_source_is_too_tall() -> None:
    assert crop_rect(100, 200, 1.0, 1.0) == (0, 50, 100, 100)


def test_half_side_by_side_is_treated_as_stretched() -> None:
    # 960x1080 の片眼は表示上 16:9。画素の縦横比 2.0 を渡せば切り出しは不要になる
    assert crop_rect(960, 1080, 2.0, 960 * 2.0 / 1080) == (0, 0, 960, 1080)


def test_crop_rejects_invalid_input() -> None:
    with pytest.raises(ValueError):
        crop_rect(0, 100, 1.0, 1.0)
    with pytest.raises(ValueError):
        crop_rect(100, 100, 0.0, 1.0)


def test_fit_content_crops_then_resizes() -> None:
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    image[:, 100:] = 255
    fit = plan_fit(200, 100, pixel_aspect=1.0, tile_size=(50, 50), tile_aspect=1.0, mode="crop")
    fitted = fit_content(image, fit)
    assert fitted.shape == (50, 50, 3)
    # 中央 100px（x=50〜149）を切り出すので、右半分だけが白になる
    assert fitted[0, -1, 0] == 255
    assert fitted[0, 0, 0] == 0


def test_crop_mode_fills_the_whole_tile() -> None:
    fit = plan_fit(
        1920, 1080, pixel_aspect=1.0, tile_size=(372, 682), tile_aspect=0.5625, mode="crop"
    )
    assert fit.content_size == (372, 682)
    assert fit.offset == (0, 0)
    assert not fit.padded
    # 表示上 9:16 になるまで幅を落とす
    assert fit.source == (656, 0, 608, 1080)


def test_pad_mode_keeps_the_whole_frame_and_letterboxes() -> None:
    """縦画面の Go に横長の素材を入れると上下に余白が入る。

    タイルの画素の縦横比（372/682）と表示上の縦横比（0.5625）は一致しないので、
    余白の量は表示上の比で決まる。
    """
    fit = plan_fit(
        1920, 1080, pixel_aspect=1.0, tile_size=(372, 682), tile_aspect=0.5625, mode="pad"
    )
    assert fit.source == (0, 0, 1920, 1080)
    assert fit.content_size[0] == 372
    assert fit.padded
    # 表示上の縦横比が保たれる: 幅いっぱい 0.5625 に対して高さは 16:9 の分だけ
    displayed = 0.5625 * (fit.content_size[0] / 372) / (fit.content_size[1] / 682)
    assert abs(displayed - 1920 / 1080) < 0.01
    assert fit.offset == (0, (682 - fit.content_size[1]) // 2)


def test_pad_mode_pillarboxes_a_tall_source() -> None:
    fit = plan_fit(
        1080, 1920, pixel_aspect=1.0, tile_size=(819, 461), tile_aspect=1.777, mode="pad"
    )
    assert fit.content_size[1] == 461
    assert fit.content_size[0] < 819
    assert fit.offset[1] == 0


def test_pad_mode_is_a_no_op_when_the_aspects_agree() -> None:
    fit = plan_fit(
        1920, 1080, pixel_aspect=1.0, tile_size=(819, 461), tile_aspect=1920 / 1080, mode="pad"
    )
    assert not fit.padded
    assert fit.content_size == (819, 461)


def test_pad_to_tile_centres_the_content_and_leaves_black_bars() -> None:
    fit = plan_fit(
        1920, 1080, pixel_aspect=1.0, tile_size=(372, 682), tile_aspect=0.5625, mode="pad"
    )
    content = np.full((fit.content_size[1], fit.content_size[0], 3), 255, dtype=np.uint8)
    tile = pad_to_tile(content, fit)
    assert tile.shape == (682, 372, 3)
    assert tile[0, 0, 0] == 0
    assert tile[341, 186, 0] == 255


def test_pad_to_tile_passes_through_when_no_bars_are_needed() -> None:
    fit = plan_fit(
        1920, 1080, pixel_aspect=1.0, tile_size=(372, 682), tile_aspect=0.5625, mode="crop"
    )
    content = np.zeros((682, 372, 3), dtype=np.uint8)
    assert pad_to_tile(content, fit) is content


def test_plan_fit_rejects_an_invalid_tile() -> None:
    with pytest.raises(ValueError):
        plan_fit(100, 100, pixel_aspect=1.0, tile_size=(0, 10), tile_aspect=1.0, mode="pad")


def _stereo_pair(disparity: int, layout: str, seed: int = 3) -> np.ndarray:
    """視差 `disparity` の左右を `layout` の並びに詰めた 1 コマを作る。

    一様ノイズだと数画素ずらしただけで無相関になり、実写と挙動が変わる。
    小さいノイズを引き伸ばして、実際の映像のような滑らかな絵にする。
    """
    generator = np.random.default_rng(seed)
    height, width, margin = 120, 240, 40
    coarse = generator.integers(0, 256, (12, 28, 3), dtype=np.uint8)
    texture = cv2.resize(coarse, (width + 2 * margin, height), interpolation=cv2.INTER_CUBIC)
    left = texture[:, margin : margin + width]
    right = texture[:, margin + disparity : margin + disparity + width]
    if layout == "sbs":
        return np.ascontiguousarray(np.hstack([left, right]))
    return np.ascontiguousarray(np.vstack([left, right]))


def test_guess_layout_finds_side_by_side() -> None:
    frames = [_stereo_pair(6, "sbs") for _ in range(3)]
    # 片眼 240x120（2:1）なので潰されてはいない
    assert guess_layout(frames) == "sbs"


def test_guess_layout_finds_top_bottom() -> None:
    assert guess_layout([_stereo_pair(6, "tb") for _ in range(3)]) == "tb"


def test_guess_layout_gives_up_on_a_2d_frame() -> None:
    """2D 動画はどちらで割っても無関係な絵になる。当てずっぽうを返さない。"""
    generator = np.random.default_rng(11)
    frames = [
        np.ascontiguousarray(
            cv2.resize(
                generator.integers(0, 256, (12, 24, 3), dtype=np.uint8),
                (240, 120),
                interpolation=cv2.INTER_CUBIC,
            ),
            dtype=np.uint8,
        )
        for _ in range(3)
    ]
    assert guess_layout(frames) is None


def test_guess_layout_ignores_frames_that_are_too_small() -> None:
    assert guess_layout([np.zeros((1, 1, 3), dtype=np.uint8)]) is None
    assert guess_layout([]) is None
