import { beforeEach, describe, expect, it } from 'vitest'
import {
  clampRound,
  clock,
  humanize,
  trim,
  parseCount,
  parseNumber,
  size,
  stamp,
} from './format'
import { locale, setLocale } from './i18n'

// 単位は言語で変わる。環境の言語に依存させない
beforeEach(() => setLocale('ja'))

describe('parseCount', () => {
  it('全角数字と桁区切りを読む', () => {
    expect(parseCount('１０００')).toBe(1000)
    expect(parseCount('1,000')).toBe(1000)
    expect(parseCount('１，０００')).toBe(1000)
    expect(parseCount(' 42 ')).toBe(42)
  })

  it('数として読めない入力は null', () => {
    expect(parseCount('')).toBeNull()
    expect(parseCount('12a')).toBeNull()
    expect(parseCount('-1')).toBeNull()
    expect(parseCount('1.5')).toBeNull()
  })
})

describe('parseNumber', () => {
  it('小数と符号を読む', () => {
    expect(parseNumber('1.25')).toBe(1.25)
    expect(parseNumber('-3')).toBe(-3)
    expect(parseNumber('+0.5')).toBe(0.5)
    expect(parseNumber('.5')).toBe(0.5)
  })

  it('全角の数字・記号も読む（IME が有効なら混ざる）', () => {
    expect(parseNumber('－２．５')).toBe(-2.5)
    expect(parseNumber('ー１')).toBe(-1)
    expect(parseNumber('１２')).toBe(12)
  })

  it('数として読めない入力は null', () => {
    expect(parseNumber('')).toBeNull()
    expect(parseNumber('-')).toBeNull()
    expect(parseNumber('1.2.3')).toBeNull()
    expect(parseNumber('2px')).toBeNull()
  })
})

describe('clampRound', () => {
  it('範囲の外は端へ丸める', () => {
    expect(clampRound(9, 0.4, 3, 2)).toBe(3)
    expect(clampRound(-5, 0.4, 3, 2)).toBe(0.4)
  })

  it('桁で丸める', () => {
    expect(clampRound(1.2345, 0.4, 3, 2)).toBe(1.23)
    expect(clampRound(1.6, -24, 24, 0)).toBe(2)
  })
})

describe('trim', () => {
  it('末尾の 0 を落とす', () => {
    expect(trim(1.5, 2)).toBe('1.5')
    expect(trim(3, 2)).toBe('3')
    expect(trim(-2.25, 2)).toBe('-2.25')
  })
})

describe('humanize', () => {
  it('長さに応じて単位を上げる', () => {
    expect(humanize(45)).toBe('45 秒')
    expect(humanize(300)).toBe('5 分')
    expect(humanize(9000)).toBe('2.5 時間')
  })

  it('言語を切り替えると単位も変わる', () => {
    setLocale('en')
    expect(locale.value).toBe('en')
    expect(humanize(45)).toBe('45 s')
    expect(humanize(300)).toBe('5 min')
  })
})

describe('clock', () => {
  it('分と秒に分ける', () => {
    expect(clock(0)).toBe('0:00')
    expect(clock(75.9)).toBe('1:15')
    expect(clock(-3)).toBe('0:00')
  })
})

describe('size', () => {
  it('桁に応じて単位を上げる', () => {
    expect(size(0)).toBe('0 kB')
    expect(size(524_288)).toBe('524 kB')
    expect(size(40_631_665)).toBe('40.6 MB')
    expect(size(2_500_000_000)).toBe('2.50 GB')
  })
})

describe('stamp', () => {
  it('時刻が無ければ空にする', () => {
    expect(stamp(0)).toBe('')
  })

  it('月日と時刻を出す', () => {
    const at = new Date(2026, 8, 7, 9, 5).getTime() / 1000
    expect(stamp(at)).toBe('9/7 9:05')
  })
})
