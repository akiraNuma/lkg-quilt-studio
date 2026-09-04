<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  useConvertJob,
  type ConvertSettings,
  type QuiltSourceInfo,
} from '../composables/useConvertJob'
import {
  matchPreset,
  type DisplayPreset,
  type DisplayQuilt,
  type QuiltLayout,
} from '../quilt'
import type { ViewMode } from '../lenticular'

// Bridge に繋がっていれば、その機種の quilt を渡してもらう。機種の取り違えを防ぐ
const props = defineProps<{
  displayQuilt?: DisplayQuilt | null
  /** 左の絵の表示モード。single のときだけ視点のスライダーを出す */
  mode: ViewMode
  /** 表示中の quilt の視点数 - 1。プリセットではなく実際に載っている絵から取る */
  maxView: number
}>()
const emit = defineEmits<{
  loaded: [url: string]
  preview: [blob: Blob, name: string, layout: QuiltLayout]
}>()

// 左の絵と共有する値。span はシェーダーが視点位置を出すのに要る
const span = defineModel<number>('span', { required: true })
const shift = defineModel<number>('shift', { required: true })
const singleView = defineModel<number>('singleView', {
  required: true,
})

const {
  job,
  uploading,
  previewing,
  error,
  upload,
  preview,
  submit,
  cancel,
  reset,
  readOptions,
} = useConvertJob()

const layouts = ref<string[]>([])
const projections = ref<string[]>([])
const displays = ref<string[]>([])
const fits = ref<string[]>([])
const presets = ref<Record<string, DisplayPreset>>({})
const source = ref<QuiltSourceInfo | null>(null)
const previewFrame = ref(0)
const startText = ref('0')
const framesText = ref('')
/** 直近のプレビューで実際に使われた収束面（自動判定の値）。 */
const baseConvergence = ref<number | null>(null)
const previewSeconds = ref<number | null>(null)
/** 描いたときの設定。今の設定と違えばプレビューは古い。 */
const renderedKey = ref<string | null>(null)

const settings = ref({
  layout: 'sbs',
  display: '',
  projection: 'flat',
  fov: 60,
  fit: 'crop',
  swapEyes: false,
  copyAudio: true,
})

/** 魚眼のときだけ視野角が効く。平面の素材では収め方（crop / pad）が効く。 */
const fisheye = computed(
  () => settings.value.projection === 'fisheye'
)

onMounted(async () => {
  const options = await readOptions()
  if (options === null) return
  layouts.value = options.layouts
  projections.value = options.projections
  settings.value.fov = options.fovDefault
  displays.value = options.displays
  fits.value = options.fits
  presets.value = options.presets
  applyDetectedDisplay()
})

/** Bridge が機種を返したら `機種` をそれに合わせる。 */
const detected = computed(() => {
  const quilt = props.displayQuilt
  if (!quilt || Object.keys(presets.value).length === 0) return null
  return matchPreset(quilt, presets.value)
})

function applyDetectedDisplay(): void {
  if (detected.value !== null) settings.value.display = detected.value
}

watch(detected, () => {
  applyDetectedDisplay()
  void renderIfIdle()
})

/** いま選んでいる機種の quilt レイアウト。画像には名前が無いので明示で渡す。 */
const currentLayout = computed<QuiltLayout | null>(
  () => presets.value[settings.value.display] ?? null
)

const lastFrame = computed(() =>
  Math.max((source.value?.frameCount ?? 1) - 1, 0)
)

/** 機種が決まるまでは描けない。合っていない quilt は実機に出すまで気付けない。 */
const ready = computed(
  () => source.value !== null && currentLayout.value !== null
)

const start = computed(() =>
  Math.min(
    Math.max(parseCount(startText.value) ?? 0, 0),
    lastFrame.value
  )
)
/** 変換するフレーム数。空なら最後まで（null）。読めない文字は null にせず invalid で弾く。 */
const frames = computed(() => parseCount(framesText.value))

const startInvalid = computed(
  () =>
    startText.value.trim() !== '' &&
    parseCount(startText.value) === null
)
const framesInvalid = computed(() => {
  if (framesText.value.trim() === '') return false
  const value = frames.value
  return value === null || value < 1
})

