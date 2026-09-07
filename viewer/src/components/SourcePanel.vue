<script setup lang="ts">
import { computed, ref, useTemplateRef } from 'vue'
import type { ConverterOptions, QuiltSourceInfo } from '../api'
import { t } from '../i18n'

const props = defineProps<{
  options: ConverterOptions | null
  source: QuiltSourceInfo | null
  uploading: boolean
  /** The preset name for the model Bridge reported, or null when unavailable */
  detected: string | null
}>()

const emit = defineEmits<{ select: [file: File | null] }>()

// Settings arrive one at a time. Taking them as a single object would let a deep property be
// rewritten without emitting an update, leaving v-model in name only
const layout = defineModel<string>('layout', { required: true })
const display = defineModel<string>('display', { required: true })
const projection = defineModel<string>('projection', {
  required: true,
})
const fit = defineModel<string>('fit', { required: true })
const swapEyes = defineModel<boolean>('swapEyes', { required: true })

const fisheye = computed(() => projection.value === 'fisheye')

// The file field is opened from our own button. `<input type="file">` takes its appearance and
// wording from the browser's language, which would mix languages on screen
const picker = useTemplateRef<HTMLInputElement>('picker')
const dragDepth = ref(0)
const multipleFiles = ref(false)

function onDragEnter(event: DragEvent): void {
  if (event.dataTransfer?.types.includes('Files')) dragDepth.value++
}

function onDragLeave(): void {
  dragDepth.value = Math.max(0, dragDepth.value - 1)
}

function onDragOver(event: DragEvent): void {
  if (event.dataTransfer)
    event.dataTransfer.dropEffect = props.uploading ? 'none' : 'copy'
}

function onDrop(event: DragEvent): void {
  dragDepth.value = 0
  if (props.uploading) return
  const files = event.dataTransfer?.files
  if (!files?.length) return
  multipleFiles.value = files.length !== 1
  if (!multipleFiles.value) emit('select', files[0])
}

function pick(): void {
  picker.value?.click()
}

function onSelectFile(event: Event): void {
  const field = event.target as HTMLInputElement
  const file = field.files?.[0]
  if (file && !props.uploading) {
    multipleFiles.value = false
    emit('select', file)
  }
  // Make change fire even when the same file is chosen again
  field.value = ''
}

/** Speak only on a disagreement with the detection; confirming agreement is just noise */
const warning = computed(() => {
  const loaded = props.source
  if (loaded === null) return null
  // Without a preset for the model nothing can be drawn, and stopping silently hides the reason
  if (
    props.options !== null &&
    !props.options.displays.includes(display.value)
  )
    return t('source.warn.preset')
  if (loaded.suggestedLayout === null)
    return t('source.warn.unknownLayout')
  if (layout.value !== loaded.suggestedLayout)
    return t('source.warn.layout', { layout: loaded.suggestedLayout })
  if (loaded.suggestedProjection === 'fisheye' && !fisheye.value)
    return t('source.warn.fisheye')
  if (props.detected !== null && display.value !== props.detected)
    return t('source.warn.detected', { display: props.detected })
  return null
})
</script>

<template>
  <section class="panel">
    <h2><span class="step">2</span>{{ t('source.title') }}</h2>

    <div
      class="dropzone"
      :class="{ dragging: dragDepth > 0 && !uploading }"
      :aria-busy="uploading"
      @dragenter.prevent="onDragEnter"
      @dragleave.prevent="onDragLeave"
      @dragover.prevent="onDragOver"
      @drop.prevent="onDrop"
    >
      <button :disabled="uploading" @click="pick">
        {{ t('source.pick') }}
      </button>
      <p class="note">{{ t('source.dropHint') }}</p>
      <span v-if="source" class="name">{{ source.name }}</span>
    </div>
    <p v-if="multipleFiles" class="error" role="alert">
      {{ t('source.oneFile') }}
    </p>
    <input
      ref="picker"
      class="picker"
      type="file"
      accept="video/*"
      :disabled="uploading"
      @change="onSelectFile"
    />
    <p v-if="uploading" class="note">{{ t('source.uploading') }}</p>
    <p v-else-if="source" class="note">
      {{
        t('source.meta', {
          width: source.width,
          height: source.height,
          frames: source.frameCount,
          fps: source.fps.toFixed(0),
        })
      }}
    </p>

    <div class="grid">
      <label>
        {{ t('source.layout') }}
        <select v-model="layout">
          <option
            v-for="name in options?.layouts ?? []"
            :key="name"
            :value="name"
          >
            {{ name }}
          </option>
        </select>
      </label>
      <label>
        {{ t('source.display') }}
        <select v-model="display">
          <option value="" disabled>
            {{ t('source.choose') }}
          </option>
          <option
            v-for="name in options?.displays ?? []"
            :key="name"
            :value="name"
          >
            {{ name }}
          </option>
        </select>
      </label>
      <label>
        {{ t('source.projection') }}
        <select v-model="projection">
          <option
            v-for="name in options?.projections ?? []"
            :key="name"
            :value="name"
          >
            {{ name }}
          </option>
        </select>
      </label>
      <label>
        {{ t('source.fit') }}
        <select v-model="fit" :disabled="fisheye">
          <option
            v-for="name in options?.fits ?? []"
            :key="name"
            :value="name"
          >
            {{ name }}
          </option>
        </select>
      </label>
    </div>

    <label>
      <input v-model="swapEyes" type="checkbox" />
      {{ t('source.swapEyes') }}
    </label>

    <p v-if="warning" class="warn">{{ warning }}</p>
  </section>
</template>

<style scoped>
.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 1.2rem 0.75rem;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
  background: var(--surface-inset);
  text-align: center;
}

.dropzone.dragging {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.picker {
  display: none;
}

.name {
  font-size: 0.8rem;
  overflow-wrap: anywhere;
}

.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.grid label {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 0.3rem;
  color: var(--muted);
  font-size: 0.85rem;
}

.grid select {
  flex: 1;
  min-width: 0;
}
</style>
