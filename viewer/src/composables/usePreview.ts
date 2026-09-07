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
  /** 素材のファイル名。**文にはしない**（言語を切り替えたら追従しなくなる） */
  name: string
  frameIndex: number
  layout: QuiltLayout
}

/** スライダーを離してから描き直すまでの待ち。掴んでいる間は描かない */
const DEBOUNCE_MS = 400

/**
 * 素材と「絵を作り直す側」の設定、そして 1 枚プレビューの自動描画。
 *
 * 設定を変えたら押さずに描き直す。押し忘れると古い絵を見ながら詰めることになり、
 * 実機で初めてずれに気付く。1 枚 2 秒掛かるので、掴んでいる間は待って離したら 1 回だけ走る。
 */
export function usePreview(displayQuilt: Ref<DisplayQuilt | null>) {
  const options = ref<api.ConverterOptions | null>(null)
  const settings = ref<api.SourceSettings>({
    layout: 'sbs',
    // 手元の実機が Go なので既定にする。Bridge に繋げば `detected` が上書きする
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
  /** 直近のプレビューで実際に使われた収束面（自動判定の値） */
  const baseConvergence = ref<number | null>(null)

  const fisheye = computed(
    () => settings.value.projection === 'fisheye'
  )
  const lastFrame = computed(() =>
    Math.max((source.value?.frameCount ?? 1) - 1, 0)
  )

  /** Bridge が返した機種に一致する変換プリセット。 */
  const detected = computed(() => {
    const quilt = displayQuilt.value
    const presets = options.value?.presets
    if (!quilt || presets === undefined) return null
    return matchPreset(quilt, presets)
  })

  /** いま選んでいる機種の quilt レイアウト。画像には名前が無いので明示で渡す */
  const layout = computed<QuiltLayout | null>(
    () => options.value?.presets[settings.value.display] ?? null
  )

  /** 機種が決まるまでは描けない。合っていない quilt は実機に出すまで気付けない */
  const ready = computed(
    () => source.value !== null && layout.value !== null
  )

  /** これが変わったら絵は作り直さないと合わない（収束面と視点は再生側で効く）。
   *
   * **素材の id も混ぜる。** 同じ設定で別の動画を選んだときに変わらないと、
   * 前の素材の絵を「最新」として置いたまま止まる
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
  /** 失敗した設定。同じ設定で無限に投げ直さないために覚える */
  const failedKey = ref<string | null>(null)

  const failed = computed(
    () =>
      failedKey.value !== null && failedKey.value === renderKey.value
  )

  /** いま出ている絵が設定と合っていないか。合っていれば投げない */
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

  /** 1 枚だけ描く。描いている間に設定が変われば、同じ待ち時間を置いてもう一度。 */
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
      // 返ってくるまでに素材が入れ替わっていたら捨てる。前の動画の絵を新しい設定の
      // ものとして置くと、実機に出すまで取り違えに気付けない
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

  /** 失敗した設定をもう一度投げる。走っている最中なら終わり際に拾われる。 */
  function retry(): void {
    failedKey.value = null
    schedule()
  }

  /** 素材を外す。消された素材を掴んだままにしない */
  function clear(): void {
    source.value = null
    frame.value = null
    renderedKey.value = null
    failedKey.value = null
    baseConvergence.value = null
    frameIndex.value = 0
    error.value = null
  }

  /** 取り込み済みの素材へ切り替える。同じ動画を上げ直さない（数百 MB ある） */
  function adopt(info: api.QuiltSourceInfo): void {
    clear()
    source.value = info
    // 左右の入り方と写り方は取り違えやすいので、当てられたら初期値にする
    if (info.suggestedLayout !== null)
      settings.value.layout = info.suggestedLayout
    if (info.suggestedProjection !== null)
      settings.value.projection = info.suggestedProjection
  }

  /** 動画を上げ直す。プレビューでパラメータを変えるたびには送らない。 */
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

  /** 変換に渡す形。収束面は呼び出し側が決める（焼くときは絶対値で渡す） */
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
  // 変わるたびに待ち時間を置き直す（needsRender を watch すると true のままの
  // ドラッグ中に置き直されず、掴んでいる最中に描き始める）
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
