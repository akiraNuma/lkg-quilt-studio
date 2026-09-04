"""quilt のレイアウト計算と合成。

仕様の出典: https://lookingglassfactory.com/tutorial/what-is-a-quilt
- 視点 0 は左下のタイル（最も左から見た絵）で、最後の視点が右上。左→右・下→上の順に並ぶ
- ファイル名は `<stem>_qs<columns>x<rows>a<aspect>.mp4` の規約に従う。ビューアはこれを読んで
  レイアウトを判定するので、規約から外れた名前で書き出さない
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .video import Frame


@dataclass(frozen=True)
class QuiltSpec:
    """quilt 1 枚の構成。`width` / `height` は quilt 全体の解像度。"""

    columns: int
    rows: int
    width: int
    height: int
    aspect: float

    def __post_init__(self) -> None:
        if self.columns < 1 or self.rows < 1:
            raise ValueError(f"列数・行数は 1 以上（{self.columns}x{self.rows}）")
        if self.width < self.columns or self.height < self.rows:
            raise ValueError(f"解像度がタイル数より小さい（{self.width}x{self.height}）")
        if self.aspect <= 0:
            raise ValueError(f"aspect は正の数（受け取った値: {self.aspect}）")

    @property
    def view_count(self) -> int:
        return self.columns * self.rows

    @property
    def tile_size(self) -> tuple[int, int]:
        """タイル 1 枚の描画サイズ（幅, 高さ）。

        公式プリセットは割り切れない組み合わせ（4096 / 5 = 819.2 など）がある。
        公式実装はタイルを整数サイズの格子にぴったり並べ、余った端の画素を
        「使わない余白」として UV 側で除外する（webxr ポリフィルの `quiltViewPortion`）。
        小数境界に置くと、どのタイルにも入らない列・行ができて黒い筋になる。
        切り上げると格子が quilt からはみ出すので、切り捨てる。
        """
        return self.width // self.columns, self.height // self.rows

    @property
    def margin(self) -> tuple[int, int]:
        """タイルの格子で埋まらない画素数（右端の列数, 上端の行数）。"""
        tile_width, tile_height = self.tile_size
        return self.width - self.columns * tile_width, self.height - self.rows * tile_height

    def tile_origin(self, view_index: int) -> tuple[int, int]:
        """視点のタイル左上座標を画像座標系（原点は左上）で返す。

        余白は画像の上端と右端に寄せる。テクスチャ座標の原点は左下なので、
        余白は U / V が 1 に近い側へ集まり、ビューア側の除外と一致する。
        """
        if not 0 <= view_index < self.view_count:
            raise ValueError(
                f"視点 {view_index} は範囲外（0〜{self.view_count - 1}）: "
                f"{self.columns}x{self.rows}"
            )
        tile_width, tile_height = self.tile_size
        column = view_index % self.columns
        # 視点 0 が左下。画像座標は原点が左上なので、下から数えた行を高さから引く
        row_from_bottom = view_index // self.columns
        return column * tile_width, self.height - (row_from_bottom + 1) * tile_height

    def compose(self, views: Sequence[Frame]) -> Frame:
        """視点画像を quilt 1 枚に並べる。視点の並びは視点 0 が先頭。"""
        if len(views) != self.view_count:
            raise ValueError(f"視点数が合わない: {len(views)} 枚 / {self.view_count} 必要")
        tile_width, tile_height = self.tile_size
        quilt = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        for index, view in enumerate(views):
            if view.shape != (tile_height, tile_width, 3):
                raise ValueError(
                    f"視点 {index} の形が違う: {view.shape} / ({tile_height}, {tile_width}, 3) 必要"
                )
            x, y = self.tile_origin(index)
            quilt[y : y + tile_height, x : x + tile_width] = view
        return self._fill_margin(quilt)

    def _fill_margin(self, quilt: Frame) -> Frame:
        """余白を隣のタイル端の色で埋める。

        ビューアは UV で余白を外すが、タイルの端では線形補間が余白側の画素も掴む。
        黒のまま残すと画面の最外周 1 px が暗くなる。
        """
        margin_x, margin_y = self.margin
        if margin_x:
            quilt[:, self.width - margin_x :] = quilt[:, [self.width - margin_x - 1]]
        if margin_y:
            quilt[:margin_y] = quilt[[margin_y]]
        return quilt

    def filename(self, stem: str, extension: str = "mp4") -> str:
        return f"{stem}_qs{self.columns}x{self.rows}a{self.aspect}.{extension}"


# 機種ごとのプリセット。値は実機の Bridge が返す `defaultQuilt` に合わせる
# （`available_output_devices` の `tileX` / `tileY` / `quiltX` / `quiltY` / `quiltAspect`）。
# 機種名は Bridge の `hardwareVersion` に対応する: go_p / standard_portrait / 8k など
PRESETS: dict[str, QuiltSpec] = {
    # Looking Glass Go は縦画面（1440x2560）なので aspect が 1 未満。横長の素材は余白が入る
    "go": QuiltSpec(columns=11, rows=6, width=4092, height=4092, aspect=0.5625),
    "portrait": QuiltSpec(columns=8, rows=6, width=3360, height=3360, aspect=0.75),
    "16": QuiltSpec(columns=5, rows=9, width=4096, height=4096, aspect=1.777),
    "32": QuiltSpec(columns=5, rows=9, width=8192, height=8192, aspect=1.777),
}
