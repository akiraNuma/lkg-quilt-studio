// 変換 API（converter/src/lkg_quilt_converter/server.py）の呼び出し。
// 失敗は例外で投げ、画面に出す文言への変換は describe() に寄せる。

import { t } from './i18n'
import type { DisplayPreset } from './quilt'

export type JobStatus =
  'queued' | 'running' | 'done' | 'failed' | 'cancelled'

export type ConvertJob = {
  id: string
  sourceId: string
  sourceName: string
  status: JobStatus
  doneFrames: number
  totalFrames: number
  progress: number
  outputName: string | null
  resultUrl: string | null
  error: string | null
  /** 変換を始めた時刻（秒）。走っていなければ null */
  startedAt: number | null
  createdAt: number
  /** 成果物の大きさ（バイト）。まだ無ければ 0 */
  sizeBytes: number
}

/** 変換に渡す設定のうち、画面で選ぶもの。 */
export type SourceSettings = {
  layout: string
  display: string
  /** 入力の写り方。fisheye は VR180 の魚眼を平面へ直してから視差を取る */
  projection: string
  /** 魚眼を平面へ直すときの水平視野角（度）。projection が flat なら使われない */
  fov: number
  fit: string
  swapEyes: boolean
}

/** 1 枚の絵を決める設定。プレビューと変換の両方がこの形で渡す。 */
export type RenderSettings = SourceSettings & {
  span: number
  /** 収束面の視差。`auto` なら変換側が決める */
  convergence: string
}

/** 動画全体を焼くときだけ要る指定。 */
export type OutputSettings = {
  start: number
  /** 変換する枚数。null なら開始位置から最後まで */
  frames: number | null
  copyAudio: boolean
}

export type QuiltSourceInfo = {
  id: string
  name: string
  /** 取り込んだ動画の大きさ（バイト）。数百 MB 残るので一覧に出す */
  sizeBytes: number
  createdAt: number
  width: number
  height: number
  fps: number
  frameCount: number
  hasAudio: boolean
  /** 左右の入り方の推定。当たらないこともあるので初期値としてだけ使う */
  suggestedLayout: string | null
  /** 写り方の推定。同じく初期値としてだけ使う */
  suggestedProjection: string | null
}

/** 1 フレームだけ変換した結果。`convergence` は実際に使われた収束面の視差 */
export type PreviewResult = {
  blob: Blob
  convergence: number
}

export type ConverterOptions = {
  layouts: string[]
  projections: string[]
  fovDefault: number
  displays: string[]
  fits: string[]
  presets: Record<string, DisplayPreset>
}

export async function readOptions(): Promise<ConverterOptions> {
  return (await request('/api/options')) as ConverterOptions
}

/** 取り込み済みの動画。同じ素材でパラメータを変えるときは上げ直さない。 */
export async function listSources(): Promise<QuiltSourceInfo[]> {
  return (await request('/api/sources')) as QuiltSourceInfo[]
}

/** 取り込んだ動画を消す。変換中の素材はサーバーが 409 で断る。 */
export async function deleteSource(id: string): Promise<void> {
  await noContent(`/api/sources/${id}`, 'DELETE')
}

/** 動画を 1 回だけ上げる。プレビューと変換はこの id を指す。 */
export async function uploadSource(
  file: File
): Promise<QuiltSourceInfo> {
  const form = new FormData()
  form.set('file', file)
  return (await request('/api/sources', {
    method: 'POST',
    body: form,
  })) as QuiltSourceInfo
}

/** 1 フレームだけ変換して quilt の画像を取る。変換本体と同じ経路を通る。 */
export async function renderPreview(
  sourceId: string,
  settings: RenderSettings,
  frame: number
): Promise<PreviewResult> {
  const query = new URLSearchParams({
    frame: String(frame),
    layout: settings.layout,
    display: settings.display,
    fit: settings.fit,
    projection: settings.projection,
    fov: String(settings.fov),
    swap_eyes: String(settings.swapEyes),
    span: String(settings.span),
    convergence: settings.convergence,
  })
  const response = await fetch(
    `/api/sources/${sourceId}/preview?${query}`
  )
  if (!response.ok) throw new Error(await readError(response))
  const blob = await response.blob()
  return {
    blob,
    convergence: Number(response.headers.get('x-convergence') ?? '0'),
  }
}

export async function startJob(
  sourceId: string,
  settings: RenderSettings & OutputSettings
): Promise<ConvertJob> {
  return (await request('/api/jobs', {
    method: 'POST',
    body: toFormData(sourceId, settings),
  })) as ConvertJob
}

export async function listJobs(): Promise<ConvertJob[]> {
  return (await request('/api/jobs')) as ConvertJob[]
}

/** ジョブと成果物を消す。走っているジョブはサーバーが 409 で断る。 */
export async function deleteJob(id: string): Promise<void> {
  await noContent(`/api/jobs/${id}`, 'DELETE')
}

export async function readJob(id: string): Promise<ConvertJob> {
  return (await request(`/api/jobs/${id}`)) as ConvertJob
}

/** 走っている変換を止める。書きかけの動画は残らない。 */
export async function cancelJob(id: string): Promise<void> {
  await noContent(`/api/jobs/${id}/cancel`, 'POST')
}

export function describe(failure: unknown): string {
  if (failure instanceof Error) return failure.message
  return t('api.unreachable')
}

function toFormData(
  sourceId: string,
  settings: RenderSettings & OutputSettings
): FormData {
  const form = new FormData()
  form.set('source_id', sourceId)
  form.set('layout', settings.layout)
  form.set('display', settings.display)
  form.set('fit', settings.fit)
  form.set('projection', settings.projection)
  form.set('fov', String(settings.fov))
  form.set('swap_eyes', String(settings.swapEyes))
  form.set('span', String(settings.span))
  form.set('convergence', settings.convergence)
  form.set('start', String(settings.start))
  form.set('copy_audio', String(settings.copyAudio))
  if (settings.frames !== null)
    form.set('frames', String(settings.frames))
  return form
}

/** 204 を返す経路。JSON は読まない */
async function noContent(url: string, method: string): Promise<void> {
  const response = await fetch(url, { method })
  if (!response.ok) throw new Error(await readError(response))
}

async function request(
  url: string,
  init?: RequestInit
): Promise<unknown> {
  const response = await fetch(url, init)
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

/** FastAPI は失敗を {detail: ...} で返す。文字列でないこともある */
async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    const detail = body.detail
    if (typeof detail === 'string') return detail
    if (detail !== undefined) return JSON.stringify(detail)
  } catch {
    // JSON でない応答（プロキシの 502 など）はそのまま status で見せる
  }
  return t('api.status', { status: response.status })
}
