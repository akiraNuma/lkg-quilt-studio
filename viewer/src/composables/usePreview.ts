import {
  computed,
  onMounted,
  onUnmounted,
  ref,
  watch,
  type Ref,
} from 'vue'
import * as api from '../api'
import {
  matchPreset,
  type DisplayQuilt,
  type QuiltLayout,
} from '../quilt'

export type PreviewFrame = {
  blob: Blob
  /** The source filename. **Not a sentence**, which would not follow a language change */
  name: string
  frameIndex: number
  layout: QuiltLayout
}

/** How long after releasing a slider to redraw. Nothing is drawn while it is held */
const DEBOUNCE_MS = 400

/**
 * The source, the settings that rebuild the picture, and automatic single-frame preview.
 *
 * A settings change redraws without a button. Forgetting to press one would mean tuning against
 * a stale picture and noticing the mismatch only on hardware. A frame takes two seconds, so it
 * waits while a slider is held and runs once on release.
 */
export function usePreview(displayQuilt: Ref<DisplayQuilt | null>) {
  const options = ref<api.ConverterOptions | null>(null)
  const settings = ref<api.SourceSettings>({
    layout: 'sbs',
    // The available hardware is a Go, so it is the default; connecting Bridge overrides it
    // through `detected`
    display: 'go',
    projection: 'flat',
    fov: 60,
    fit: 'crop',
    swapEyes: false,
  })
  const span = ref(1.2)
  const frameIndex = ref(0)

  const source = ref<api.QuiltSourceInfo | null>(null)
  const uploading = ref(false)
  const rendering = ref(false)
  const error = ref<string | null>(null)
  const frame = ref<PreviewFrame | null>(null)
  /** The convergence actually used by the latest preview (the automatically chosen value) */
  const baseConvergence = ref<number | null>(null)

  const fisheye = computed(
    () => settings.value.projection === 'fisheye'
  )
  const lastFrame = computed(() =>
    Math.max((source.value?.frameCount ?? 1) - 1, 0)
  )

  /** The conversion preset matching the model Bridge reported. */
  const detected = computed(() => {
    const quilt = displayQuilt.value
    const presets = options.value?.presets
    if (!quilt || presets === undefined) return null
    return matchPreset(quilt, presets)
  })

  /** The selected model's quilt layout, passed explicitly since an image carries no name */
  const layout = computed<QuiltLayout | null>(
    () => options.value?.presets[settings.value.display] ?? null
  )

  /** Nothing can be drawn until a model is chosen; a mismatched quilt shows only on hardware */
  const ready = computed(
    () => source.value !== null && layout.value !== null
  )

  /** A change here requires rebuilding the picture (convergence and view apply at playback).
   *
   * **The source id is mixed in too.** Without it, choosing a different video under identical
   * settings would not change the key, leaving the previous source's picture as "current"
   */
  const renderKey = computed(() =>
    JSON.stringify([
      source.value?.id ?? null,
      settings.value,
      span.value,
      frameIndex.value,
    ])
  )
  const renderedKey = ref<string | null>(null)
  /** The settings that failed, remembered so the same ones are not resubmitted forever */
  const failedKey = ref<string | null>(null)

  const failed = computed(
    () =>
      failedKey.value !== null && failedKey.value === renderKey.value
  )

  /** Whether the picture on screen disagrees with the settings; if it agrees, nothing is sent */
  const needsRender = computed(
    () =>
      ready.value &&
      renderKey.value !== renderedKey.value &&
      renderKey.value !== failedKey.value
  )

  let timer: ReturnType<typeof setTimeout> | null = null

  function schedule(): void {
    if (timer !== null) clearTimeout(timer)
    timer = setTimeout(() => {
      timer = null
      void run()
    }, DEBOUNCE_MS)
  }

  /** Draw a single frame. A settings change while drawing schedules another after the same wait. */
  async function run(): Promise<void> {
    if (rendering.value || !needsRender.value) return
    const loaded = source.value
    const tile = layout.value
    if (loaded === null || tile === null) return
    const key = renderKey.value
    rendering.value = true
    error.value = null
    try {
      const result = await api.renderPreview(
        loaded.id,
        { ...settings.value, span: span.value, convergence: 'auto' },
        frameIndex.value
      )
      // Discard the result if the source changed while it was in flight. Presenting the previous
      // video's picture as the new settings' output hides the mix-up until it reaches hardware
      if (source.value !== loaded) return
      baseConvergence.value = result.convergence
      renderedKey.value = key
      failedKey.value = null
      frame.value = {
        blob: result.blob,
        name: loaded.name,
        frameIndex: frameIndex.value,
        layout: tile,
      }
    } catch (failure) {
      error.value = api.describe(failure)
      failedKey.value = key
    } finally {
      rendering.value = false
      if (needsRender.value) schedule()
    }
  }

  /** Resubmit the failed settings. While a run is in flight, it is picked up as that run ends. */
  function retry(): void {
    failedKey.value = null
    schedule()
  }

  /** Drop the source, so a deleted one is not held on to */
  function clear(): void {
    source.value = null
    frame.value = null
    renderedKey.value = null
    failedKey.value = null
    baseConvergence.value = null
    frameIndex.value = 0
    error.value = null
  }

  /** Switch to an imported source without re-uploading the same video (hundreds of megabytes) */
  function adopt(info: api.QuiltSourceInfo): void {
    clear()
    source.value = info
    // The arrangement and projection are easy to get wrong, so a guess becomes the initial value
    if (info.suggestedLayout !== null)
      settings.value.layout = info.suggestedLayout
    if (info.suggestedProjection !== null)
      settings.value.projection = info.suggestedProjection
  }

  /** Upload a video. Not sent again for every parameter change during preview. */
  async function selectFile(file: File | null): Promise<void> {
    clear()
    if (file === null) return
    uploading.value = true
    try {
      adopt(await api.uploadSource(file))
    } catch (failure) {
      error.value = api.describe(failure)
    } finally {
      uploading.value = false
    }
  }

  /** The shape handed to a conversion. The caller decides convergence (baking passes an
   * absolute value)
   */
  function renderSettings(convergence: string): api.RenderSettings {
    return { ...settings.value, span: span.value, convergence }
  }

  watch(
    detected,
    name => {
      if (name !== null) settings.value.display = name
    },
    { immediate: true }
  )
  // Restart the wait on every change (watching needsRender instead would not restart it while a
  // drag keeps it true, and drawing would begin mid-drag)
  watch([renderKey, ready], () => {
    if (needsRender.value) schedule()
  })

  onMounted(async () => {
    try {
      const loaded = await api.readOptions()
      options.value = loaded
      settings.value.fov = loaded.fovDefault
    } catch (failure) {
      error.value = api.describe(failure)
    }
  })

  onUnmounted(() => {
    if (timer !== null) clearTimeout(timer)
  })

  return {
    options,
    settings,
    span,
    frameIndex,
    source,
    uploading,
    rendering,
    error,
    failed,
    frame,
    baseConvergence,
    fisheye,
    lastFrame,
    detected,
    ready,
    selectFile,
    adopt,
    clear,
    retry,
    renderSettings,
  }
}
