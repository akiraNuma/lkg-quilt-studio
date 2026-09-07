import { computed, onMounted, ref } from 'vue'
import * as api from '../api'

/**
 * The sources and outputs left on the server.
 *
 * A source runs to hundreds of megabytes and a quilt video past 40 MB. Left alone they only
 * grow `out/`, and the screen showed nothing, so there was no way to remove them. Listing them
 * here makes that possible.
 */
export function useLibrary() {
  const sources = ref<api.QuiltSourceInfo[]>([])
  const jobs = ref<api.ConvertJob[]>([])
  const error = ref<string | null>(null)
  const loading = ref(false)

  /** A finished quilt video, which can be played and downloaded */
  const outputs = computed(() =>
    jobs.value.filter(job => job.resultUrl !== null)
  )
  /** A job with no output after failing or being cancelled; deleting is all that is left */
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

  /** Return whether the deletion happened. **The server can refuse** (409 for a source being
   * converted).
   *
   * Callers clean up only on true. Discarding the picture after a refusal would lose the tuned
   * position while the source itself remains.
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
