import { t } from './i18n'

/** 全角の数字・記号を半角へ直し、桁区切りと空白を落とす。
 *
 * `<input type="number">` は全角で入れた値（IME が有効なら簡単に起きる）や `1,000` を
 * **黙って捨てて value を空にする**ので、テキストで受けてここで直す。
 */
function normalize(text: string): string {
  return text
    .replace(/[０-９＋－．]/g, character =>
      String.fromCharCode(character.charCodeAt(0) - 0xfee0)
    )
    .replace(/[−ー]/g, '-')
    .replace(/[,，、\s]/g, '')
}

/** 数の入った文字列を整数として読む。読めなければ null。
 *
 * 捨てられるとフレーム数が「空＝最後まで」に化けるので、自分で検証する。
 */
export function parseCount(text: string): number | null {
  const normalized = normalize(text)
  if (normalized === '' || !/^\d+$/.test(normalized)) return null
  return Number.parseInt(normalized, 10)
}

/** 数の入った文字列を小数として読む。負の値も読む（収束面は手前側が負）。 */
export function parseNumber(text: string): number | null {
  const normalized = normalize(text)
  if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(normalized)) return null
  const value = Number.parseFloat(normalized)
  return Number.isFinite(value) ? value : null
}

/** スライダーの範囲へ収めて桁を丸める。欄に打ち込んだ値をスライダーと揃えるのに使う */
export function clampRound(
  value: number,
  min: number,
  max: number,
  decimals: number
): number {
  const clamped = Math.min(Math.max(value, min), max)
  return Number(clamped.toFixed(decimals))
}

/** 数を表示用の文字列にする。末尾の 0 は落とす（1.50 ではなく 1.5） */
export function trim(value: number, decimals: number): string {
  return String(Number(value.toFixed(decimals)))
}

/** 所要時間を読める粒度へ丸める。秒まで見せても判断が変わらない長さになる */
export function humanize(seconds: number): string {
  if (seconds < 120)
    return t('unit.seconds', { value: Math.round(seconds) })
  if (seconds < 7200)
    return t('unit.minutes', { value: Math.round(seconds / 60) })
  return t('unit.hours', { value: (seconds / 3600).toFixed(1) })
}

/** 再生位置の表示（m:ss） */
export function clock(seconds: number): string {
  const whole = Math.max(Math.floor(seconds), 0)
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

/** ファイルの大きさ。素材は数百 MB 残るので、消す判断に使えるところまで出す */
export function size(bytes: number): string {
  if (bytes < 1e6) return `${Math.round(bytes / 1e3)} kB`
  if (bytes < 1e9) return `${(bytes / 1e6).toFixed(1)} MB`
  return `${(bytes / 1e9).toFixed(2)} GB`
}

/** 取り込んだ・書き出した時刻（M/D H:MM）。言語で並びを変えない */
export function stamp(seconds: number): string {
  if (!seconds) return ''
  const date = new Date(seconds * 1000)
  const time = `${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`
  return `${date.getMonth() + 1}/${date.getDate()} ${time}`
}
