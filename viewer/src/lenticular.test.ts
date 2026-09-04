import { describe, expect, it } from 'vitest'
import {
  fragmentShader,
  lenticularParams,
  viewPortion,
  type Calibration,
} from './lenticular'

// Looking Glass Portrait 相当の値。数値そのものは機種ごとに Bridge から届く
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
  it('画面横幅あたりのレンズ本数へ直す', () => {
    expect(lenticularParams(CALIBRATION).pitch).toBeCloseTo(
      246.8916717,
      6
    )
  })

  it('傾きとサブピクセル間隔を画面比から求める', () => {
    const params = lenticularParams(CALIBRATION)
    expect(params.tilt).toBeCloseTo(-0.1854427, 6)
    expect(params.subp).toBeCloseTo(0.000217014, 9)
    expect(params.center).toBe(0.18)
    expect(params.invertView).toBe(true)
  })

  it('flipImageX が立つと傾きとサブピクセルの符号が反転する', () => {
    const flipped = lenticularParams({
      ...CALIBRATION,
      flipImageX: 1,
    })
    expect(flipped.tilt).toBeCloseTo(0.1854427, 6)
    expect(flipped.subp).toBeLessThan(0)
    // pitch は符号を持たない
    expect(flipped.pitch).toBeCloseTo(246.8916717, 6)
  })

  it('invView が 0 なら視点の並びを反転しない', () => {
    expect(
      lenticularParams({ ...CALIBRATION, invView: 0 }).invertView
    ).toBe(false)
  })

  it.each([{ screenW: 0 }, { screenH: 0 }, { DPI: 0 }, { slope: 0 }])(
    '壊れた値は例外にする (%o)',
    overrides => {
      expect(() =>
        lenticularParams({ ...CALIBRATION, ...overrides })
      ).toThrow()
    }
  )
})

describe('viewPortion', () => {
  it('割り切れる解像度では余白が無い', () => {
    expect(
      viewPortion({ columns: 8, rows: 6, aspect: 0.75 }, 3360, 3360)
    ).toEqual({ u: 1, v: 1 })
  })

  it('割り切れない解像度では端の 1 px を除外する', () => {
    // 4096 / 5 = 819.2 → タイル幅 819、格子は 4095 px しか埋めない
    const portion = viewPortion(LAYOUT, 4096, 4096)
    expect(portion.u).toBeCloseTo(4095 / 4096, 10)
    expect(portion.v).toBeCloseTo(4095 / 4096, 10)
  })

  it('タイル数より小さい解像度は例外にする', () => {
    expect(() => viewPortion(LAYOUT, 4, 4096)).toThrow()
  })
})

describe('fragmentShader', () => {
  const source = fragmentShader(lenticularParams(CALIBRATION), LAYOUT)

  it('視点数とタイル数を定数として焼き込む', () => {
    expect(source).toContain('const float tileCount = 45.00000000')
    expect(source).toContain('const float rows = 9.000000000')
    // 桁落ち対策で列数をわずかに減らす
    expect(source).toContain('const float columns = 4.999990000')
  })

  it('invView に応じて反転の式を切り替える', () => {
    expect(source).toContain('views = 1.0 - fract(views);')
    const notInverted = fragmentShader(
      lenticularParams({ ...CALIBRATION, invView: 0 }),
      LAYOUT
    )
    expect(notInverted).toContain('views = fract(views);')
  })

  it('タイル座標に余白の除外を掛ける', () => {
    expect(source).toContain('return uv * viewPortion;')
  })

  it('GLSL の数値リテラルに小数点が付く', () => {
    for (const line of source.split('\n')) {
      const constant = /^const float \w+ = ([^;]+);/.exec(line)
      if (constant) expect(constant[1]).toContain('.')
    }
  })
})
