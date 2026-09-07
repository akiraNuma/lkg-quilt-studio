<script setup lang="ts">
import { computed, ref, useTemplateRef, watch } from 'vue'
import QuiltStage from './QuiltStage.vue'
import type { QuiltSource } from '../composables/useQuiltSource'
import { t, type MessageKey } from '../i18n'
import {
  VIEW_MODES,
  type Calibration,
  type ViewMode,
} from '../lenticular'

const props = defineProps<{
  source: QuiltSource | null
  singleView: number
  shift: number
  span: number
  calibration: Calibration | null
  /** The Looking Glass window's position and size; without it nothing can be moved */
  windowRect: {
    x: number
    y: number
    width: number
    height: number
  } | null
  /** Whether a redraw is in flight */
  rendering: boolean
  /** A caution shown beside the picture, such as a video / model mismatch */
  warning: string | null
  error: string | null
}>()

const mode = defineModel<ViewMode>('mode', { required: true })

const MODE_KEY: Record<ViewMode, MessageKey> = {
  lenticular: 'stage.mode.lenticular',
  single: 'stage.mode.single',
  quilt: 'stage.mode.quilt',
}

/** The picture's caption, **built in a computed** (a stored `t()` result would not follow a
 * language change)
 */
const title = computed(() => {
  const loaded = props.source
  if (loaded === null) return ''
  return loaded.frameIndex === null
    ? loaded.name
    : t('stage.frameName', {
        name: loaded.name,
        frame: loaded.frameIndex,
      })
})

const stage = useTemplateRef<InstanceType<typeof QuiltStage>>('stage')
const stageError = ref<string | null>(null)
// A person can close the window directly, so read the owning QuiltStage's state as is
const movedOut = computed(() => stage.value?.poppedOut === true)

// The Tune panel shows the same button next to the values, so it drives the stage from here
defineExpose({ movedOut, moveToDisplay, bringBack })

// A redraw or a new source can fix it; keeping the previous failure leaves red text behind
watch(
  () => props.source,
  () => (stageError.value = null)
)

function moveToDisplay(): void {
  if (props.windowRect === null) return
  mode.value = 'lenticular'
  stage.value?.openWindow(props.windowRect)
}

function bringBack(): void {
  stage.value?.closeWindow()
}
</script>

<template>
  <div class="column">
    <div class="viewport">
      <p v-if="source === null" class="empty">
        {{ t('stage.empty') }}
      </p>
      <QuiltStage
        v-else
        ref="stage"
        :source="source"
        :mode="mode"
        :single-view="singleView"
        :shift="shift"
        :span="span"
        :calibration="calibration"
        @error="stageError = $event"
      />
      <p v-if="rendering" class="badge">
        <span class="spinner" aria-hidden="true" />{{
          t('stage.rendering')
        }}
      </p>
    </div>

    <div v-if="source" class="toolbar">
      <div class="modes" role="group">
        <button
          v-for="option in VIEW_MODES"
          :key="option"
          :class="{ on: mode === option }"
          @click="mode = option"
        >
          {{ t(MODE_KEY[option]) }}
        </button>
      </div>
      <button
        v-if="!movedOut"
        :disabled="windowRect === null"
        @click="moveToDisplay"
      >
        {{ t('stage.moveOut') }}
      </button>
      <button v-else @click="bringBack">
        {{ t('stage.bringBack') }}
      </button>
    </div>

    <p v-if="source" class="note">
      {{ title }} / {{ source.layout.columns }}x{{
        source.layout.rows
      }}
      <template v-if="mode === 'lenticular'">
        / {{ t('stage.stripes') }}
      </template>
    </p>
    <p v-if="warning" class="warn">{{ warning }}</p>
    <p v-if="stageError" class="error">{{ stageError }}</p>
    <p v-if="error" class="error">{{ error }}</p>
  </div>
</template>

<style scoped>
.column {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0.5rem;
  text-align: center;
  /* A portrait tile (0.5625 on the Go) makes the picture narrow. The controls and notes follow
     the picture's width */
  max-width: min(100%, 46rem);
  margin-inline: auto;
}

.viewport {
  position: relative;
  display: flex;
  justify-content: center;
}

.empty {
  display: grid;
  place-content: center;
  width: 100%;
  min-height: clamp(16rem, 48vh, 32rem);
  padding: 2rem;
  background: var(--surface-inset);
  font-size: 0.9rem;
  margin: 0;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
  color: var(--muted);
}

/* Centred, so it sits on the picture and not in the empty space beside a portrait tile */
.badge {
  position: absolute;
  top: 0.5rem;
  left: 50%;
  transform: translateX(-50%);
  margin: 0;
  white-space: nowrap;
  padding: 0.15rem 0.55rem;
  border-radius: 999px;
  background: var(--overlay);
  color: var(--text);
  font-size: 0.75rem;
}

.toolbar {
  display: flex;
  justify-content: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.modes {
  display: flex;
}

.modes button {
  border-radius: 0;
  font-size: 0.85rem;
}

.modes button:first-child {
  border-radius: 6px 0 0 6px;
}

.modes button:last-child {
  border-radius: 0 6px 6px 0;
  border-left-width: 0;
}

.modes button:not(:first-child):not(:last-child) {
  border-left-width: 0;
}

.modes button.on {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--accent-ink);
}
</style>
