import { describe, expect, it } from 'vitest'
import {
  fragmentShader,
  lenticularParams,
  viewPortion,
  type Calibration,
} from './lenticular'

// Values equivalent to a Looking Glass Portrait. The numbers themselves arrive from Bridge
// per model
const CALIBRATION: Calibration = {
  pitch: 52.58,
  slope: -7.19,
  center: 0.18,
  DPI: 324,
  screenW: 1536,
  screenH: 2048,
  flipImageX: 0,
  invView: 1,
}

const LAYOUT = { columns: 5, rows: 9, aspect: 1.777 }

describe('lenticularParams', () => {
  it('converts pitch to lenses across the screen width', () => {
    expect(lenticularParams(CALIBRATION).pitch).toBeCloseTo(
      246.8916717,
      6
    )
  })

  it('derives tilt and subpixel spacing from the screen ratio', () => {
    const params = lenticularParams(CALIBRATION)
    expect(params.tilt).toBeCloseTo(-0.1854427, 6)
    expect(params.subp).toBeCloseTo(0.000217014, 9)
    expect(params.center).toBe(0.18)
    expect(params.invertView).toBe(true)
  })

  it('flips the sign of tilt and subpixel when flipImageX is set', () => {
    const flipped = lenticularParams({
      ...CALIBRATION,
      flipImageX: 1,
    })
    expect(flipped.tilt).toBeCloseTo(0.1854427, 6)
    expect(flipped.subp).toBeLessThan(0)
    // pitch carries no sign
    expect(flipped.pitch).toBeCloseTo(246.8916717, 6)
  })

  it('does not reverse the view order when invView is 0', () => {
    expect(
      lenticularParams({ ...CALIBRATION, invView: 0 }).invertView
    ).toBe(false)
  })

  it.each([{ screenW: 0 }, { screenH: 0 }, { DPI: 0 }, { slope: 0 }])(
    'throws on broken values (%o)',
    overrides => {
      expect(() =>
        lenticularParams({ ...CALIBRATION, ...overrides })
      ).toThrow()
    }
  )
})

describe('viewPortion', () => {
  it('leaves no padding when the resolution divides evenly', () => {
    expect(
      viewPortion({ columns: 8, rows: 6, aspect: 0.75 }, 3360, 3360)
    ).toEqual({ u: 1, v: 1 })
  })

  it('excludes the edge pixel when the resolution does not divide evenly', () => {
    // 4096 / 5 = 819.2, so a tile is 819 wide and the grid fills only 4095 px
    const portion = viewPortion(LAYOUT, 4096, 4096)
    expect(portion.u).toBeCloseTo(4095 / 4096, 10)
    expect(portion.v).toBeCloseTo(4095 / 4096, 10)
  })

  it('throws when the resolution is smaller than the tile count', () => {
    expect(() => viewPortion(LAYOUT, 4, 4096)).toThrow()
  })
})

describe('fragmentShader', () => {
  const source = fragmentShader(lenticularParams(CALIBRATION), LAYOUT)

  it('bakes the view count and tile counts in as constants', () => {
    expect(source).toContain('const float tileCount = 45.00000000')
    expect(source).toContain('const float rows = 9.000000000')
    // The precision guard shortens the column count slightly
    expect(source).toContain('const float columns = 4.999990000')
  })

  it('switches the inversion formula on invView', () => {
    expect(source).toContain('views = 1.0 - fract(views);')
    const notInverted = fragmentShader(
      lenticularParams({ ...CALIBRATION, invView: 0 }),
      LAYOUT
    )
    expect(notInverted).toContain('views = fract(views);')
  })

  it('applies the padding exclusion to tile coordinates', () => {
    expect(source).toContain('return uv * viewPortion;')
  })

  it('gives GLSL numeric literals a decimal point', () => {
    for (const line of source.split('\n')) {
      const constant = /^const float \w+ = ([^;]+);/.exec(line)
      if (constant) expect(constant[1]).toContain('.')
    }
  })
})
