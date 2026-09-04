"""視差推定。左画像を基準にした画素単位の視差を返す。

視差 `d` は `left[x] ≒ right[x - d]` の関係で、手前の面ほど大きい。**符号は正に限らない。**
収束面（画面と同じ奥行きに見える面）より奥にある面は負の視差を持つ。

既定は重みの取得が要らない SGBM + WLS フィルタ。時間的一貫性を持つ深層モデル
（候補は `.claude/rules/external-apis.md`）へ差し替えられるよう、
`DisparityEstimator` の形だけを固定してある。
"""

from dataclasses import dataclass
from typing import Protocol, cast

import cv2
import numpy as np
from numpy.typing import NDArray

from .holes import DisparityMap, fill_horizontal
from .video import Frame

GrayFrame = NDArray[np.uint8]
"""(高さ, 幅) のグレースケール画像。"""


@dataclass(frozen=True)
class DisparityParams:
    """視差推定の設定。

    探索する視差は `[min_disparity, min_disparity + max_disparity)` の範囲。
    `min_disparity` を 0 にすると**画面より手前に飛び出す面（負の視差）が見つからず**、
    その面の奥行きが 0 に潰れる。撮影時の収束面がどこにあるか分からないので、
    既定では正負の両側を探す。
    """

    max_disparity: int = 128
    min_disparity: int = -64
    block_size: int = 5
    downscale: int = 1
    wls_lambda: float = 8000.0
    wls_sigma: float = 1.5
    temporal_weight: float = 0.35
    temporal_threshold: float = 4.0

    def __post_init__(self) -> None:
        # numDisparities は 16 の倍数でないと SGBM が例外を投げる
        if self.max_disparity <= 0 or self.max_disparity % 16:
            raise ValueError(
                f"max_disparity は 16 の倍数の正数（受け取った値: {self.max_disparity}）"
            )
        if self.block_size < 1 or self.block_size % 2 == 0:
            raise ValueError(f"block_size は奇数の正数（受け取った値: {self.block_size}）")
        if self.min_disparity + self.max_disparity <= 0:
            raise ValueError(
                "探索範囲の上端が 0 以下で手前の面が見つからない"
                f"（min_disparity={self.min_disparity} max_disparity={self.max_disparity}）"
            )
        if self.downscale < 1:
            raise ValueError(f"downscale は 1 以上（受け取った値: {self.downscale}）")
        if not 0.0 < self.temporal_weight <= 1.0:
            raise ValueError(
                f"temporal_weight は 0 より大きく 1 以下（受け取った値: {self.temporal_weight}）"
            )


class DisparityEstimator(Protocol):
    """1 フレーム分の左右画像から視差マップを返す推定器。"""

    def estimate(self, left: Frame, right: Frame) -> DisparityMap: ...

    def seed(self, disparity: DisparityMap) -> None:
        """前フレームの視差を外から入れる。キャッシュから読んで estimate を飛ばしたとき、
        時間方向の平滑化の連鎖が切れて視差が跳ねるのを防ぐ。"""
        ...


def blend_temporal(
    current: DisparityMap,
    previous: DisparityMap | None,
    *,
    weight: float,
    threshold: float,
) -> DisparityMap:
    """前フレームの視差と混ぜてちらつきを抑える。

    単純な指数移動平均だと動く被写体が引きずられるので、前フレームとの差が
    `threshold` 画素を超えた画素は混ぜずに今フレームの値を採る。
    """
    if previous is None:
        return current
    if previous.shape != current.shape:
        raise ValueError(f"形が違う: current={current.shape} previous={previous.shape}")
    smoothed = weight * current + (1.0 - weight) * previous
    moved = np.abs(current - previous) > threshold
    return np.where(moved, current, smoothed).astype(np.float32)


