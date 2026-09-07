import { beforeEach, describe, expect, it } from 'vitest'
import { setLocale } from './i18n'
import {
  layoutMismatch,
  matchPreset,
  parseQuiltLayout,
} from './quilt'

// The wording changes with the language; do not depend on the environment locale
beforeEach(() => setLocale('ja'))

describe('parseQuiltLayout', () => {
  it('reads the layout from the filename convention', () => {
    expect(parseQuiltLayout('sample_qs5x9a1.777.mp4')).toEqual({
      columns: 5,
      rows: 9,
      aspect: 1.777,
    })
  })

  it('reads an integer aspect ratio too', () => {
    expect(parseQuiltLayout('sample_qs8x6a1.mp4')?.aspect).toBe(1)
  })

  it('returns null for a name outside the convention', () => {
    expect(parseQuiltLayout('sample.mp4')).toBeNull()
  })
})

describe('layoutMismatch', () => {
  const display = { columns: 5, rows: 9, quiltAspect: 1.777 }

  it('returns null when they agree', () => {
    expect(
      layoutMismatch({ columns: 5, rows: 9, aspect: 1.777 }, display)
    ).toBeNull()
  })

  it('reports a tile-count difference', () => {
    const message = layoutMismatch(
      { columns: 8, rows: 6, aspect: 1.777 },
      display
    )
    expect(message).toContain('タイル数が違う')
  })

  it('reports an aspect-ratio difference', () => {
    const message = layoutMismatch(
      { columns: 5, rows: 9, aspect: 0.75 },
      display
    )
    expect(message).toContain('縦横比が違う')
  })

  it('ignores a negligible aspect-ratio difference', () => {
    expect(
      layoutMismatch({ columns: 5, rows: 9, aspect: 1.78 }, display)
    ).toBeNull()
  })
})

describe('matchPreset', () => {
  const presets = {
    '16': { columns: 5, rows: 9, aspect: 1.777 },
    go: { columns: 11, rows: 6, aspect: 0.5625 },
  }

  it('returns the preset matching the connected model', () => {
    expect(
      matchPreset(
        { columns: 11, rows: 6, quiltAspect: 0.5625 },
        presets
      )
    ).toBe('go')
  })

  it('treats a negligible aspect difference as the same model', () => {
    expect(
      matchPreset(
        { columns: 5, rows: 9, quiltAspect: 1.7778 },
        presets
      )
    ).toBe('16')
  })

  it('returns null when the tile counts disagree', () => {
    expect(
      matchPreset({ columns: 8, rows: 6, quiltAspect: 0.75 }, presets)
    ).toBeNull()
  })
})
