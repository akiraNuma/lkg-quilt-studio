<script setup lang="ts">
import { computed, ref, useTemplateRef } from 'vue'
import type { ConvertJob, QuiltSourceInfo } from '../api'
import { size, stamp } from '../format'
import { t, type MessageKey } from '../i18n'

const props = defineProps<{
  sources: QuiltSourceInfo[]
  /** Jobs that produced output */
  outputs: ConvertJob[]
  /** Jobs with no output after failing or being cancelled */
  leftovers: ConvertJob[]
  /** The id of the source being tuned, marked because deleting it clears the picture */
  currentSourceId: string | null
  loading: boolean
  error: string | null
}>()

const emit = defineEmits<{
  play: [url: string]
  use: [source: QuiltSourceInfo]
  removeSource: [id: string]
  removeJob: [id: string]
  refresh: []
  openFile: [file: File]
  openUri: [uri: string]
}>()

const STATUS_KEY: Record<ConvertJob['status'], MessageKey> = {
  queued: 'job.queued',
  running: 'job.running',
  done: 'job.done',
  failed: 'job.failed',
  cancelled: 'job.cancelled',
}

/** Ask once before deleting, remembering the id so only that row changes its wording */
const pending = ref<string | null>(null)
const uriInput = ref('')

const outputTotal = computed(() => total(props.outputs))
const sourceTotal = computed(() => total(props.sources))

/** "size / imported at". Old state files carry no timestamp, so an empty part is dropped */
function meta(parts: (string | number)[]): string {
  return parts.filter(part => part !== '').join(' / ')
}

function total(items: { sizeBytes: number }[]): string {
  return t('library.total', {
    count: items.length,
    size: size(items.reduce((sum, item) => sum + item.sizeBytes, 0)),
  })
}

function onPlay(job: ConvertJob): void {
  if (job.resultUrl === null) return
  emit('play', job.resultUrl)
}

function confirmRemove(id: string): void {
  pending.value = pending.value === id ? null : id
}

function removeSource(id: string): void {
  pending.value = null
  emit('removeSource', id)
}

function removeJob(id: string): void {
  pending.value = null
  emit('removeJob', id)
}

// The file field takes its wording from the browser's language, so open it from our own button
const picker = useTemplateRef<HTMLInputElement>('picker')

function pick(): void {
  picker.value?.click()
}

function onOpenFile(event: Event): void {
  const field = event.target as HTMLInputElement
  const file = field.files?.[0]
  if (file) emit('openFile', file)
  // Make change fire even when the same file is chosen again
  field.value = ''
}

function onOpenUri(): void {
  emit('openUri', uriInput.value)
}
</script>