/** 変換に渡す形。`span` と収束面はここで合流する。 */
function wire(convergence: string): ConvertSettings {
  return {
    ...settings.value,
    span: span.value,
    convergence,
    start: start.value,
    frames: frames.value,
  }
}

/** これが変わったらプレビューは描き直さないと合わない（収束面と視点は除く）。 */
const renderKey = computed(() =>
  JSON.stringify([settings.value, span.value, previewFrame.value])
)
const stale = computed(
  () =>
    renderedKey.value !== null &&
    renderedKey.value !== renderKey.value
)

async function onSelectFile(event: Event): Promise<void> {
  const chosen = (event.target as HTMLInputElement).files?.[0] ?? null
  source.value = null
  renderedKey.value = null
  baseConvergence.value = null
  previewFrame.value = 0
  startText.value = '0'
  framesText.value = ''
  if (chosen === null) return
  // 上げるのは 1 回だけ。プレビューでパラメータを変えるたびに送り直さない
  source.value = await upload(chosen)
  if (source.value === null) return
  // 左右の入り方と写り方は取り違えやすいので、当てられたら初期値にする
  if (source.value.suggestedLayout !== null) {
    settings.value.layout = source.value.suggestedLayout
  }
  if (source.value.suggestedProjection !== null) {
    settings.value.projection = source.value.suggestedProjection
  }
  await renderIfIdle()
}

/** 最初の 1 枚は自動で描く。何も出ていない画面から始めさせない。 */
async function renderIfIdle(): Promise<void> {
  if (renderedKey.value !== null || previewing.value) return
  if (!ready.value) return
  await render()
}

/** 現在の設定で 1 フレームだけ変換し、そのまま実機で見られるよう親へ渡す。 */
async function render(): Promise<void> {
  const loaded = source.value
  const layout = currentLayout.value
  if (loaded === null || layout === null) return
  const requested = renderKey.value
  const result = await preview(
    loaded.id,
    wire('auto'),
    previewFrame.value
  )
  if (result === null) return
  baseConvergence.value = result.convergence
  previewSeconds.value = result.seconds
  renderedKey.value = requested
  emit(
    'preview',
    result.blob,
    `${loaded.name} の ${previewFrame.value} フレーム目`,
    layout
  )
}

function onSubmit(): void {
  const loaded = source.value
  if (loaded === null || !ready.value) return
  // 画面で詰めた収束面を絶対値で焼き込む。auto のままだと動画の先頭フレームで
  // 決め直され、プレビューで見た位置とずれる
  const base = baseConvergence.value
  const convergence =
    base === null ? 'auto' : String(base + shift.value)
  void submit(loaded.id, wire(convergence))
}

function openInViewer(): void {
  const url = job.value?.resultUrl
  if (!url) return
  // Bridge は別プロセスなので、相対パスでは取りに行けない
  emit('loaded', new URL(url, window.location.href).toString())
}

const displayNote = computed(() => {
  const quilt = props.displayQuilt
  if (!quilt)
    return settings.value.display === ''
      ? '機種が決まっていない。下の Bridge に接続すると自動で入る'
      : '接続中の Looking Glass が分からないので、機種は手で選ぶ'
  if (detected.value === null)
    return `接続中の機種（${quilt.columns}x${quilt.rows} / ${quilt.quiltAspect}）に合うプリセットが無い`
  if (settings.value.display !== detected.value)
    return `接続中の機種は ${detected.value}。このままだと別機種向けの quilt になる`
  return `接続中の機種（${detected.value}）に合わせてある`
})

const layoutNote = computed(() => {
  const loaded = source.value
  if (loaded === null) return ''
  if (loaded.suggestedLayout === null)
    return '左右の入り方を当てられなかった。絵が真っ二つに切れていたら別の並びを選ぶ'
  if (settings.value.layout !== loaded.suggestedLayout)
    return `この動画は ${loaded.suggestedLayout} に見える。合っていないと絵が真っ二つに切れる`
  return `左右の入り方は ${loaded.suggestedLayout} と判定した`
})

const projectionNote = computed(() => {
  const loaded = source.value
  if (loaded === null) return ''
  if (loaded.suggestedProjection === 'fisheye' && !fisheye.value)
    return 'この動画は魚眼（VR180）に見える。平面として読むと黒い縁が入り、視差も合わない'
  if (fisheye.value)
    return '魚眼の円を片眼ずつ測って、中央の視野だけを平面へ直す。黒い縁は入らない'
  return ''
})

