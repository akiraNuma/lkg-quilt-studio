<script setup lang="ts">
import { computed, ref, useTemplateRef, watch } from 'vue'
import BridgePanel from './components/BridgePanel.vue'
import QuiltStage from './components/QuiltStage.vue'
import QuiltWorkbench from './components/QuiltWorkbench.vue'
import { useBridge } from './composables/useBridge'
import { useQuiltSource } from './composables/useQuiltSource'
import { VIEW_MODES, type ViewMode } from './lenticular'
import { layoutMismatch, viewCount, type QuiltLayout } from './quilt'

const { source, error, fromFile, fromUri, fromImage } =
  useQuiltSource()
const bridge = useBridge()

const mode = ref<ViewMode>('lenticular')
const singleView = ref(0)
// 収束面のずらし（視差の画素）。焼き込んだ値を再生側で上書きする
const shift = ref(0)
// 視点の広がり。変換に渡す値で、シェーダーが視点位置を出すのにも使う
const span = ref(1.2)
const uriInput = ref('')
const selectedDisplay = ref(0)
const stageError = ref<string | null>(null)
const stage = useTemplateRef<InstanceType<typeof QuiltStage>>('stage')

const display = computed(
  () =>
    bridge.displays.value.find(
      found => found.index === selectedDisplay.value
    ) ?? null
)
const calibration = computed(() => display.value?.calibration ?? null)

// Bridge の index は 0 から始まらない。Looking Glass 以外のモニタが混ざっていると、
// 一覧から外れた分だけ番号が飛ぶ（実測で Go が index 1）。選んだ番号が一覧に無いと
// 較正値も quilt も取れないまま画面が黙るので、繋がった時点で先頭へ寄せる
watch(
  () => bridge.displays.value,
  found => {
    if (found.length === 0) return
    if (found.some(one => one.index === selectedDisplay.value)) return
    selectedDisplay.value = found[0].index
  },
  { immediate: true }
)

const mismatch = computed(() => {
  const quilt = display.value?.quilt
  if (source.value === null || !quilt) return null
  return layoutMismatch(source.value.layout, quilt)
})

const maxView = computed(() =>
  source.value === null ? 0 : viewCount(source.value.layout) - 1
)

function onSelectFile(event: Event): void {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  fromFile(file)
  resetView()
}

function onSubmitUri(): void {
  fromUri(uriInput.value)
  resetView()
}

function onPreview(
  blob: Blob,
  name: string,
  layout: QuiltLayout
): void {
  fromImage(blob, name, layout)
  // 収束面のずらしは残す。1 枚描き直すたびに 0 へ戻ると詰められない
  singleView.value = Math.floor((viewCount(layout) - 1) / 2)
  stageError.value = null
}

function onConverted(url: string): void {
  uriInput.value = url
  fromUri(url)
  resetView()
}

function resetView(): void {
  singleView.value = Math.floor(maxView.value / 2)
  shift.value = 0
  stageError.value = null
}

function moveToDisplay(): void {
  const target = display.value
  if (target?.calibration == null || target.windowCoords === null) {
    stageError.value =
      'キャリブレーションと窓の位置が取れていない。Bridge に接続して機種を選ぶ'
    return
  }
  mode.value = 'lenticular'
  stage.value?.openWindow({
    x: target.windowCoords.x,
    y: target.windowCoords.y,
    width: target.calibration.screenW,
    height: target.calibration.screenH,
  })
}

function bringBack(): void {
  stage.value?.closeWindow()
}

function castToBridge(): void {
  const uri = source.value?.castUri
  if (uri == null || source.value === null) return
  void bridge.cast(uri, source.value.layout)
}
</script>

<template>
  <main>
    <h1>lkg-quilt-studio</h1>

    <QuiltWorkbench
      v-model:span="span"
      v-model:shift="shift"
      v-model:single-view="singleView"
      :mode="mode"
      :max-view="maxView"
      :display-quilt="display?.quilt ?? null"
      @loaded="onConverted"
      @preview="onPreview"
    >
      <template #stage>
        <p v-if="source === null" class="empty">
          右で動画を選ぶと、1 枚だけ変換した絵がここに出る
        </p>
        <template v-else>
          <QuiltStage
            ref="stage"
            :source="source"
            :mode="mode"
            :single-view="singleView"
            :shift="shift"
            :span="span"
            :calibration="calibration"
            @error="stageError = $event"
          />
          <div class="beside">
            <p class="modes">
              <label v-for="option in VIEW_MODES" :key="option">
                <input
                  v-model="mode"
                  type="radio"
                  name="mode"
                  :value="option"
                />
                {{ option }}
              </label>
            </p>
            <p>
              <button :disabled="!calibration" @click="moveToDisplay">
                Looking Glass の窓へ移す
              </button>
            </p>
            <p>
              <button @click="bringBack">こちらへ戻す</button>
            </p>
            <p class="note">
              {{ source.name }} / {{ source.layout.columns }} 列 ×
              {{ source.layout.rows }} 行 / {{ maxView + 1 }} 視点
            </p>
            <p class="note">
              lenticular
              は実画素に合わせた表示なので、通常のモニタでは
              縞模様に見えるのが正しい
            </p>
            <p v-if="mismatch" class="warn">{{ mismatch }}</p>
            <p v-if="stageError" class="warn">{{ stageError }}</p>
            <p v-if="error" class="warn">{{ error }}</p>
          </div>
        </template>
      </template>
    </QuiltWorkbench>

    <details>
      <summary>できた quilt 動画を開く</summary>
      <p>
        <input type="file" accept="video/*" @change="onSelectFile" />
      </p>
      <form class="row" @submit.prevent="onSubmitUri">
        <input
          v-model="uriInput"
          type="text"
          placeholder="http(s) の URL か、Bridge から見えるファイルパス"
          size="48"
        />
        <button type="submit">読み込む</button>
      </form>
    </details>

    <BridgePanel
      :status="bridge.status.value"
      :message="bridge.message.value"
      :displays="bridge.displays.value"
      :selected="selectedDisplay"
      :cast-uri="source?.castUri ?? null"
      @connect="void bridge.connect()"
      @refresh="void bridge.refresh()"
      @disconnect="void bridge.disconnect()"
      @select="selectedDisplay = $event"
      @cast="castToBridge"
    />
  </main>
</template>

<style scoped>
main {
  max-width: 76rem;
  margin: 0 auto;
  padding: 1rem;
  font-family: system-ui, sans-serif;
}

h1 {
  font-size: 1.1rem;
  margin: 0 0 0.75rem;
}

.row {
  display: flex;
  gap: 0.75rem;
  align-items: center;
  flex-wrap: wrap;
}

.beside {
  flex: 0 1 18rem;
}

.beside p {
  margin: 0 0 0.5rem;
}

.modes {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.empty {
  display: grid;
  place-content: center;
  min-height: 20rem;
  border: 1px dashed #cfd8dc;
  border-radius: 6px;
  color: #78909c;
}

.warn {
  color: #b3261e;
}

.note {
  color: #546e7a;
  font-size: 0.8rem;
}

details {
  margin-top: 1rem;
}

summary {
  cursor: pointer;
  color: #37474f;
}
</style>
