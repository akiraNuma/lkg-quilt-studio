import { describe, expect, it } from 'vitest'
import {
  layoutMismatch,
  matchPreset,
  parseQuiltLayout,
} from './quilt'

describe('parseQuiltLayout', () => {
  it('ファイル名の規約からレイアウトを読む', () => {
    expect(parseQuiltLayout('sample_qs5x9a1.777.mp4')).toEqual({
      columns: 5,
      rows: 9,
      aspect: 1.777,
    })
  })

  it('整数のアスペクト比も読む', () => {
    expect(parseQuiltLayout('sample_qs8x6a1.mp4')?.aspect).toBe(1)
  })

  it('規約に合わない名前は null を返す', () => {
    expect(parseQuiltLayout('sample.mp4')).toBeNull()
  })
})

describe('layoutMismatch', () => {
  const display = { columns: 5, rows: 9, quiltAspect: 1.777 }

  it('噛み合っていれば null', () => {
    expect(
      layoutMismatch({ columns: 5, rows: 9, aspect: 1.777 }, display)
    ).toBeNull()
  })

  it('タイル数の違いを指摘する', () => {
    const message = layoutMismatch(
      { columns: 8, rows: 6, aspect: 1.777 },
      display
    )
    expect(message).toContain('タイル数が違う')
  })

  it('縦横比の違いを指摘する', () => {
    const message = layoutMismatch(
      { columns: 5, rows: 9, aspect: 0.75 },
      display
    )
    expect(message).toContain('縦横比が違う')
  })

  it('わずかな縦横比の差は指摘しない', () => {
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

  it('接続中の機種に一致するプリセットを返す', () => {
    expect(
      matchPreset(
        { columns: 11, rows: 6, quiltAspect: 0.5625 },
        presets
      )
    ).toBe('go')
  })

  it('縦横比のわずかな差は同じ機種と見なす', () => {
    expect(
      matchPreset(
        { columns: 5, rows: 9, quiltAspect: 1.7778 },
        presets
      )
    ).toBe('16')
  })

  it('タイル数が合わなければ null', () => {
    expect(
      matchPreset({ columns: 8, rows: 6, quiltAspect: 0.75 }, presets)
    ).toBeNull()
  })
})
