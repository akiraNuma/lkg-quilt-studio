"""アップロードされた入力動画の置き場所。

プレビューと変換で同じファイルを使い回すために、ジョブとは別に持つ。
ジョブに紐づけて置くと、パラメータを変えるたびに数百 MB を上げ直すことになる。
"""

import json
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from .fisheye import Projection, guess_projection
from .stereo import StereoLayout, guess_layout, split_stereo
from .video import FfmpegError, VideoInfo, probe, read_frames

STATE_FILE = "source.json"


@dataclass(frozen=True)
class Source:
    """取り込んだ入力動画 1 本。`path` はサーバー上の実体。"""

    id: str
    name: str
    width: int
    height: int
    fps: float
    """probe が返す Fraction を JSON に載せるため float に落としてある。"""

    frame_count: int
    has_audio: bool
    suggested_layout: StereoLayout | None = None
    """左右の入り方の推定。当たらないこともあるので、画面では初期値として使うだけ。"""

    suggested_projection: Projection | None = None
    """写り方（平面 / 魚眼）の推定。同じく初期値として使うだけ。"""

    @property
    def stem(self) -> str:
        return Path(self.name).stem


class SourceStore:
    """入力動画を `root/<id>/` に置き、メタデータを `source.json` に書く。"""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._sources: dict[str, Source] = {}
        self._restore()

    def add(self, name: str, staged: Path) -> Source:
        """`staged` の動画を取り込む。`staged` は呼び出し側の一時ファイル。"""
        source_id = uuid.uuid4().hex
        directory = self._root / source_id
        directory.mkdir(parents=True)
        suffix = Path(name).suffix or ".mp4"
        target = directory / f"input{suffix}"
        staged.replace(target)

        # 壊れた動画はここで弾く。プレビューや変換まで持ち越すと原因が分かりにくい
        try:
            info = probe(target)
        except ValueError, FfmpegError, OSError:
            _remove_tree(directory)
            raise
        layout, projection = _inspect(info)

        source = Source(
            id=source_id,
            name=name,
            width=info.width,
            height=info.height,
            fps=float(info.fps),
            frame_count=info.frame_count,
            has_audio=info.has_audio,
            suggested_layout=layout,
            suggested_projection=projection,
        )
        self._write(source)
        return source

    def get(self, source_id: str) -> Source | None:
        with self._lock:
            return self._sources.get(source_id)

    def path(self, source_id: str) -> Path | None:
        """取り込んだ動画の実体を返す。無ければ None。"""
        if self.get(source_id) is None:
            return None
        for path in sorted((self._root / source_id).glob("input.*")):
            return path
        return None

    def all(self) -> list[Source]:
        with self._lock:
            return list(self._sources.values())

    def delete(self, source_id: str) -> bool:
        with self._lock:
            if self._sources.pop(source_id, None) is None:
                return False
        _remove_tree(self._root / source_id)
        return True

    def _write(self, source: Source) -> None:
        with self._lock:
            self._sources[source.id] = source
        directory = self._root / source.id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / STATE_FILE).write_text(
            json.dumps(asdict(source), ensure_ascii=False, indent=2)
        )

    def _restore(self) -> None:
        for state in sorted(self._root.glob(f"*/{STATE_FILE}")):
            try:
                source = Source(**json.loads(state.read_text()))
            # 古い形式や壊れた JSON は無視する。その入力が使えないだけで害はない
            except ValueError, TypeError:
                continue
            self._sources[source.id] = source


SAMPLE_POSITIONS = (0.2, 0.5, 0.8)
"""左右の入り方を見るコマの位置。真っ暗な冒頭や終端を避けるため中ほどから取る。"""


def _inspect(info: VideoInfo) -> tuple[StereoLayout | None, Projection | None]:
    """何コマか読んで左右の入り方と写り方を当てる。読めなければ諦める（画面で手で選べる）。"""
    frames = []
    for position in SAMPLE_POSITIONS:
        index = int(info.frame_count * position) if info.frame_count else 0
        try:
            frames.append(next(read_frames(info, start=index, count=1)))
        except ValueError, FfmpegError, OSError, StopIteration:
            continue
    layout = guess_layout(frames)
    if layout is None or layout == "separate":
        return layout, None
    projection = guess_projection([split_stereo(frame, layout)[0] for frame in frames])
    if projection == "flat":
        return layout, projection
    # 魚眼の円は画素の上で丸いので、潰してある入力（half 系）ではない。
    # half のまま平面として読むと横に 2 倍伸びる（実測の VR180 素材が sbs-half と判定された）
    return cast(StereoLayout, layout.removesuffix("-half")), projection


def _remove_tree(directory: Path) -> None:
    shutil.rmtree(directory, ignore_errors=True)
