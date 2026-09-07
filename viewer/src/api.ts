// Calls into the conversion API (converter/src/lkg_quilt_converter/server.py).
// Failures throw; turning them into on-screen text is left to describe().

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
  /** When the conversion started, in seconds, or null when it is not running */
  startedAt: number | null
  createdAt: number
  /** Output size in bytes, or 0 when there is none yet */
  sizeBytes: number
}

/** The conversion settings chosen on screen. */
export type SourceSettings = {
  layout: string
  display: string
  /** How the input was captured. fisheye flattens VR180 before estimating disparity */
  projection: string
  /** Horizontal field of view in degrees when flattening fisheye; unused when projection is flat */
  fov: number
  fit: string
  swapEyes: boolean
}

/** The settings that determine one picture, passed in this shape by preview and conversion. */
export type RenderSettings = SourceSettings & {
  span: number
  /** The convergence disparity. With `auto`, the converter decides */
  convergence: string
}

/** Options needed only when baking a whole video. */
export type OutputSettings = {
  start: number
  /** How many frames to convert. null means from the start position to the end */
  frames: number | null
  copyAudio: boolean
}

export type QuiltSourceInfo = {
  id: string
  name: string
  /** Imported video size in bytes. Hundreds of megabytes remain, so the list shows it */
  sizeBytes: number
  createdAt: number
  width: number
  height: number
  fps: number
  frameCount: number
  hasAudio: boolean
  /** The guessed eye arrangement. It can be wrong, so it is only an initial value */
  suggestedLayout: string | null
  /** The guessed projection, likewise only an initial value */
  suggestedProjection: string | null
}

/** The result of converting a single frame. `convergence` is the disparity actually used */
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

/** Imported videos. Changing parameters on the same source does not re-upload it. */
export async function listSources(): Promise<QuiltSourceInfo[]> {
  return (await request('/api/sources')) as QuiltSourceInfo[]
}

/** Delete an imported video. The server answers 409 for a source being converted. */
export async function deleteSource(id: string): Promise<void> {
  await noContent(`/api/sources/${id}`, 'DELETE')
}

/** Upload a video once. Preview and conversion both refer to this id. */
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

/** Convert a single frame and fetch the quilt image, through the same path as a full run. */
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

/** Delete a job and its output. The server answers 409 for a running job. */
export async function deleteJob(id: string): Promise<void> {
  await noContent(`/api/jobs/${id}`, 'DELETE')
}

export async function readJob(id: string): Promise<ConvertJob> {
  return (await request(`/api/jobs/${id}`)) as ConvertJob
}

/** Stop a running conversion. No partial video is left behind. */
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

/** Endpoints answering 204; no JSON is read */
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

/** FastAPI returns failures as {detail: ...}, which is not always a string */
async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    const detail = body.detail
    if (typeof detail === 'string') return detail
    if (detail !== undefined) return JSON.stringify(detail)
  } catch {
    // A non-JSON response (a proxy 502, say) is shown by its status as is
  }
  return t('api.status', { status: response.status })
}
