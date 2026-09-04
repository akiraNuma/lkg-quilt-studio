"""DIBR（Depth Image Based Rendering）による視点合成。

左画像基準の視差から、左右のどちらでもない位置の視点を作る。位置は
`position=0.0` が左カメラ、`1.0` が右カメラ。0 未満・1 超は外挿になる。

外挿では左に写っていない面が必ず露出する（disocclusion）。そこを右画像から
拾い、両方に写っていない画素だけを最後に inpaint で埋める。
"""

from dataclasses import dataclass
from typing import cast

import cv2
import numpy as np
from numpy.typing import NDArray

from .holes import DisparityMap, fill_horizontal
from .video import Frame


@dataclass(frozen=True)
class SynthesisParams:
    """視点合成の設定。"""

    crack_width: int = 2
    convergence: float = 0.0
    consistency_tolerance: float = 1.0
    inpaint_radius: int = 3

    # 遮蔽判定の許容差は視差に比例して緩める。視差が大きい面ほど推定の誤差も大きい
    tolerance_ratio: float = 0.05

    def __post_init__(self) -> None:
        if self.crack_width < 0:
            raise ValueError(f"crack_width は 0 以上（受け取った値: {self.crack_width}）")
        if self.inpaint_radius < 1:
            raise ValueError(f"inpaint_radius は 1 以上（受け取った値: {self.inpaint_radius}）")
        if self.tolerance_ratio < 0:
            raise ValueError(f"tolerance_ratio は 0 以上（受け取った値: {self.tolerance_ratio}）")


MINIMUM_AGREEMENT = 0.05
"""これ以下の一致度は信用しない（0 に落として穴として扱う）。

判定は一致度に掛ける。混ぜた後の重みに掛けると、視点が端に寄って片側の位置の重みが
小さいときに、正しく写っている画素まで穴へ落ちる。
"""


def view_positions(view_count: int, span: float) -> list[float]:
    """視点数と広がりから、各視点のカメラ位置を返す。

    `span=1.0` で左右カメラの間だけを使い、大きくすると両側へ外挿する。
    ステレオの基線は Looking Glass の視野角より狭いので既定では外挿するが、
    広げるほど穴埋めの面積が増えて画質が落ちる。
    """
    if view_count < 1:
        raise ValueError(f"view_count は 1 以上（受け取った値: {view_count}）")
    if span <= 0:
        raise ValueError(f"span は正の数（受け取った値: {span}）")
    if view_count == 1:
        return [0.5]
    return [0.5 + span * (index / (view_count - 1) - 0.5) for index in range(view_count)]


def forward_warp(disparity: DisparityMap, shift: float) -> tuple[DisparityMap, NDArray[np.bool_]]:
    """視差マップを `x + shift * disparity` の位置へ前進ワープする。

    同じ行の複数画素が同じ列に落ちたら視差の大きい方（＝手前の面）を採る。
    これで遮蔽が正しい側に出る。
    """
    height, width = disparity.shape
    columns = np.arange(width, dtype=np.float32)
    destination = np.rint(columns[None, :] + shift * disparity).astype(np.int64)
    rows = np.broadcast_to(np.arange(height, dtype=np.int64)[:, None], (height, width))
    inside = (destination >= 0) & (destination < width)

    warped = np.full((height, width), -np.inf, dtype=np.float32)
    np.maximum.at(warped, (rows[inside], destination[inside]), disparity[inside])
    valid = np.isfinite(warped)
    return np.where(valid, warped, 0.0).astype(np.float32), valid


