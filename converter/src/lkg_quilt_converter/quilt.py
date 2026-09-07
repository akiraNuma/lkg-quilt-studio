"""Quilt layout arithmetic and composition.

Specification: https://lookingglassfactory.com/tutorial/what-is-a-quilt
- View 0 is the bottom-left tile (the leftmost viewpoint) and the last view is top-right.
  Tiles run left to right, then bottom to top.
- Filenames follow `<stem>_qs<columns>x<rows>a<aspect>.mp4`. The viewer reads the layout from
  the name, so never write output under a name that breaks the convention.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .video import Frame


@dataclass(frozen=True)
class QuiltSpec:
    """One quilt's composition. `width` / `height` are the whole quilt's resolution."""

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
        """One tile's drawn size (width, height).

        Official presets include combinations that do not divide evenly (4096 / 5 = 819.2).
        The official implementation packs tiles into an integer-sized grid and excludes the
        leftover edge pixels through UVs (`quiltViewPortion` in the webxr polyfill).
        Fractional boundaries leave columns or rows outside every tile, which show up as black
        seams. Rounding up would push the grid past the quilt, so round down.
        """
        return self.width // self.columns, self.height // self.rows

    @property
    def margin(self) -> tuple[int, int]:
        """Pixels the tile grid does not fill (columns at the right, rows at the top)."""
        tile_width, tile_height = self.tile_size
        return self.width - self.columns * tile_width, self.height - self.rows * tile_height

    def tile_origin(self, view_index: int) -> tuple[int, int]:
        """Return a view's top-left tile coordinate in image space (origin at the top left).

        Padding is pushed to the top and right edges. Texture coordinates start at the bottom
        left, so the padding collects where U / V approach 1, matching what the viewer excludes.
        """
        if not 0 <= view_index < self.view_count:
            raise ValueError(
                f"視点 {view_index} は範囲外（0〜{self.view_count - 1}）: "
                f"{self.columns}x{self.rows}"
            )
        tile_width, tile_height = self.tile_size
        column = view_index % self.columns
        # View 0 is bottom-left. Image space starts at the top, so subtract the row counted
        # from the bottom from the height
        row_from_bottom = view_index // self.columns
        return column * tile_width, self.height - (row_from_bottom + 1) * tile_height

    def compose(self, views: Sequence[Frame]) -> Frame:
        """Arrange view images into one quilt. The sequence starts at view 0."""
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
        """Fill the padding with the colour of the neighbouring tile edge.

        The viewer excludes padding through UVs, but linear interpolation at a tile edge still
        samples pixels on the padding side. Leaving it black darkens the outermost pixel.
        """
        margin_x, margin_y = self.margin
        if margin_x:
            quilt[:, self.width - margin_x :] = quilt[:, [self.width - margin_x - 1]]
        if margin_y:
            quilt[:margin_y] = quilt[[margin_y]]
        return quilt

    def filename(self, stem: str, extension: str = "mp4") -> str:
        return f"{stem}_qs{self.columns}x{self.rows}a{self.aspect}.{extension}"


# Per-model presets. Values match `defaultQuilt` as Bridge reports it on real hardware
# (`tileX` / `tileY` / `quiltX` / `quiltY` / `quiltAspect` from `available_output_devices`).
# Model names follow Bridge's `hardwareVersion`: go_p / standard_portrait / 8k and so on
PRESETS: dict[str, QuiltSpec] = {
    # Looking Glass Go is portrait (1440x2560), so aspect is below 1. Landscape sources get padding
    "go": QuiltSpec(columns=11, rows=6, width=4092, height=4092, aspect=0.5625),
    "portrait": QuiltSpec(columns=8, rows=6, width=3360, height=3360, aspect=0.75),
    "16": QuiltSpec(columns=5, rows=9, width=4096, height=4096, aspect=1.777),
    "32": QuiltSpec(columns=5, rows=9, width=8192, height=8192, aspect=1.777),
}
