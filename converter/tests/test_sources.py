"""入力動画の取り込み。壊れたファイルをここで弾けるかを見る。"""

import json
from pathlib import Path

import pytest

from lkg_quilt_converter.sources import Source, SourceStore
from lkg_quilt_converter.video import FfmpegError

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "bbb_stereo_tb.mp4"
"""上下に 2 視点が入った実物。左右の入り方の推定を実際の動画で確かめるために使う。"""


def test_broken_upload_is_rejected_and_leaves_nothing(tmp_path: Path) -> None:
    """壊れた動画はプレビューや変換まで持ち越さない。原因が分かりにくくなる。"""
    store = SourceStore(tmp_path)
    staged = tmp_path / "staged.upload"
    staged.write_bytes(b"not a video")

    with pytest.raises((ValueError, FfmpegError, OSError)):
        store.add("movie.mp4", staged)

    assert store.all() == []
    assert list(tmp_path.glob("*/input.*")) == []


def test_unknown_id_has_no_path(tmp_path: Path) -> None:
    store = SourceStore(tmp_path)
    assert store.get("nope") is None
    assert store.path("nope") is None


def test_restore_reads_back_saved_sources(tmp_path: Path) -> None:
    source = Source(
        id="abc",
        name="movie.mp4",
        width=1920,
        height=2160,
        fps=30.0,
        frame_count=180,
        has_audio=False,
    )
    directory = tmp_path / source.id
    directory.mkdir()
    (directory / "input.mp4").write_bytes(b"x")
    (directory / "source.json").write_text(json.dumps(vars(source), ensure_ascii=False))

    restored = SourceStore(tmp_path).get("abc")
    assert restored == source
    assert SourceStore(tmp_path).path("abc") == directory / "input.mp4"


def test_broken_state_file_is_skipped(tmp_path: Path) -> None:
    directory = tmp_path / "bad"
    directory.mkdir()
    (directory / "source.json").write_text("{}")
    assert SourceStore(tmp_path).all() == []


def test_delete_removes_the_directory(tmp_path: Path) -> None:
    directory = tmp_path / "abc"
    directory.mkdir()
    (directory / "source.json").write_text(
        json.dumps(
            {
                "id": "abc",
                "name": "movie.mp4",
                "width": 4,
                "height": 4,
                "fps": 1.0,
                "frame_count": 1,
                "has_audio": False,
            }
        )
    )
    store = SourceStore(tmp_path)

    assert store.delete("abc")
    assert not directory.exists()
    assert not store.delete("abc")


@pytest.mark.skipif(not SAMPLE.exists(), reason="サンプル動画が無い")
def test_real_video_is_probed_on_upload(tmp_path: Path) -> None:
    store = SourceStore(tmp_path)
    staged = tmp_path / "staged.upload"
    staged.write_bytes(SAMPLE.read_bytes())

    source = store.add(SAMPLE.name, staged)

    assert source.width > 0 and source.height > 0
    assert source.frame_count > 0
    assert store.path(source.id) == tmp_path / source.id / "input.mp4"
    assert source.suggested_layout == "tb"
    # 平面のステレオ対なので魚眼と読み違えない
    assert source.suggested_projection == "flat"
