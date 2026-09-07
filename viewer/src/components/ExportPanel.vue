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
  /** Whether a source and a model are chosen; baking waits until they are */
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
/** How many frames to convert. Empty means to the end (null); unreadable text is rejected as
 * invalid
 */
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

/** Show what will be baked before the button is pressed, so an empty field turning into "to the
 * end" is noticed
 */
const plan = computed(() => {
  if (props.source === null || plannedFrames.value === 0) return ''
  const range = t('export.plan', {
    start: start.value,
    last: start.value + plannedFrames.value - 1,
    count: plannedFrames.value,
  })
  return range
})

/** The remaining estimate, **measured from the running job**.
 *
 * Multiplying a preview frame's time is far off: a preview includes circle detection, JPEG
 * compression, and HTTP, and measured 2.9 seconds against 0.52 seconds per converted frame.
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

// Reset the range when the source changes; numbers meant for the previous video would make the
// fields disagree with what is actually baked
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
  // A full URL keeps working regardless of the page the link is opened from
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
