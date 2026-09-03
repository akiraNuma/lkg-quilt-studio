import { describe, expect, it } from 'vitest'
import { parseQuiltLayout, tileUvRect, viewCount } from './quilt'

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

describe('tileUvRect', () => {
  const layout = { columns: 5, rows: 9, aspect: 1.777 }

  it('視点 0 は左下', () => {
    expect(tileUvRect(layout, 0)).toEqual({
      u: 0,
      v: 0,
      width: 1 / 5,
      height: 1 / 9,
    })
  })

  it('最後の視点は右上', () => {
    const rect = tileUvRect(layout, viewCount(layout) - 1)
    expect(rect.u).toBeCloseTo(1 - 1 / 5)
    expect(rect.v).toBeCloseTo(1 - 1 / 9)
  })

  it('列を跨ぐと 1 段上へ進む', () => {
    expect(tileUvRect(layout, 5).v).toBeCloseTo(1 / 9)
    expect(tileUvRect(layout, 5).u).toBe(0)
  })

  it('範囲外の視点は例外', () => {
    expect(() => tileUvRect(layout, viewCount(layout))).toThrow()
  })
})
