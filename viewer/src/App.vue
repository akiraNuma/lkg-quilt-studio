<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import DisplayPanel from './components/DisplayPanel.vue'
import ExportPanel from './components/ExportPanel.vue'
import LibraryPanel from './components/LibraryPanel.vue'
import SourcePanel from './components/SourcePanel.vue'
import StagePanel from './components/StagePanel.vue'
import TunePanel from './components/TunePanel.vue'
import { useBridge } from './composables/useBridge'
import { useConvertJob } from './composables/useConvertJob'
import { useLibrary } from './composables/useLibrary'
import { usePreview } from './composables/usePreview'
import { useQuiltSource } from './composables/useQuiltSource'
import type { OutputSettings, QuiltSourceInfo } from './api'
import { LOCALES, LOCALE_LABEL, locale, setLocale, t } from './i18n'
import type { ViewMode } from './lenticular'
import { layoutMismatch, viewCount } from './quilt'

const bridge = useBridge()
const selectedDisplay = ref(0)

const display = computed(
  () =>
    bridge.displays.value.find(
      found => found.index === selectedDisplay.value
    ) ?? null
)
const displayQuilt = computed(() => display.value?.quilt ?? null)
const calibration = computed(() => display.value?.calibration ?? null)

const {
  options,
  settings,
  span,
  frameIndex,
  source: sourceInfo,
  uploading,
  rendering,
  error: previewError,
  failed,
  frame,
  baseConvergence,
  fisheye,
  lastFrame,
  detected,
  ready,
  selectFile,
  adopt,
  clear: clearPreview,
  retry,
  renderSettings,
} = usePreview(displayQuilt)

const {
  source,
  error: sourceError,
  fromFile,
  fromUri,
  fromImage,
  clear: clearStage,
} = useQuiltSource()
const convert = useConvertJob()
const library = useLibrary()

const mode = ref<ViewMode>('lenticular')
const singleView = ref(0)
// 収束面のずらし（視差の画素）。焼き込んだ値を再生側で上書きする
const shift = ref(0)

// Bridge の index は 0 から始まらない。Looking Glass 以外のモニタが混ざっていると、
// 一覧から外れた分だけ番号が飛ぶ（実測で Go が index 1）。選んだ番号が一覧に無いと
// 較正値も quilt も取れないまま画面が黙るので、繋がった時点で先頭へ寄せる
watch(
  bridge.displays,
  found => {
    if (found.length === 0) return
    if (found.some(one => one.index === selectedDisplay.value)) return
    selectedDisplay.value = found[0].index
  },
  { immediate: true }
)

const maxView = computed(() =>
  source.value === null ? 0 : viewCount(source.value.layout) - 1
)

const mismatch = computed(() => {
  const quilt = displayQuilt.value
  if (source.value === null || !quilt) return null
  return layoutMismatch(source.value.layout, quilt)
})

const windowRect = computed(() => {
  const target = display.value
  if (target?.calibration == null || target.windowCoords === null)
    return null
  return {
    x: target.windowCoords.x,
    y: target.windowCoords.y,
    width: target.calibration.screenW,
    height: target.calibration.screenH,
  }
})

// 描き上がった 1 枚をそのまま絵に載せる。収束面のずらしは残す
// （描き直すたびに 0 へ戻ると詰められない）
watch(frame, latest => {
  if (latest === null) return
  const first = source.value === null
  fromImage(
    latest.blob,
    latest.name,
    latest.frameIndex,
    latest.layout
  )
  if (first || singleView.value > maxView.value) centerView()
})

// 焼き上がった動画は一覧に出す。押して確かめるまで残っているか分からないのは不便
watch(
  () => convert.job.value?.status,
  status => {
    // 失敗も一覧に出す（leftovers）。押すまで見えないと消せない
    if (
      status === 'done' ||
      status === 'cancelled' ||
      status === 'failed'
    )
      void library.refresh()
  }
)

function centerView(): void {
  singleView.value = Math.floor(maxView.value / 2)
}

function onSubmit(output: OutputSettings): void {
  const loaded = sourceInfo.value
  if (loaded === null || !ready.value) return
  // 画面で詰めた収束面を絶対値で焼き込む。auto のままだと動画の先頭フレームで
  // 決め直され、プレビューで見た位置とずれる
  const base = baseConvergence.value
  const convergence =
    base === null ? 'auto' : String(base + shift.value)
  void convert.submit(loaded.id, {
    ...renderSettings(convergence),
    ...output,
  })
}

/** 動画を上げたら一覧にも出す（上げ直したのに見えないと二重に上げてしまう） */
async function onSelectFile(file: File | null): Promise<void> {
  await selectFile(file)
  await library.refresh()
}

/** 一覧から素材を選び直す。上げ直さないので待ち時間が無い */
function useSource(info: QuiltSourceInfo): void {
  adopt(info)
  shift.value = 0
}

