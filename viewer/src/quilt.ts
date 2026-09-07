// quilt のレイアウトはファイル名の規約から読む。変換側と数値を二重に持たないため。
// 規約と並び順の出典: https://lookingglassfactory.com/tutorial/what-is-a-quilt
//   `<stem>_qs<columns>x<rows>a<aspect>.mp4`（例: sample_qs5x9a1.777.mp4）

import { t } from './i18n'

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

/** Bridge の `getDisplays()` が返す、機種が想定する quilt の構成。 */
export type DisplayQuilt = {
  columns: number
  rows: number
  quiltAspect: number
}

/**
 * 動画の quilt レイアウトが接続中の機種と噛み合わない点を日本語で返す。
 * 噛み合っていれば null。列数・行数が違うと視点の振り分けがずれる
 */
export type DisplayPreset = {
  columns: number
  rows: number
  aspect: number
}

/**
 * 接続中の機種の quilt に一致する変換プリセットの名前を返す。無ければ null。
 * 機種の指定を間違えると変換が丸ごと無駄になるので、画面の既定値をここから決める
 */
export function matchPreset(
  display: DisplayQuilt,
  presets: Record<string, DisplayPreset>
): string | null {
  for (const [name, preset] of Object.entries(presets)) {
    if (
      preset.columns === display.columns &&
      preset.rows === display.rows &&
      Math.abs(preset.aspect - display.quiltAspect) <= 0.02
    )
      return name
  }
  return null
}

export function layoutMismatch(
  layout: QuiltLayout,
  display: DisplayQuilt
): string | null {
  const problems: string[] = []
  if (
    layout.columns !== display.columns ||
    layout.rows !== display.rows
  ) {
    problems.push(
      t('quilt.mismatchTiles', {
        video: `${layout.columns}x${layout.rows}`,
        display: `${display.columns}x${display.rows}`,
      })
    )
  }
  if (Math.abs(layout.aspect - display.quiltAspect) > 0.02) {
    problems.push(
      t('quilt.mismatchAspect', {
        video: layout.aspect,
        display: display.quiltAspect,
      })
    )
  }
  return problems.length ? problems.join(' / ') : null
}