const convergenceNote = computed(() => {
  const base = baseConvergence.value
  if (base === null) return ''
  const used = (base + shift.value).toFixed(2)
  return `いま見えている収束面は ${used} px（自動 ${base.toFixed(2)} を ${shift.value} ずらした）。動画全体にはこの値を焼き込む`
})

/** 変換する枚数。フレーム数の指定が無ければ開始位置から最後まで。 */
const plannedFrames = computed(() => {
  const loaded = source.value
  if (loaded === null) return 0
  const rest = Math.max(loaded.frameCount - start.value, 0)
  return frames.value === null ? rest : Math.min(frames.value, rest)
})

/** 何を焼くのかを押す前に見せる。空欄が「最後まで」に化けるのを気付けるようにする。 */
const rangeNote = computed(() => {
  if (source.value === null) return ''
  if (plannedFrames.value === 0) return '変換するフレームが無い'
  const last = start.value + plannedFrames.value - 1
  const scope =
    frames.value === null
      ? 'フレーム数が空なので動画の最後まで'
      : `フレーム数 ${frames.value}`
  return `${start.value} 〜 ${last} の ${plannedFrames.value} フレーム（${scope}）`
})

const wholeVideoNote = computed(() => {
  const seconds = previewSeconds.value
  if (seconds === null || plannedFrames.value === 0) return ''
  // プレビュー 1 枚には円の検出・JPEG の圧縮・HTTP が入る。変換はこれより速いので上限として出す
  const total = seconds * plannedFrames.value
  return `長くても ${humanize(total)}（走らせると実測の残り時間が出る）`
})

const running = computed(
  () =>
    job.value?.status === 'queued' || job.value?.status === 'running'
)

const label = computed(() => {
  const current = job.value
  if (current === null) return ''
  if (current.status === 'queued') return '順番待ち'
  if (current.status === 'failed') return '失敗した'
  if (current.status === 'cancelled')
    return `中止した（${current.doneFrames} フレームで止めた）`
  if (current.status === 'done')
    return `完了（${current.doneFrames} フレーム）`
  const goal = current.totalFrames || '?'
  return `変換中 ${current.doneFrames} / ${goal} フレーム${remaining.value}`
})

/** 残りの見込み。**走っているジョブの実測から出す。**
 *
 * プレビュー 1 枚の時間から掛け算すると大きく外れる（1 枚の中に円の検出・JPEG の圧縮・
 * HTTP が入るので、実測で 2.9 秒に対して変換は 1 枚 0.52 秒だった）。
 */
const remaining = computed(() => {
  const current = job.value
  if (current === null || current.startedAt === null) return ''
  if (current.doneFrames < 3 || current.totalFrames === 0) return ''
  const elapsed = Date.now() / 1000 - current.startedAt
  const perFrame = elapsed / current.doneFrames
  const left = (current.totalFrames - current.doneFrames) * perFrame
  return `（1 枚 ${perFrame.toFixed(2)} 秒 / 残り およそ ${humanize(left)}）`
})

/** 数の入った文字列を整数として読む。読めなければ null。
 *
 * 全角数字と桁区切りを先に直す。`<input type="number">` は全角で入れた値
 * （IME が有効なら簡単に起きる）や `1,000` を**黙って捨てて value を空にする**ので、
 * テキストで受けてここで直す。捨てられるとフレーム数が「空＝最後まで」に化ける。
 */
function parseCount(text: string): number | null {
  const normalized = text
    .replace(/[０-９]/g, character =>
      String.fromCharCode(character.charCodeAt(0) - 0xfee0)
    )
    .replace(/[,\s]/g, '')
  if (normalized === '' || !/^\d+$/.test(normalized)) return null
  return Number.parseInt(normalized, 10)
}

/** 試すフレームの数値欄。直した値を欄へ書き戻して、何が入ったかを見せる。 */
function onPreviewFrameText(event: Event): void {
  const field = event.target as HTMLInputElement
  const parsed = parseCount(field.value)
  if (parsed !== null) {
    previewFrame.value = Math.min(
      Math.max(parsed, 0),
      lastFrame.value
    )
  }
  field.value = String(previewFrame.value)
}