<template>
  <section class="panel">
    <h2>
      {{ t('library.title') }}
      <button
        class="refresh"
        :aria-label="t('library.refresh')"
        :title="t('library.refresh')"
        :disabled="loading"
        @click="$emit('refresh')"
      >
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.75"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path d="M20 7v5h-5M4 17v-5h5" />
          <path
            d="M6.1 6.1a8 8 0 0 1 13.5 4.1M4.4 13.8a8 8 0 0 0 13.5 4.1"
          />
        </svg>
      </button>
    </h2>

    <h3>{{ t('library.outputs') }}</h3>
    <p v-if="outputs.length === 0" class="empty">
      {{ t('library.empty') }}
    </p>
    <ul v-else class="items">
      <li v-for="job in outputs" :key="job.id">
        <span class="name" :title="job.outputName ?? ''">
          {{ job.outputName }}
        </span>
        <span class="note">
          {{ meta([size(job.sizeBytes), stamp(job.createdAt)]) }}
        </span>
        <span v-if="pending === job.id" class="row">
          <span class="warn">{{ t('library.confirm') }}</span>
          <button class="small" @click="removeJob(job.id)">
            {{ t('library.yes') }}
          </button>
          <button class="small" @click="pending = null">
            {{ t('library.no') }}
          </button>
        </span>
        <span v-else class="row">
          <button class="small" @click="onPlay(job)">
            {{ t('library.play') }}
          </button>
          <a
            class="small"
            :href="job.resultUrl ?? ''"
            :download="job.outputName ?? ''"
          >
            {{ t('library.download') }}
          </a>
          <button class="small" @click="confirmRemove(job.id)">
            {{ t('library.delete') }}
          </button>
        </span>
      </li>
    </ul>
    <p v-if="outputs.length" class="note">{{ outputTotal }}</p>

    <h3>{{ t('library.sources') }}</h3>
    <p v-if="sources.length === 0" class="empty">
      {{ t('library.empty') }}
    </p>
    <ul v-else class="items">
      <li v-for="source in sources" :key="source.id">
        <span class="name" :title="source.name">{{
          source.name
        }}</span>
        <span class="note">
          {{
            meta([
              `${source.width}x${source.height}`,
              size(source.sizeBytes),
              stamp(source.createdAt),
            ])
          }}
        </span>
        <span v-if="pending === source.id" class="row">
          <span class="warn">{{ t('library.confirm') }}</span>
          <button class="small" @click="removeSource(source.id)">
            {{ t('library.yes') }}
          </button>
          <button class="small" @click="pending = null">
            {{ t('library.no') }}
          </button>
        </span>
        <span v-else class="row">
          <button
            class="small"
            :disabled="source.id === currentSourceId"
            @click="$emit('use', source)"
          >
            {{
              source.id === currentSourceId
                ? t('library.inUse')
                : t('library.use')
            }}
          </button>
          <button class="small" @click="confirmRemove(source.id)">
            {{ t('library.delete') }}
          </button>
        </span>
      </li>
    </ul>
    <p v-if="sources.length" class="note">{{ sourceTotal }}</p>

    <template v-if="leftovers.length">
      <h3>{{ t('library.leftovers') }}</h3>
      <ul class="items">
        <li v-for="job in leftovers" :key="job.id">
          <span class="name" :title="job.sourceName">
            {{ job.sourceName }}
          </span>
          <span class="note">{{ t(STATUS_KEY[job.status]) }}</span>
          <span v-if="pending === job.id" class="row">
            <button class="small" @click="removeJob(job.id)">
              {{ t('library.yes') }}
            </button>
            <button class="small" @click="pending = null">
              {{ t('library.no') }}
            </button>
          </span>
          <button v-else class="small" @click="confirmRemove(job.id)">
            {{ t('library.delete') }}
          </button>
        </li>
      </ul>
    </template>

    <p v-if="error" class="error">{{ error }}</p>

    <details>
      <summary>{{ t('library.open') }}</summary>
      <p class="row">
        <button @click="pick">{{ t('library.pickFile') }}</button>
      </p>
      <input
        ref="picker"
        class="picker"
        type="file"
        accept="video/*"
        @change="onOpenFile"
      />
      <form class="row" @submit.prevent="onOpenUri">
        <input
          v-model="uriInput"
          type="text"
          :placeholder="t('library.uri')"
        />
        <button type="submit">{{ t('library.load') }}</button>
      </form>
    </details>
  </section>
</template>

<style scoped>
h3 {
  font-size: 0.9rem;
  color: var(--text);
  margin: 0.45rem 0 0;
}

.empty {
  margin: 0;
  padding: 1.2rem 0.9rem;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
  background: var(--surface-inset);
  color: var(--muted);
  font-size: 0.8rem;
  font-weight: 400;
  text-align: center;
}

.items {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  /* It grows without bound as items pile up, so scroll inside this box */
  max-height: 14rem;
  overflow-y: auto;
}

.items li {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  padding: 0.75rem;
  background: var(--surface-inset);
  border: 1px solid var(--line);
  border-radius: 8px;
}

.name {
  font-size: 0.875rem;
  font-weight: 500;
  /* A long filename must not push the right column wider */
  overflow-wrap: anywhere;
}

.small {
  font-size: 0.75rem;
  padding: 0.3rem 0.55rem;
  min-height: 2rem;
  display: inline-flex;
  align-items: center;
}

a.small {
  color: var(--accent);
  text-decoration: none;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
}

.refresh {
  margin-left: auto;
  background: none;
  border-color: transparent;
  width: 2.25rem;
  padding: 0.4rem;
  display: grid;
  place-items: center;
  color: var(--muted);
}

.refresh svg {
  width: 1.1rem;
  height: 1.1rem;
}

details {
  margin-top: 0.4rem;
  padding-top: 0.8rem;
  border-top: 1px solid var(--line);
}

details .row {
  margin-top: 0.65rem;
}

summary {
  cursor: pointer;
  color: var(--muted);
  font-size: 0.85rem;
}

details[open] summary {
  margin-bottom: 0.5rem;
}

.picker {
  display: none;
}

details input[type='text'] {
  flex: 1;
  min-width: 0;
}
</style>
