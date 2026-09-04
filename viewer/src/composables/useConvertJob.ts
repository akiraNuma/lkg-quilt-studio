import { onUnmounted, ref } from 'vue'
import type { DisplayPreset } from '../quilt'

export type JobStatus =
  'queued' | 'running' | 'done' | 'failed' | 'cancelled'

export type ConvertJob = {
  id: string
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
}

export type ConvertSettings = {
  layout: string
  display: string
  /** 入力の写り方。fisheye は VR180 の魚眼を平面へ直してから視差を取る */
  projection: string
  /** 魚眼を平面へ直すときの水平視野角（度）。projection が flat なら使われない */
  fov: number
  fit: string
  swapEyes: boolean
  span: number
  convergence: string
  start: number
  frames: number | null
  copyAudio: boolean
}

export type QuiltSourceInfo = {
  id: string
  name: string
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
  /** 1 枚に掛かった秒数。動画全体の見積もりに使う */
  seconds: number
}

export type ConvertOptionsResponse = {
  layouts: string[]
  projections: string[]
  fovDefault: number
  displays: string[]
  fits: string[]
  presets: Record<string, DisplayPreset>
}

const POLL_INTERVAL_MS = 1000

/** 変換ジョブの投入と進捗の追跡。完了・失敗までポーリングする。 */
export function useConvertJob() {
  const job = ref<ConvertJob | null>(null)
  const uploading = ref(false)
  const previewing = ref(false)
  const error = ref<string | null>(null)
  let timer: ReturnType<typeof setInterval> | null = null

  function stopPolling(): void {
    if (timer === null) return
    clearInterval(timer)
    timer = null
  }

  async function readOptions(): Promise<ConvertOptionsResponse | null> {
    try {
      return (await request('/api/options')) as ConvertOptionsResponse
    } catch (failure) {
      error.value = describe(failure)
      return null
    }
  }

  /** 動画を 1 回だけ上げる。プレビューと変換はこの id を指す。 */
  async function upload(file: File): Promise<QuiltSourceInfo | null> {
    uploading.value = true
    error.value = null
    try {
      const form = new FormData()
      form.set('file', file)
      return (await request('/api/sources', {
        method: 'POST',
        body: form,
      })) as QuiltSourceInfo
    } catch (failure) {
      error.value = describe(failure)
      return null
    } finally {
      uploading.value = false
    }
  }

  /** 1 フレームだけ変換して quilt の画像を取る。変換本体と同じ経路を通る。 */
  async function preview(
    sourceId: string,
    settings: ConvertSettings,
    frame: number
  ): Promise<PreviewResult | null> {
    previewing.value = true
    error.value = null
    try {
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
      const began = performance.now()
      const response = await fetch(
        `/api/sources/${sourceId}/preview?${query}`
      )
      if (!response.ok) throw new Error(await readError(response))
      const blob = await response.blob()
      return {
        blob,
        convergence: Number(
          response.headers.get('x-convergence') ?? '0'
        ),
        seconds: (performance.now() - began) / 1000,
      }
    } catch (failure) {
      error.value = describe(failure)
      return null
    } finally {
      previewing.value = false
    }
  }

  async function submit(
    sourceId: string,
    settings: ConvertSettings
  ): Promise<void> {
    stopPolling()
    error.value = null
    job.value = null
    try {
      job.value = (await request('/api/jobs', {
        method: 'POST',
        body: toFormData(sourceId, settings),
      })) as ConvertJob
      startPolling()
    } catch (failure) {
      error.value = describe(failure)
    }
  }

  function startPolling(): void {
    timer = setInterval(() => {
      void refresh()
    }, POLL_INTERVAL_MS)
  }

  /** 走っている変換を止める。書きかけの動画は残らない。 */
  async function cancel(): Promise<void> {
    const current = job.value
    if (current === null) return
    try {
      // 204 が返るので JSON にはしない
      const response = await fetch(`/api/jobs/${current.id}/cancel`, {
        method: 'POST',
      })
      if (!response.ok) throw new Error(await readError(response))
      await refresh()
    } catch (failure) {
      error.value = describe(failure)
    }
  }

  async function refresh(): Promise<void> {
    const current = job.value
    if (current === null) return
    try {
      const latest = (await request(
        `/api/jobs/${current.id}`
      )) as ConvertJob
      job.value = latest
      if (latest.status !== 'queued' && latest.status !== 'running')
        stopPolling()
    } catch (failure) {
      // 一時的な失敗でポーリングを止めない。続けて拾えることが多い
      error.value = describe(failure)
    }
  }

  function reset(): void {
    stopPolling()
    job.value = null
    error.value = null
  }

  onUnmounted(stopPolling)

  return {
    job,
    uploading,
    previewing,
    error,
    upload,
    preview,
    submit,
    cancel,
    refresh,
    reset,
    readOptions,
  }
}

function toFormData(
  sourceId: string,
  settings: ConvertSettings
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
  return `変換 API が ${response.status} を返した`
}

function describe(failure: unknown): string {
  if (failure instanceof Error) return failure.message
  return '変換 API に届かなかった。api サービスが起動しているか確認する'
}
