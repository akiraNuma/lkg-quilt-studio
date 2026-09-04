"""入力ステレオ動画の整形。左右の切り出しと、quilt のタイル 1 枚への収め方。"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast, get_args

import cv2
import numpy as np

from .video import Frame

StereoLayout = Literal["sbs", "sbs-half", "tb", "tb-half", "separate"]

LAYOUTS: tuple[str, ...] = get_args(StereoLayout)

FitMode = Literal["pad", "crop"]
"""タイルの縦横比と入力の縦横比が違うときの収め方。crop は切り落とし、pad は余白を足す。

既定は crop。切り出した範囲を画面いっぱいに拡大するので視差も同じ倍率で増え、立体感が強く出る。
"""

FIT_MODES: tuple[str, ...] = get_args(FitMode)

# half 系は片眼が横（または縦）に圧縮されて入っている。画素の縦横比で戻す
PIXEL_ASPECT: dict[str, float] = {
    "sbs": 1.0,
    "sbs-half": 2.0,
    "tb": 1.0,
    "tb-half": 0.5,
    "separate": 1.0,
}


def split_stereo(frame: Frame, layout: StereoLayout) -> tuple[Frame, Frame]:
    """1 枚のフレームから左眼・右眼を切り出す。"""
    height, width = frame.shape[:2]
    if layout in ("sbs", "sbs-half"):
        if width % 2:
            raise ValueError(f"横並びの入力は幅が偶数である必要がある（{width}）")
        middle = width // 2
        return frame[:, :middle], frame[:, middle:]
    if layout in ("tb", "tb-half"):
        if height % 2:
            raise ValueError(f"縦並びの入力は高さが偶数である必要がある（{height}）")
        middle = height // 2
        return frame[:middle], frame[middle:]
    raise ValueError(f"{layout} は 1 本の動画から左右を切り出せない")


def guess_layout(frames: Sequence[Frame]) -> StereoLayout | None:
    """何コマかから左右の入り方を当てる。判断がつかなければ None。

    ステレオ対なら、切り分けた 2 枚は視差の分だけずれた同じ絵になる。無関係な絵より
    平均絶対差がはるかに小さいので、左右で割った差と上下で割った差を比べれば向きが分かる。
    たまたま片側が似ているコマもあるので、複数コマの平均で決める。

    潰してある入力（`sbs-half` / `tb-half`）は切り分け方が同じで縦横比だけ違うので、
    片眼の縦横比が不自然かどうかで見分ける。
    """
    scores = [_halves_difference(frame) for frame in frames if min(frame.shape[:2]) >= 2]
    if not scores:
        return None
    side_by_side = float(np.mean([score[0] for score in scores]))
    top_bottom = float(np.mean([score[1] for score in scores]))

    # 片方がもう片方の 6 割を下回らないと、ステレオだと言い切れない
    # （ふつうの 2D 動画はどちらで割っても無関係な絵なので、両方とも大きく出る）
    if min(side_by_side, top_bottom) > 0.6 * max(side_by_side, top_bottom):
        return None
    height, width = frames[0].shape[:2]
    if side_by_side < top_bottom:
        # 片眼が正方形に近いほど横に潰されている。16:9 を横半分にすると 8:9
        return "sbs-half" if (width / 2) / height < 1.2 else "sbs"
    return "tb-half" if width / (height / 2) > 2.4 else "tb"


def _halves_difference(frame: Frame) -> tuple[float, float]:
    """(左右で割った差, 上下で割った差) を平均絶対差で返す。"""
    height, width = frame.shape[:2]
    values = frame.astype(np.float32)
    return (
        float(np.abs(values[:, : width // 2] - values[:, width // 2 :]).mean()),
        float(np.abs(values[: height // 2] - values[height // 2 :]).mean()),
    )


@dataclass(frozen=True)
class TileFit:
    """入力フレーム 1 枚をタイル 1 枚へ収める写像。左右の眼で同じものを使う。"""

    source: tuple[int, int, int, int]
    """入力から切り出す矩形 (x, y, 幅, 高さ)。"""

    content_size: tuple[int, int]
    """タイルの中で絵が占める大きさ (幅, 高さ)。視差推定と視点合成はこの解像度で行う。"""

    offset: tuple[int, int]
    """タイル内で絵を置く左上座標 (x, y)。"""

    tile_size: tuple[int, int]
    """タイル 1 枚の画素数 (幅, 高さ)。"""

    @property
    def padded(self) -> bool:
        return self.content_size != self.tile_size


def crop_rect(
    width: int, height: int, pixel_aspect: float, target_aspect: float
) -> tuple[int, int, int, int]:
    """表示上の縦横比を `target_aspect` に合わせる中央切り出し矩形 (x, y, 幅, 高さ) を返す。"""
    if width < 1 or height < 1:
        raise ValueError(f"大きさが不正（{width}x{height}）")
    if pixel_aspect <= 0 or target_aspect <= 0:
        raise ValueError(f"縦横比は正の数（pixel={pixel_aspect} target={target_aspect}）")

    displayed = width * pixel_aspect / height
    if displayed > target_aspect:
        cropped = max(1, min(width, round(height * target_aspect / pixel_aspect)))
        return (width - cropped) // 2, 0, cropped, height
    cropped = max(1, min(height, round(width * pixel_aspect / target_aspect)))
    return 0, (height - cropped) // 2, width, cropped


def plan_fit(
    width: int,
    height: int,
    *,
    pixel_aspect: float,
    tile_size: tuple[int, int],
    tile_aspect: float,
    mode: FitMode,
) -> TileFit:
    """入力の大きさとタイルの仕様から収め方を決める。

    タイルの画素の縦横比（`tile_size` の比）と表示上の縦横比（`tile_aspect`）は一致しない。
    Looking Glass Go は 4092x4092 を 11x6 に割るのでタイルは 372x682 画素だが、
    表示上は 0.5625（縦長）として出る。余白の量は表示上の比で計算しないと合わない。
    """
    tile_width, tile_height = tile_size
    if tile_width < 1 or tile_height < 1:
        raise ValueError(f"タイルの大きさが不正（{tile_width}x{tile_height}）")
    if mode == "crop":
        return TileFit(
            source=crop_rect(width, height, pixel_aspect, tile_aspect),
            content_size=tile_size,
            offset=(0, 0),
            tile_size=tile_size,
        )
    if width < 1 or height < 1:
        raise ValueError(f"大きさが不正（{width}x{height}）")
    if pixel_aspect <= 0 or tile_aspect <= 0:
        raise ValueError(f"縦横比は正の数（pixel={pixel_aspect} tile={tile_aspect}）")

    displayed = width * pixel_aspect / height
    if displayed > tile_aspect:
        inner_height = max(1, min(tile_height, round(tile_height * tile_aspect / displayed)))
        content = (tile_width, inner_height)
        offset = (0, (tile_height - inner_height) // 2)
    else:
        inner_width = max(1, min(tile_width, round(tile_width * displayed / tile_aspect)))
        content = (inner_width, tile_height)
        offset = ((tile_width - inner_width) // 2, 0)
    return TileFit(
        source=(0, 0, width, height),
        content_size=content,
        offset=offset,
        tile_size=tile_size,
    )


def fit_content(image: Frame, fit: TileFit) -> Frame:
    """入力を切り出して `content_size` へ伸縮する。余白はまだ足さない。

    視差推定と視点合成は余白の無い状態で行う。真っ黒な余白は左右で同じ絵なので
    ステレオマッチングが視差を決められず、自動の収束面（視差の中央値）まで狂わせる。
    """
    x, y, width, height = fit.source
    content_width, content_height = fit.content_size
    cropped = image[y : y + height, x : x + width]
    # 縮小なら INTER_AREA、拡大なら INTER_CUBIC。tb-half のように縦だけ縮む入力もあるので
    # 幅だけで決めず、面積で見る
    shrinking = width * height > content_width * content_height
    interpolation = cv2.INTER_AREA if shrinking else cv2.INTER_CUBIC
    # cv2 の型定義は dtype を保たないので、rgb24 のままだと分かっている戻り値を読み替える
    return cast(Frame, cv2.resize(cropped, fit.content_size, interpolation=interpolation))


def pad_to_tile(image: Frame, fit: TileFit) -> Frame:
    """合成済みの絵をタイルの大きさに合わせる。余白が要らなければ素通しする。"""
    if not fit.padded:
        return image
    tile_width, tile_height = fit.tile_size
    content_width, content_height = fit.content_size
    x, y = fit.offset
    tile = np.zeros((tile_height, tile_width, 3), dtype=image.dtype)
    tile[y : y + content_height, x : x + content_width] = image
    return cast(Frame, tile)