class SgbmDisparityEstimator:
    """SGBM + WLS フィルタによる視差推定。フレーム間は `blend_temporal` で平滑化する。"""

    def __init__(self, params: DisparityParams) -> None:
        self._params = params
        self._previous: DisparityMap | None = None

        block = params.block_size
        self._left_matcher = cv2.StereoSGBM.create(
            minDisparity=_search_start(params),
            numDisparities=_search_range(params),
            blockSize=block,
            # P1 / P2 は視差の変化への罰則。OpenCV のサンプルが使う 8/32 × チャンネル数 × 窓面積
            P1=8 * block * block,
            P2=32 * block * block,
            disp12MaxDiff=1,
            uniquenessRatio=10,
            speckleWindowSize=100,
            speckleRange=2,
            preFilterCap=63,
            mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
        )
        self._right_matcher = cv2.ximgproc.createRightMatcher(self._left_matcher)
        self._filter = cv2.ximgproc.createDisparityWLSFilter(self._left_matcher)
        self._filter.setLambda(params.wls_lambda)
        self._filter.setSigmaColor(params.wls_sigma)

    def seed(self, disparity: DisparityMap) -> None:
        self._previous = disparity

    def estimate(self, left: Frame, right: Frame) -> DisparityMap:
        if left.shape != right.shape:
            raise ValueError(f"左右の形が違う: left={left.shape} right={right.shape}")
        scale = self._params.downscale
        # 探索範囲が画像幅と同程度以上だと SGBM が内部で巨大なバッファを要求して
        # cv2.error（Insufficient memory）になる。原因の分かる形で先に落とす
        search = _search_range(self._params)
        usable_width = max(left.shape[1] // scale, 1)
        if search >= usable_width:
            raise ValueError(
                f"視差の探索範囲 {search} px がタイル幅 {usable_width} px 以上で、"
                "ステレオマッチングが動かない。"
                "--max-disparity を下げるか quilt の解像度を上げる"
            )
        small_left = _to_gray(left, scale)
        small_right = _to_gray(right, scale)

        raw_left = self._left_matcher.compute(small_left, small_right)
        raw_right = self._right_matcher.compute(small_right, small_left)
        filtered = self._filter.filter(raw_left, small_left, None, raw_right)

        # SGBM / WLS は視差を 16 倍した固定小数点で返す
        disparity = filtered.astype(np.float32) / 16.0
        # SGBM は対応が取れなかった画素に (minDisparity - 1) を入れて返す。
        # 探索範囲の下端そのものは正当な値なので、それより下だけを無効と見なす
        valid = disparity >= float(_search_start(self._params))
        disparity, _ = fill_horizontal(disparity, valid)

        if scale > 1:
            height, width = left.shape[:2]
            upscaled = cv2.resize(disparity, (width, height), interpolation=cv2.INTER_LINEAR)
            disparity = cast(DisparityMap, upscaled) * float(scale)

        disparity = blend_temporal(
            disparity,
            self._previous,
            weight=self._params.temporal_weight,
            threshold=self._params.temporal_threshold,
        )
        self._previous = disparity
        return disparity


def photometric_residual(left: Frame, right: Frame, disparity: DisparityMap) -> float:
    """視差で右画像を左視点へ戻したときの平均絶対誤差。

    視差の当たり外れを 1 つの数で見るための指標。左右が逆に入っていると、
    どの視差を選んでも画像を説明できないので大きな値になる。
    """
    height, width = disparity.shape
    columns = np.arange(width, dtype=np.float32)[None, :]
    rows = np.broadcast_to(np.arange(height, dtype=np.float32)[:, None], (height, width))
    sampled_x = np.ascontiguousarray(columns - disparity, dtype=np.float32)
    warped = cv2.remap(
        right,
        sampled_x,
        np.ascontiguousarray(rows, dtype=np.float32),
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    inside = (sampled_x >= 0.0) & (sampled_x <= float(width - 1))
    difference = np.abs(left.astype(np.float32) - warped.astype(np.float32)).mean(axis=2)
    return float(difference[inside].mean())


def _search_range(params: DisparityParams) -> int:
    """縮小して推定する分だけ探索範囲も狭める。16 の倍数に丸める。

    SGBM の numDisparities は 16 の倍数でないと例外になる。
    """
    return max(16, round(params.max_disparity / params.downscale / 16.0) * 16)


def _search_start(params: DisparityParams) -> int:
    """縮小して推定する分だけ探索の下端も詰める。"""
    return round(params.min_disparity / params.downscale)


def _to_gray(frame: Frame, scale: int) -> GrayFrame:
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    if scale == 1:
        return cast(GrayFrame, gray)
    height, width = gray.shape[:2]
    size = (max(width // scale, 1), max(height // scale, 1))
    return cast(GrayFrame, cv2.resize(gray, size, interpolation=cv2.INTER_AREA))
