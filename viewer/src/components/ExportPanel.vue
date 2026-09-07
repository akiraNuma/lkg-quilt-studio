<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type {
  ConvertJob,
  OutputSettings,
  QuiltSourceInfo,
} from '../api'
import { humanize, parseCount } from '../format'
import { t } from '../i18n'

const props = defineProps<{
  source: QuiltSourceInfo | null
  /** 素材と機種が決まっているか。決まるまで焼かせない */
  ready: boolean
  job: ConvertJob | null
  running: boolean
  error: string | null
}>()

const emit = defineEmits<{
  submit: [output: OutputSettings]
  cancel: []
  reset: []
  open: [url: string]
}>()

const startText = ref('0')
const framesText = ref('')
const copyAudio = ref(true)

const lastFrame = computed(() =>
  Math.max((props.source?.frameCount ?? 1) - 1, 0)
)
const start = computed(() =>
  Math.min(
    Math.max(parseCount(startText.value) ?? 0, 0),
    lastFrame.value
  )
)
/** 変換する枚数。空なら最後まで（null）。読めない文字は invalid で弾く */
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

const plannedFrames = computed(() => {
  const loaded = props.source
  if (loaded === null) return 0
  const rest = Math.max(loaded.frameCount - start.value, 0)
  return frames.value === null ? rest : Math.min(frames.value, rest)
})

/** 何を焼くのかを押す前に見せる。空欄が「最後まで」に化けるのを気付けるようにする */
const plan = computed(() => {
  if (props.source === null || plannedFrames.value === 0) return ''
  const range = t('export.plan', {
    start: start.value,
    last: start.value + plannedFrames.value - 1,
    count: plannedFrames.value,
  })
  return range
})

/** 残りの見込み。**走っているジョブの実測から出す。**
 *
 * プレビュー 1 枚の時間から掛け算すると大きく外れる（1 枚の中に円の検出・JPEG の圧縮・
 * HTTP が入るので、実測で 2.9 秒に対して変換は 1 枚 0.52 秒だった）。
 */
const remaining = computed(() => {
  const current = props.job
  if (current === null || current.startedAt === null) return ''
  if (current.doneFrames < 3 || current.totalFrames === 0) return ''
  const elapsed = Date.now() / 1000 - current.startedAt
  const perFrame = elapsed / current.doneFrames
  const left = (current.totalFrames - current.doneFrames) * perFrame
  return ` / ${t('export.remaining', { time: humanize(left) })}`
})

const status = computed(() => {
  const current = props.job
  if (current === null) return ''
  if (current.status === 'queued') return t('job.queued')
  if (current.status === 'failed') return t('job.failed')
  if (current.status === 'cancelled' || current.status === 'done')
    return t('export.doneFrames', {
      status: t(
        current.status === 'done' ? 'job.done' : 'job.cancelled'
      ),
      frames: current.doneFrames,
    })
  const progress = t('export.progress', {
    done: current.doneFrames,
    total: current.totalFrames || '?',
  })
  return `${progress}${remaining.value}`
})

// 素材を替えたら範囲を戻す。前の動画向けの数字が残ると、欄の表示と実際に焼く範囲がずれる
watch(
  () => props.source?.id,
  () => {
    startText.value = '0'
    framesText.value = ''
  }
)

function onSubmit(): void {
  emit('submit', {
    start: start.value,
    frames: frames.value,
    copyAudio: copyAudio.value,
  })
}

function onOpen(): void {
  const url = props.job?.resultUrl
  if (!url) return
  // Bridge は別プロセスなので、相対パスでは取りに行けない
  emit('open', new URL(url, window.location.href).toString())
}
</script>

<template>
  <section class="panel">
    <h2><span class="step">4</span>{{ t('export.title') }}</h2>

    <div class="range">
      <label>
        {{ t('export.start') }}
        <input
          v-model="startText"
          type="text"
          inputmode="numeric"
          :class="{ bad: startInvalid }"
        />
      </label>
      <label>
        {{ t('export.frames') }}
        <input
          v-model="framesText"
          type="text"
          inputmode="numeric"
          :placeholder="t('export.toEnd')"
          :class="{ bad: framesInvalid }"
        />
      </label>
    </div>

    <label>
      <input v-model="copyAudio" type="checkbox" />
      {{ t('export.copyAudio') }}
    </label>

    <p v-if="startInvalid || framesInvalid" class="error">
      {{ t('export.badNumber') }}
    </p>
    <p v-else-if="plan" class="note">
      {{ plan }}
    </p>

    <p class="row">
      <button
        class="primary"
        :disabled="!ready || running || startInvalid || framesInvalid"
        @click="onSubmit"
      >
        {{ t('export.submit') }}
      </button>
      <button v-if="running" @click="$emit('cancel')">
        {{ t('export.cancel') }}
      </button>
    </p>

    <p v-if="error" class="error">{{ error }}</p>

    <template v-if="job">
      <progress :value="job.progress" max="1"></progress>
      <p class="row">
        <span class="status">{{ status }}</span>
        <button v-if="!running" class="link" @click="$emit('reset')">
          {{ t('export.close') }}
        </button>
      </p>
      <p v-if="job.error" class="error">{{ job.error }}</p>
      <p v-if="job.resultUrl" class="row">
        <button @click="onOpen">{{ t('export.play') }}</button>
        <a :href="job.resultUrl" :download="job.outputName ?? ''">
          {{ t('export.download') }}
        </a>
      </p>
    </template>
  </section>
</template>

<style scoped>
.range {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
}

.range label {
  display: grid;
  gap: 0.3rem;
  min-width: 0;
  color: var(--muted);
  font-size: 0.85rem;
}

.range input {
  width: 100%;
  min-width: 0;
  text-align: right;
}

.bad {
  border-color: var(--danger);
}

progress {
  width: 100%;
}

.status {
  font-size: 0.85rem;
  font-variant-numeric: tabular-nums;
}

.link {
  margin-left: auto;
  background: none;
  border: 0;
  padding: 0;
  color: var(--muted);
  font-size: 0.8rem;
  text-decoration: underline;
}
</style>