async function onRemoveSource(id: string): Promise<void> {
  const removed = await library.removeSource(id)
  // 消した素材を掴んだままだと、描き直せない絵を見ながら操作することになる。
  // 断られた（変換中）ときは絵を残す。捨てると詰めていた位置を失う
  if (removed && sourceInfo.value?.id === id) {
    clearPreview()
    clearStage()
  }
}

async function onRemoveJob(id: string): Promise<void> {
  const removed = await library.removeJob(id)
  if (removed && convert.job.value?.id === id) convert.reset()
}

function openUri(uri: string): void {
  fromUri(uri)
  resetView()
}

function openFile(file: File): void {
  fromFile(file)
  resetView()
}

function resetView(): void {
  shift.value = 0
  centerView()
}
</script>

<template>
  <div class="app">
    <header>
      <h1>lkg-quilt-studio</h1>
      <p class="note">{{ t('app.tagline') }}</p>
      <p class="locales">
        <button
          v-for="one in LOCALES"
          :key="one"
          :class="{ on: locale === one }"
          @click="setLocale(one)"
        >
          {{ LOCALE_LABEL[one] }}
        </button>
      </p>
    </header>

    <main>
      <StagePanel
        v-model:mode="mode"
        :source="source"
        :single-view="singleView"
        :shift="shift"
        :span="span"
        :calibration="calibration"
        :window-rect="windowRect"
        :rendering="rendering"
        :warning="mismatch"
        :error="sourceError"
      />
    </main>

    <aside>
      <DisplayPanel
        v-model:selected="selectedDisplay"
        :status="bridge.status.value"
        :message="bridge.message.value"
        :displays="bridge.displays.value"
        @connect="void bridge.connect()"
        @refresh="void bridge.refresh()"
        @disconnect="void bridge.disconnect()"
      />

      <SourcePanel
        v-model:layout="settings.layout"
        v-model:display="settings.display"
        v-model:projection="settings.projection"
        v-model:fit="settings.fit"
        v-model:swap-eyes="settings.swapEyes"
        :options="options"
        :source="sourceInfo"
        :uploading="uploading"
        :detected="detected"
        @select="void onSelectFile($event)"
      />

      <TunePanel
        v-model:shift="shift"
        v-model:single-view="singleView"
        v-model:span="span"
        v-model:fov="settings.fov"
        v-model:frame-index="frameIndex"
        :disabled="!ready"
        :mode="mode"
        :max-view="maxView"
        :fisheye="fisheye"
        :last-frame="lastFrame"
        :base-convergence="baseConvergence"
      />

      <div v-if="previewError" class="panel">
        <p class="row error">
          {{ previewError }}
          <button v-if="failed" @click="retry">
            {{ t('app.retry') }}
          </button>
        </p>
      </div>

      <ExportPanel
        :source="sourceInfo"
        :ready="ready"
        :job="convert.job.value"
        :running="convert.running.value"
        :error="convert.error.value"
        @submit="onSubmit"
        @cancel="void convert.cancel()"
        @reset="convert.reset"
        @open="openUri"
      />

      <LibraryPanel
        :sources="library.sources.value"
        :outputs="library.outputs.value"
        :leftovers="library.leftovers.value"
        :current-source-id="sourceInfo?.id ?? null"
        :loading="library.loading.value"
        :error="library.error.value"
        @play="openUri"
        @use="useSource"
        @remove-source="void onRemoveSource($event)"
        @remove-job="void onRemoveJob($event)"
        @refresh="void library.refresh()"
        @open-file="openFile"
        @open-uri="openUri"
      />
    </aside>
  </div>
</template>

<style scoped>
.app {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 26rem;
  grid-template-areas: 'head head' 'stage side';
  gap: 1rem;
  align-items: start;
  max-width: 100rem;
  margin: 0 auto;
  padding: 1.5rem;
}

header {
  grid-area: head;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem 1rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid var(--line);
}

h1 {
  font-size: 1.15rem;
  letter-spacing: -0.025em;
  margin: 0;
}

.locales {
  display: flex;
  gap: 0.25rem;
  margin: 0 0 0 auto;
}

.locales button {
  font-size: 0.75rem;
  padding: 0.25rem 0.6rem;
  min-height: 2rem;
}

.locales button.on {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--accent-ink);
}

main {
  grid-area: stage;
  min-width: 0;
  position: sticky;
  top: 1rem;
}

aside {
  grid-area: side;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-width: 0;
}

@media (max-width: 64rem) {
  .app {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: 'head' 'stage' 'side';
  }

  main {
    position: static;
  }
}
@media (max-width: 36rem) {
  .app {
    padding: 0.75rem;
  }

  header > .note {
    order: 3;
    flex-basis: 100%;
  }
}
</style>
