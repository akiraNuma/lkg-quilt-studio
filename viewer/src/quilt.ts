// quilt のレイアウトはファイル名の規約から読む。変換側と数値を二重に持たないため。
// 規約と並び順の出典: https://lookingglassfactory.com/tutorial/what-is-a-quilt
//   `<stem>_qs<columns>x<rows>a<aspect>.mp4`（例: sample_qs5x9a1.777.mp4）

export type QuiltLayout = {
  columns: number
  rows: number
  aspect: number
}

const FILENAME_PATTERN = /_qs(\d+)x(\d+)a(\d+(?:\.\d+)?)\./

export function parseQuiltLayout(
  filename: string
): QuiltLayout | null {
  const matched = FILENAME_PATTERN.exec(filename)
  if (!matched) return null
  return {
    columns: Number(matched[1]),
    rows: Number(matched[2]),
    aspect: Number(matched[3]),
  }
}

export function viewCount(layout: QuiltLayout): number {
  return layout.columns * layout.rows
}

export type UvRect = {
  u: number
  v: number
  width: number
  height: number
}

// 視点 0 は quilt の左下タイル。テクスチャ座標も左下が原点なので、
// 画像座標のような上下の読み替えが要らない
export function tileUvRect(
  layout: QuiltLayout,
  viewIndex: number
): UvRect {
  const total = viewCount(layout)
  if (
    !Number.isInteger(viewIndex) ||
    viewIndex < 0 ||
    viewIndex >= total
  ) {
    throw new Error(
      `視点 ${viewIndex} は範囲外（0〜${total - 1}）: ${layout.columns}x${layout.rows}`
    )
  }
  return {
    u: (viewIndex % layout.columns) / layout.columns,
    v: Math.floor(viewIndex / layout.columns) / layout.rows,
    width: 1 / layout.columns,
    height: 1 / layout.rows,
  }
}