function humanize(seconds: number): string {
  if (seconds < 120) return `${Math.round(seconds)} 秒`
  if (seconds < 7200) return `${Math.round(seconds / 60)} 分`
  return `${(seconds / 3600).toFixed(1)} 時間`
}
</script>

<template>
  <div class="workbench">
    <div class="stage-column">
      <slot name="stage" />
    </div>

    <div class="controls">
      <section class="block">
        <h3>素材</h3>
        <p class="row">
          <input
            type="file"
            accept="video/*"
            @change="onSelectFile"
          />
        </p>
        <p v-if="uploading" class="note">送っている…</p>
        <p v-else-if="source" class="note">
          {{ source.width }}x{{ source.height }} /
          {{ source.frameCount }} フレーム
        </p>
        <p class="row">
          <label>
            入力の並び
            <select v-model="settings.layout">
              <option
                v-for="name in layouts"
                :key="name"
                :value="name"
              >
                {{ name }}
              </option>
            </select>
          </label>
          <label>
            機種
            <select v-model="settings.display" required>
              <option value="" disabled>選ぶ</option>
              <option
                v-for="name in displays"
                :key="name"
                :value="name"
              >
                {{ name }}
              </option>
            </select>
          </label>
        </p>
        <p class="row">
          <label>
            写り方
            <select v-model="settings.projection">
              <option
                v-for="name in projections"
                :key="name"
                :value="name"
              >
                {{ name }}
              </option>
            </select>
          </label>
          <label>
            収め方
            <select v-model="settings.fit" :disabled="fisheye">
              <option v-for="name in fits" :key="name" :value="name">
                {{ name }}
              </option>
            </select>
          </label>
        </p>
        <p class="row">
          <label>
            <input v-model="settings.swapEyes" type="checkbox" />
            左右を入れ替える
          </label>
        </p>
        <p v-if="layoutNote" class="note">{{ layoutNote }}</p>
        <p v-if="projectionNote" class="note">
          {{ projectionNote }}
        </p>
        <p class="note">{{ displayNote }}</p>
      </section>

      <section class="block live">
        <h3>すぐ効く <span class="hint">描き直さずに変わる</span></h3>
        <p v-if="props.mode === 'single'" class="row">
          <label for="single-view">視点</label>
          <input
            id="single-view"
            v-model.number="singleView"
            type="range"
            min="0"
            :max="props.maxView"
          />
          <span class="value">{{ singleView }}</span>
        </p>
        <p class="row">
          <label for="shift">収束面</label>
          <input
            id="shift"
            v-model.number="shift"
            type="range"
            min="-24"
            max="24"
            step="0.5"
          />
          <span class="value">{{ shift }} px</span>
          <button
            type="button"
            :disabled="shift === 0"
            @click="shift = 0"
          >
            0 に戻す
          </button>
        </p>
        <p class="note">
          収束面は「どの奥行きが画面の面に来るか」。手前に出しすぎたら
          正の側へ、奥に沈んだら負の側へ動かす
        </p>
        <p v-if="convergenceNote" class="note">
          {{ convergenceNote }}
        </p>
      </section>

      <section class="block">
        <h3>
          描き直しが要る
          <span class="hint">変えたら 1 枚描き直す</span>
        </h3>
        <p class="row">
          <label for="span">視点の広がり</label>
          <input
            id="span"
            v-model.number="span"
            type="range"
            min="0.4"
            max="3"
            step="0.1"
          />
          <span class="value">{{ span.toFixed(1) }}</span>
        </p>
        <p class="note">
          大きいほど立体が強く出るが、端の視点で穴埋めの面積が増えて絵が荒れる
        </p>
        <p v-if="fisheye" class="row">
          <label for="fov">視野角</label>
          <input
            id="fov"
            v-model.number="settings.fov"
            type="range"
            min="20"
            max="120"
            step="5"
          />
          <span class="value">{{ settings.fov }}°</span>
        </p>
        <p v-if="fisheye" class="note">
          魚眼から切り出す横の画角。狭いほど中央だけを使うので歪みが減り、
          広いほど周りまで写るが端が伸びる
        </p>
        <p class="row">
          <label for="preview-frame">試すフレーム</label>
          <input
            id="preview-frame"
            v-model.number="previewFrame"
            type="range"
            min="0"
            :max="lastFrame"
            :disabled="source === null"
          />
          <input
            :value="previewFrame"
            type="text"
            inputmode="numeric"
            size="7"
            :disabled="source === null"
            @change="onPreviewFrameText"
          />
        </p>
        <p class="row">
          <button
            type="button"
            :disabled="previewing || !ready"
            @click="render"
          >
            {{ previewing ? '描いている…' : '1 枚描き直す' }}
          </button>
          <span v-if="stale" class="stale">設定を変えた</span>
        </p>
        <p v-if="!ready" class="note">
          動画を選んで機種が決まると描ける
        </p>
      </section>
    </div>

    <div class="output">
      <p class="row">
        <label>
          開始フレーム
          <input
            v-model="startText"
            type="text"
            inputmode="numeric"
            size="7"
            :class="{ bad: startInvalid }"
          />
        </label>
        <label>
          フレーム数
          <input
            v-model="framesText"
            type="text"
            inputmode="numeric"
            placeholder="空なら最後まで"
            size="12"
            :class="{ bad: framesInvalid }"
          />
        </label>
        <label>
          <input v-model="settings.copyAudio" type="checkbox" />
          音声を残す
        </label>
        <button
          type="button"
          :disabled="
            !ready ||
            uploading ||
            running ||
            startInvalid ||
            framesInvalid
          "
          @click="onSubmit"
        >
          変換する
        </button>
      </p>

      <p v-if="startInvalid || framesInvalid" class="warn">
        数として読めない文字が入っている（全角で入っていないか確認する）
      </p>
      <p v-else-if="rangeNote" class="note">
        {{ rangeNote
        }}<template v-if="wholeVideoNote">
          / {{ wholeVideoNote }}</template
        >
      </p>

      <p v-if="error" class="warn">{{ error }}</p>

      <template v-if="job">
        <p class="row">
          <progress :value="job.progress" max="1"></progress>
          <span>{{ label }}</span>
          <button v-if="running" type="button" @click="void cancel()">
            中止する
          </button>
          <button v-else type="button" @click="reset">閉じる</button>
        </p>
        <p v-if="job.error" class="warn">{{ job.error }}</p>
        <p v-if="job.resultUrl" class="row">
          <button type="button" @click="openInViewer">
            ここで再生する
          </button>
          <a :href="job.resultUrl" :download="job.outputName ?? ''">
            ダウンロード（{{ job.outputName }}）
          </a>
        </p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.workbench {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 22rem;
  grid-template-areas: 'stage controls' 'output output';
  gap: 1rem;
  align-items: start;
}

