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

// The units change with the language; do not depend on the environment locale
beforeEach(() => setLocale('ja'))

describe('parseCount', () => {
  it('reads full-width digits and thousands separators', () => {
    expect(parseCount('１０００')).toBe(1000)
    expect(parseCount('1,000')).toBe(1000)
    expect(parseCount('１，０００')).toBe(1000)
    expect(parseCount(' 42 ')).toBe(42)
  })

  it('returns null for input that is not a number', () => {
    expect(parseCount('')).toBeNull()
    expect(parseCount('12a')).toBeNull()
    expect(parseCount('-1')).toBeNull()
    expect(parseCount('1.5')).toBeNull()
  })
})

describe('parseNumber', () => {
  it('reads decimals and signs', () => {
    expect(parseNumber('1.25')).toBe(1.25)
    expect(parseNumber('-3')).toBe(-3)
    expect(parseNumber('+0.5')).toBe(0.5)
    expect(parseNumber('.5')).toBe(0.5)
  })

  it('reads full-width digits and symbols too, which an active IME mixes in', () => {
    expect(parseNumber('－２．５')).toBe(-2.5)
    expect(parseNumber('ー１')).toBe(-1)
    expect(parseNumber('１２')).toBe(12)
  })

  it('returns null for a float that is not a number', () => {
    expect(parseNumber('')).toBeNull()
    expect(parseNumber('-')).toBeNull()
    expect(parseNumber('1.2.3')).toBeNull()
    expect(parseNumber('2px')).toBeNull()
  })
})

describe('clampRound', () => {
  it('clamps out-of-range values to the limits', () => {
    expect(clampRound(9, 0.4, 3, 2)).toBe(3)
    expect(clampRound(-5, 0.4, 3, 2)).toBe(0.4)
  })

  it('rounds to the given decimals', () => {
    expect(clampRound(1.2345, 0.4, 3, 2)).toBe(1.23)
    expect(clampRound(1.6, -24, 24, 0)).toBe(2)
  })
})

describe('trim', () => {
  it('drops trailing zeros', () => {
    expect(trim(1.5, 2)).toBe('1.5')
    expect(trim(3, 2)).toBe('3')
    expect(trim(-2.25, 2)).toBe('-2.25')
  })
})

describe('humanize', () => {
  it('raises the unit with the duration', () => {
    expect(humanize(45)).toBe('45 秒')
    expect(humanize(300)).toBe('5 分')
    expect(humanize(9000)).toBe('2.5 時間')
  })

  it('changes the unit with the language', () => {
    setLocale('en')
    expect(locale.value).toBe('en')
    expect(humanize(45)).toBe('45 s')
    expect(humanize(300)).toBe('5 min')
  })
})

describe('clock', () => {
  it('splits into minutes and seconds', () => {
    expect(clock(0)).toBe('0:00')
    expect(clock(75.9)).toBe('1:15')
    expect(clock(-3)).toBe('0:00')
  })
})

describe('size', () => {
  it('raises the unit with the magnitude', () => {
    expect(size(0)).toBe('0 kB')
    expect(size(524_288)).toBe('524 kB')
    expect(size(40_631_665)).toBe('40.6 MB')
    expect(size(2_500_000_000)).toBe('2.50 GB')
  })
})

describe('stamp', () => {
  it('returns empty without a timestamp', () => {
    expect(stamp(0)).toBe('')
  })

  it('shows the date and time', () => {
    const at = new Date(2026, 8, 7, 9, 5).getTime() / 1000
    expect(stamp(at)).toBe('9/7 9:05')
  })
})
