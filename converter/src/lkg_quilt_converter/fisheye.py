"""魚眼（VR180）入力の平面化。円の検出と、中央視野の透視投影への再投影。

VR180 の素材は片眼ずつ 180° の魚眼像が円で入っている。**これは平面のステレオ対ではない。**
ステレオマッチングは同じ行に対応点がある前提で横方向だけを探すが、魚眼では中心から
離れるほど縦にもずれるので探索が合わない。合わない視差で視点を作るとブレて見える。

透視投影（rectilinear）へ直すと、平行な光軸・水平な基線という条件で対応点が同じ行に乗る。
円の中心は片眼ごとに測るので、左右の光軸のずれもここで吸収される。
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast, get_args

import cv2
import numpy as np
from numpy.typing import NDArray

from .video import Frame

Projection = Literal["flat", "fisheye"]
"""入力の写り方。`flat` は平面のステレオ対、`fisheye` は VR180 の魚眼。"""

PROJECTIONS: tuple[str, ...] = get_args(Projection)

SOURCE_FOV = 180.0
"""魚眼側の視野角（度）。VR180 の素材は 180° 等距離射影が事実上の標準。"""

DEFAULT_FOV = 60.0
"""平面へ直すときの水平視野角（度）。狭くするほど中央だけを使うので歪みが減る。"""

BLACK_LEVEL = 8
"""これ以下の輝度を円の外（黒枠）と見なす。圧縮のノイズで真っ黒にならないので 0 にしない。"""

MIN_FILL = 0.3
MAX_FILL = 0.95
"""絵が写っている面積の割合。魚眼の円は 3〜9 割に収まる（実測の 960x1080 で 65%）。"""

ROUNDNESS = 0.25
"""外形の縦横比の許容差。1 から離れていれば円ではない。"""


@dataclass(frozen=True)
class FisheyeCircle:
    """片眼のフレームに写っている魚眼の円。単位は画素。`radius` が θ=90° に対応する。"""

    center_x: float
    center_y: float
    radius: float

    def __post_init__(self) -> None:
        if self.radius <= 0:
            raise ValueError(f"radius は正の数（受け取った値: {self.radius}）")


def detect_circle(images: Sequence[Frame]) -> FisheyeCircle | None:
    """片眼のフレーム群から魚眼の円を測る。円が見つからなければ None。

    半径は**いちばん広い行と、いちばん高い列**から取る。境界に円を最小二乗で当てる方法は
    使わない。実測した素材の外形は真円より上下が広く（超楕円）、円として当てると
    半径が 437 px から 469 px へ膨らんだ。素材ごとの写り方の違いは視野角（`fov`）で吸収する。
    """
    mask = _content_mask(images)
    if mask is None:
        return None
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    width = int(xs.max() - xs.min()) + 1
    height = int(ys.max() - ys.min()) + 1
    # 外形が丸くないなら魚眼ではない（横長の 2 視点をそのまま渡された場合など）
    if abs(width / height - 1.0) > ROUNDNESS:
        return None
    fill = float(mask.sum()) / mask.size
    if not MIN_FILL <= fill <= MAX_FILL:
        return None
    widest = int(mask.sum(axis=1).max())
    tallest = int(mask.sum(axis=0).max())
    return FisheyeCircle(
        center_x=float(xs.min() + xs.max()) / 2.0,
        center_y=float(ys.min() + ys.max()) / 2.0,
        radius=(widest + tallest) / 4.0,
    )


def guess_projection(images: Sequence[Frame]) -> Projection:
    """片眼のフレーム群から写り方を当てる。円が見つかれば魚眼。"""
    return "fisheye" if detect_circle(images) is not None else "flat"


def rectilinear_maps(
    circle: FisheyeCircle,
    *,
    tile_size: tuple[int, int],
    tile_aspect: float,
    fov: float = DEFAULT_FOV,
    source_fov: float = SOURCE_FOV,
) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
    """魚眼からタイル 1 枚ぶんの透視投影を作る `cv2.remap` の写像を返す。

    等距離射影（`ρ = f * θ`）を仮定する。VR180 の素材はこれが事実上の標準で、
    円の半径が θ=90° に対応する。

    タイルの画素は表示上で正方形ではない（Go は 372x682 px を縦横比 0.5625 で出す）。
    視野角の計算を画素の比で行うと横に伸びるので、表示上の比で行う。
    """
    tile_width, tile_height = tile_size
    if tile_width < 1 or tile_height < 1:
        raise ValueError(f"タイルの大きさが不正（{tile_width}x{tile_height}）")
    if tile_aspect <= 0:
        raise ValueError(f"tile_aspect は正の数（受け取った値: {tile_aspect}）")
    if not 0.0 < fov < source_fov:
        raise ValueError(f"fov は 0 より大きく {source_fov} 未満（受け取った値: {fov}）")

    # 画素 1 つの表示上の幅 / 高さ。以降の長さは「縦画素」を単位にする
    pixel_aspect = tile_aspect / (tile_width / tile_height)
    focal = (tile_width * pixel_aspect / 2.0) / math.tan(math.radians(fov) / 2.0)

    u = (np.arange(tile_width, dtype=np.float32) + 0.5 - tile_width / 2.0) * pixel_aspect
    v = np.arange(tile_height, dtype=np.float32) + 0.5 - tile_height / 2.0
    grid_u, grid_v = np.meshgrid(u, v)
    distance = np.hypot(grid_u, grid_v)
    theta = np.arctan2(distance, focal)

    limit = math.radians(source_fov) / 2.0
    if float(theta.max()) > limit:
        raise ValueError(
            f"視野角 {fov}° ではタイルの隅が魚眼の外（{math.degrees(float(theta.max())):.0f}° > "
            f"{source_fov / 2:.0f}°）を指す。fov を下げる"
        )

    rho = circle.radius * theta / limit
    # 中心では distance=0 なので、割る前に下限を入れる（rho も 0 なので値は中心のまま）
    unit = rho / np.maximum(distance, 1e-6)
    map_x = (circle.center_x + unit * grid_u).astype(np.float32)
    map_y = (circle.center_y + unit * grid_v).astype(np.float32)
    return map_x, map_y


def rectify(image: Frame, maps: tuple[NDArray[np.float32], NDArray[np.float32]]) -> Frame:
    """`rectilinear_maps` の写像で 1 枚を平面へ直す。"""
    map_x, map_y = maps
    return cast(
        Frame,
        cv2.remap(image, map_x, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE),
    )


def _content_mask(images: Sequence[Frame]) -> NDArray[np.bool_] | None:
    """絵が写っている領域の真偽マップ。黒枠が無ければ None。

    「一度でも明るくなった画素」を有効とし、そこから**いちばん大きな連結成分だけ**を残して
    行ごとに塗り潰す。黒枠に浮くロゴや字幕を拾うと円が大きく外れ、絵の中の影を境界と
    読み違えると半径が伸びる（実測で 437 px の円が 466 px になった）。
    """
    if not images:
        return None
    grays = [cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) for image in images]
    brightest = np.maximum.reduce(grays)
    lit = (brightest > BLACK_LEVEL).astype(np.uint8)
    # 全面が明るいなら黒枠が無い＝魚眼ではない
    if not lit.size or bool(lit.all()):
        return None
    count, labels = cv2.connectedComponents(lit, connectivity=4)
    if count < 2:
        return None
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    body = labels == int(np.argmax(sizes))
    return _fill_rows(body)


def _fill_rows(mask: NDArray[np.bool_]) -> NDArray[np.bool_]:
    """行ごとに左端と右端の間を塗り潰す。円なら塗り潰した形が円そのものになる。"""
    filled = np.zeros_like(mask)
    columns = np.arange(mask.shape[1])
    for index, row in enumerate(mask):
        if not row.any():
            continue
        hit = columns[row]
        filled[index, hit[0] : hit[-1] + 1] = True
    return filled
