import { computed, onUnmounted, ref } from 'vue'
import * as api from '../api'

const POLL_INTERVAL_MS = 1000

/** 変換ジョブの投入と進捗の追跡。完了・失敗までポーリングする。 */
export function useConvertJob() {
  const job = ref<api.ConvertJob | null>(null)
  const error = ref<string | null>(null)
  let timer: ReturnType<typeof setInterval> | null = null

  const running = computed(
    () =>
      job.value?.status === 'queued' ||
      job.value?.status === 'running'
  )

  function stopPolling(): void {
    if (timer === null) return
    clearInterval(timer)
    timer = null
  }

  async function submit(
    sourceId: string,
    settings: api.RenderSettings & api.OutputSettings
  ): Promise<void> {
    stopPolling()
    error.value = null
    job.value = null
    try {
      job.value = await api.startJob(sourceId, settings)
      timer = setInterval(() => void refresh(), POLL_INTERVAL_MS)
    } catch (failure) {
      error.value = api.describe(failure)
    }
  }

  async function cancel(): Promise<void> {
    const current = job.value
    if (current === null) return
    try {
      await api.cancelJob(current.id)
      await refresh()
    } catch (failure) {
      error.value = api.describe(failure)
    }
  }

  async function refresh(): Promise<void> {
    const current = job.value
    if (current === null) return
    try {
      const latest = await api.readJob(current.id)
      job.value = latest
      if (latest.status !== 'queued' && latest.status !== 'running')
        stopPolling()
    } catch (failure) {
      // 一時的な失敗でポーリングを止めない。続けて拾えることが多い
      error.value = api.describe(failure)
    }
  }

  function reset(): void {
    stopPolling()
    job.value = null
    error.value = null
  }

  onUnmounted(stopPolling)

  return { job, error, running, submit, cancel, refresh, reset }
}