.stage-column {
  grid-area: stage;
  position: sticky;
  top: 1rem;
  /* 縦長のタイルだと絵が細いので、表示の操作は絵の横へ並べる */
  display: flex;
  align-items: flex-start;
  gap: 1rem;
}

.controls {
  grid-area: controls;
}

.output {
  grid-area: output;
  border-top: 1px solid #cfd8dc;
  padding-top: 0.5rem;
}

.block {
  border: 1px solid #cfd8dc;
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
  margin-bottom: 0.75rem;
}

.block h3 {
  margin: 0.25rem 0 0.5rem;
  font-size: 0.95rem;
}

.live {
  border-color: #2e7d32;
}

.hint {
  color: #78909c;
  font-size: 0.75rem;
  font-weight: normal;
}

.row {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  flex-wrap: wrap;
  margin: 0.4rem 0;
}

.row input[type='range'] {
  flex: 1;
  min-width: 6rem;
}

.value {
  font-variant-numeric: tabular-nums;
  min-width: 3.5rem;
}

.stale {
  color: #b26500;
}

.bad {
  border-color: #b3261e;
  background: #fdeceb;
}

.warn {
  color: #b3261e;
}

.note {
  color: #546e7a;
  font-size: 0.8rem;
  margin: 0.3rem 0;
}

progress {
  width: 12rem;
}

@media (max-width: 60rem) {
  .workbench {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: 'stage' 'controls' 'output';
  }

  .stage-column {
    position: static;
  }
}
</style>
