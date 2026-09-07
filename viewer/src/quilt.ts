// The quilt layout is read from the filename convention, so the numbers are not duplicated from
// the converter. Convention and tile order: https://lookingglassfactory.com/tutorial/what-is-a-quilt
//   `<stem>_qs<columns>x<rows>a<aspect>.mp4` (for example sample_qs5x9a1.777.mp4)

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

/** The quilt composition a model expects, as returned by Bridge's `getDisplays()`. */
export type DisplayQuilt = {
  columns: number
  rows: number
  quiltAspect: number
}

/**
 * Describe, in the user's language, how a video's quilt layout disagrees with the connected
 * model. Returns null when they agree. Different columns or rows misassign the views
 */
export type DisplayPreset = {
  columns: number
  rows: number
  aspect: number
}

/**
 * Return the name of the conversion preset matching the connected model's quilt, or null.
 * A wrong model wastes an entire conversion, so the screen's default comes from here
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