class ViewSynthesizer:
    """1 フレーム分の左右画像と視差から、任意位置の視点を合成する。

    右画像基準の視差は左の視差を右視点へ前進ワープして作る。フレームごとに
    一度だけ用意して、視点ごとの合成で使い回す。

    ステレオマッチングから右基準の視差を直接取る手もある（`cv2.ximgproc.createRightMatcher`
    の出力は符号を反転すれば使える）が、**使うと品質が落ちる**。一致判定は左右の視差が
    互いに整合していることが前提で、独立に推定した 2 枚は許容差を越えてずれる。
    実測では穴の割合が平均 0.51 % から 5.51 %（最悪 19 %）へ悪化した
    （--display 16 / --span 2.0、許容差はすべて既定値での測定）。
    前進ワープで作れば整合は構造的に保証される。

    代わりに、左右のカメラ位置で穴の量が非対称になる（同じ条件で位置 0.0 が 0.00 %、
    位置 1.0 が 0.78 %）。ワープ自体が空ける穴の分だけ右側の判定が厳しいため。
    """

    def __init__(
        self, left: Frame, right: Frame, disparity: DisparityMap, params: SynthesisParams
    ) -> None:
        if left.shape != right.shape:
            raise ValueError(f"左右の形が違う: left={left.shape} right={right.shape}")
        if disparity.shape != left.shape[:2]:
            raise ValueError(f"視差の形が画像と違う: {disparity.shape} vs {left.shape[:2]}")
        self._left = left
        self._right = right
        self._params = params
        self._disparity_left = disparity
        warped, valid = forward_warp(disparity, -1.0)
        self._disparity_right, _ = fill_horizontal(warped, valid, max_gap=params.crack_width)

    def view(self, position: float) -> Frame:
        """`position` の位置から見た 1 枚を合成する。"""
        params = self._params
        height, width = self._disparity_left.shape
        columns = np.arange(width, dtype=np.float32)[None, :]
        rows = np.arange(height, dtype=np.float32)[:, None]
        row_map = np.broadcast_to(rows, (height, width)).astype(np.float32)

        # 収束面（視差 = convergence の面）が全視点で同じ位置に来るよう視差をずらす
        shifted = self._disparity_left - params.convergence
        warped, warp_valid = forward_warp(shifted, -position)
        target, _ = fill_horizontal(warped, warp_valid, max_gap=params.crack_width)
        assumed = target + params.convergence

        left_x = (columns + position * target).astype(np.float32)
        right_x = (columns - (1.0 - position) * target - params.convergence).astype(np.float32)

        left_color, left_valid = self._sample(
            self._left, self._disparity_left, left_x, row_map, assumed
        )
        right_color, right_valid = self._sample(
            self._right, self._disparity_right, right_x, row_map, assumed
        )

        left_weight = np.clip(1.0 - position, 0.0, 1.0) * left_valid
        right_weight = np.clip(position, 0.0, 1.0) * right_valid
        total = left_weight + right_weight
        blended = np.zeros((height, width, 3), dtype=np.float32)
        usable = total > 0.0
        np.divide(
            left_color * left_weight[..., None] + right_color * right_weight[..., None],
            total[..., None],
            out=blended,
            where=usable[..., None],
        )

        composed = np.clip(blended, 0.0, 255.0).astype(np.uint8)
        holes = (~usable).astype(np.uint8)
        if holes.any():
            filled = cv2.inpaint(composed, holes, params.inpaint_radius, cv2.INPAINT_TELEA)
            composed = cast(Frame, filled)
        return composed

    def _sample(
        self,
        image: Frame,
        reference: DisparityMap,
        map_x: DisparityMap,
        map_y: DisparityMap,
        assumed: DisparityMap,
    ) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
        """`map_x` の位置で色を拾い、その面が想定した視差とどれだけ一致するかも返す。

        拾った先の視差が想定と食い違う画素は、その視点では別の面に隠れている。
        一致判定を入れないと、遮蔽された面の色が引き伸ばされて混ざる。

        重みは 0 / 1 の二値にしない。境界が視点ごとに 1 px 単位で跳ぶと、
        再生時に輪郭がちらつく。許容差の 2 倍までを遷移域にして滑らかに落とす。
        """
        params = self._params
        sampled_x = np.ascontiguousarray(map_x, dtype=np.float32)
        color = cv2.remap(
            image, sampled_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
        ).astype(np.float32)
        found = cast(
            DisparityMap,
            cv2.remap(
                reference, sampled_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
            ),
        )
        tolerance = params.consistency_tolerance + params.tolerance_ratio * np.abs(assumed)
        error = np.abs(found - assumed)
        agreement = np.clip(2.0 - error / np.maximum(tolerance, 1e-6), 0.0, 1.0)
        # わずかに残った一致度で穴を「埋まった」ことにしない。落とさないと、
        # 奥行き境界の数 px が inpaint されず遮蔽色が薄く伸びる
        agreement = np.where(agreement > MINIMUM_AGREEMENT, agreement, 0.0)
        inside = (sampled_x >= 0.0) & (sampled_x <= float(image.shape[1] - 1))
        return color, (agreement * inside).astype(np.float32)
