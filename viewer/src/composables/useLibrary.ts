import { computed, onMounted, ref } from 'vue'
import * as api from '../api'

/**
 * サーバーに残っている素材と成果物の一覧。
 *
 * 素材は数百 MB、quilt 動画は 1 本 40 MB を超える。放っておくと `out/` が膨らむだけで、
 * 画面からは見えないので消しようがなかった。ここで一覧にして消せるようにする。
 */
export function useLibrary() {
  const sources = ref<api.QuiltSourceInfo[]>([])
  const jobs = ref<api.ConvertJob[]>([])
  const error = ref<string | null>(null)
  const loading = ref(false)

  /** 書き出せた quilt 動画。再生とダウンロードができる */
  const outputs = computed(() =>
    jobs.value.filter(job => job.resultUrl !== null)
  )
  /** 失敗・中止で成果物が無いジョブ。消す以外にすることは無い */
  const leftovers = computed(() =>
    jobs.value.filter(
      job =>
        job.resultUrl === null &&
        job.status !== 'queued' &&
        job.status !== 'running'
    )
  )

  async function refresh(): Promise<void> {
    loading.value = true
    try {
      const [foundSources, foundJobs] = await Promise.all([
        api.listSources(),
        api.listJobs(),
      ])
      sources.value = foundSources
      jobs.value = foundJobs
      error.value = null
    } catch (failure) {
      error.value = api.describe(failure)
    } finally {
      loading.value = false
    }
  }

  async function removeSource(id: string): Promise<boolean> {
    return await remove(() => api.deleteSource(id))
  }

  async function removeJob(id: string): Promise<boolean> {
    return await remove(() => api.deleteJob(id))
  }

  /** 消せたかを返す。**サーバーは断ることがある**（変換中の素材は 409）。
   *
   * 呼び出し側は真のときだけ後始末する。断られたのに絵を捨てると、
   * 素材は残っているのに調整していた位置だけ失う。
   */
  async function remove(call: () => Promise<void>): Promise<boolean> {
    let removed = false
    try {
      await call()
      error.value = null
      removed = true
    } catch (failure) {
      error.value = api.describe(failure)
    }
    await refresh()
    return removed
  }

  onMounted(() => void refresh())

  return {
    sources,
    outputs,
    leftovers,
    error,
    loading,
    refresh,
    removeSource,
    removeJob,
  }
}
