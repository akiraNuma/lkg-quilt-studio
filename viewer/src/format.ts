import { t } from './i18n'

/** Normalise full-width digits and symbols to ASCII, dropping separators and whitespace.
 *
 * `<input type="number">` **silently discards** full-width input (easy to produce with an IME)
 * and `1,000`, leaving value empty, so input is taken as text and fixed here.
 */
function normalize(text: string): string {
  return text
    .replace(/[０-９＋－．]/g, character =>
      String.fromCharCode(character.charCodeAt(0) - 0xfee0)
    )
    .replace(/[−ー]/g, '-')
    .replace(/[,，、\s]/g, '')
}

/** Read a numeric string as an integer, or null when unreadable.
 *
 * A discarded value would turn a frame count into "empty means to the end", so validate here.
 */
export function parseCount(text: string): number | null {
  const normalized = normalize(text)
  if (normalized === '' || !/^\d+$/.test(normalized)) return null
  return Number.parseInt(normalized, 10)
}

/** Read a numeric string as a float, negatives included (convergence is negative in front). */
export function parseNumber(text: string): number | null {
  const normalized = normalize(text)
  if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(normalized)) return null
  const value = Number.parseFloat(normalized)
  return Number.isFinite(value) ? value : null
}

/** Clamp to the slider range and round, so a typed value agrees with the slider */
export function clampRound(
  value: number,
  min: number,
  max: number,
  decimals: number
): number {
  const clamped = Math.min(Math.max(value, min), max)
  return Number(clamped.toFixed(decimals))
}

/** Format a number for display, dropping trailing zeros (1.5 rather than 1.50) */
export function trim(value: number, decimals: number): string {
  return String(Number(value.toFixed(decimals)))
}

/** Round a duration to a legible granularity; showing seconds would not change any decision */
export function humanize(seconds: number): string {
  if (seconds < 120)
    return t('unit.seconds', { value: Math.round(seconds) })
  if (seconds < 7200)
    return t('unit.minutes', { value: Math.round(seconds / 60) })
  return t('unit.hours', { value: (seconds / 3600).toFixed(1) })
}

/** Playback position (m:ss) */
export function clock(seconds: number): string {
  const whole = Math.max(Math.floor(seconds), 0)
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

/** File size. Sources leave hundreds of megabytes behind, so show enough to decide on deleting */
export function size(bytes: number): string {
  if (bytes < 1e6) return `${Math.round(bytes / 1e3)} kB`
  if (bytes < 1e9) return `${(bytes / 1e6).toFixed(1)} MB`
  return `${(bytes / 1e9).toFixed(2)} GB`
}

/** When it was imported or exported (M/D H:MM). The order does not change with language */
export function stamp(seconds: number): string {
  if (!seconds) return ''
  const date = new Date(seconds * 1000)
  const time = `${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`
  return `${date.getMonth() + 1}/${date.getDate()} ${time}`
}
