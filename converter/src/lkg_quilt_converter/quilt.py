"""quilt のレイアウト計算。

仕様の出典: https://lookingglassfactory.com/tutorial/what-is-a-quilt
- 視点 0 は左下のタイル（最も左から見た絵）で、最後の視点が右上。左→右・下→上の順に並ぶ
- ファイル名は `<stem>_qs<columns>x<rows>a<aspect>.mp4` の規約に従う。ビューアはこれを読んで
  レイアウトを判定するので、規約から外れた名前で書き出さない
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class QuiltSpec:
    """quilt 1 枚の構成。`width` / `height` は quilt 全体の解像度。"""

    columns: int
    rows: int
    width: int
    height: int
    aspect: float

    @property
    def view_count(self) -> int:
        return self.columns * self.rows

    @property
    def tile_width(self) -> float:
        # 公式プリセットは割り切れない組み合わせ（4096 / 5 など）があるので float で返す。
        # ピクセルへの丸めは書き出し側の責務にする
        return self.width / self.columns

    @property
    def tile_height(self) -> float:
        return self.height / self.rows

    def tile_origin(self, view_index: int) -> tuple[float, float]:
        """視点のタイル左上座標を画像座標系（原点は左上）で返す。"""
        if not 0 <= view_index < self.view_count:
            raise ValueError(
                f"視点 {view_index} は範囲外（0〜{self.view_count - 1}）: "
                f"{self.columns}x{self.rows}"
            )
        column = view_index % self.columns
        row_from_bottom = view_index // self.columns
        # 視点 0 が左下なので、画像座標では下から数えた行を上から数えた行へ読み替える
        row_from_top = self.rows - 1 - row_from_bottom
        return column * self.tile_width, row_from_top * self.tile_height

    def filename(self, stem: str, extension: str = "mp4") -> str:
        return f"{stem}_qs{self.columns}x{self.rows}a{self.aspect}.{extension}"


# 機種ごとのプリセット（出典は本モジュール冒頭の URL）
PRESETS: dict[str, QuiltSpec] = {
    "portrait": QuiltSpec(columns=8, rows=6, width=3360, height=3360, aspect=0.75),
    "16": QuiltSpec(columns=5, rows=9, width=4096, height=4096, aspect=1.777),
    "32": QuiltSpec(columns=5, rows=9, width=8192, height=8192, aspect=1.777),
}
