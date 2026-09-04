<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { Calibration, ViewMode } from '../lenticular'
import { QuiltRenderer } from '../quiltRenderer'
import type { QuiltSource } from '../composables/useQuiltSource'

const props = defineProps<{
  source: QuiltSource
  mode: ViewMode
  singleView: number
  /** 収束面のずらし（視差の画素）。再生側で効かせる */
  shift: number
  /** 視点の広がり。ずらしを視点ごとの平行移動へ写すのに要る */
  span: number
  calibration: Calibration | null
}>()

const emit = defineEmits<{ error: [message: string] }>()

const canvas = ref<HTMLCanvasElement | null>(null)
const video = ref<HTMLVideoElement | null>(null)
const image = ref<HTMLImageElement | null>(null)
const stage = ref<HTMLDivElement | null>(null)
const poppedOut = ref(false)
const sizeNote = ref<string | null>(null)
const playing = ref(false)
const position = ref(0)
const duration = ref(0)

const STAGE_HEIGHT = '72vh'

function togglePlay(): void {
  const element = video.value
  if (element === null) return
  if (element.paused) void element.play()
  else element.pause()
}

function onTimeUpdate(): void {
  const element = video.value
  if (element === null) return
  playing.value = !element.paused
  position.value = element.currentTime
  duration.value = Number.isFinite(element.duration)
    ? element.duration
    : 0
}

function onSeek(event: Event): void {
  const element = video.value
  if (element === null) return
  element.currentTime = Number(
    (event.target as HTMLInputElement).value
  )
}

function clock(seconds: number): string {
  const whole = Math.max(Math.floor(seconds), 0)
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

let renderer: QuiltRenderer | null = null
let popup: Window | null = null
let observer: ResizeObserver | null = null

function fitToStage(): void {
  if (renderer === null || poppedOut.value) return
  const box = stage.value
  if (box === null) return
  const ratio = window.devicePixelRatio
  renderer.setSize(box.clientWidth * ratio, box.clientHeight * ratio)
}

/**
 * 別窓の canvas を実画素と 1 対 1 にする。`pitch` は画面横幅あたりのレンズ本数として
 * 正規化してあるので、描画バッファが物理画素と一致していないと縞が全部ずれる。
 */
function fitToPopup(): void {
  if (popup === null || renderer === null || canvas.value === null)
    return
  const ratio = popup.devicePixelRatio
  const width = Math.round(popup.innerWidth * ratio)
  const height = Math.round(popup.innerHeight * ratio)
  // scoped CSS は元ドキュメントの head にしか入らないので、別窓では style を直に当てる
  canvas.value.style.width = `${popup.innerWidth}px`
  canvas.value.style.height = `${popup.innerHeight}px`
  renderer.setSize(width, height)
  const target = props.calibration
  sizeNote.value =
    target !== null &&
    (width !== target.screenW || height !== target.screenH)
      ? `描画バッファ ${width}x${height} が機種の ${target.screenW}x${target.screenH} と違う。窓を Looking Glass 側で全画面にする`
      : null
}

function start(): void {
  const media =
    props.source.kind === 'video' ? video.value : image.value
  if (canvas.value === null || media === null) return
  // muted は属性だけだと自動再生の判定に間に合わないことがあるので、DOM 側にも入れる
  if (video.value !== null) video.value.muted = true
  try {
    renderer = new QuiltRenderer({
      canvas: canvas.value,
      media,
      layout: props.source.layout,
      onError: message => emit('error', message),
    })
  } catch (failure) {
    emit(
      'error',
      failure instanceof Error ? failure.message : String(failure)
    )
    return
  }
  renderer.setCalibration(props.calibration)
  renderer.setMode(props.mode)
  renderer.setSingleView(props.singleView)
  renderer.setSpan(props.span)
  renderer.setShift(props.shift)
  fitToStage()
  renderer.start()
}

/**
 * canvas を別窓へ移す。Looking Glass は OS 上の別画面なので、そこへ持っていった窓を
 * 全画面にしないとレンチキュラー表示にならない。WebGL の context を保ったまま
 * 窓を移す方法は公式ポリフィルと同じ。
 *
 * `rect` は位置の希望でしかない。ブラウザは Window Management 権限が無いと
 * ポップアップを今の画面内へ丸めるので、別画面へは手で動かしてもらう
 */
function openWindow(rect: {
  x: number
  y: number
  width: number
  height: number
}): void {
  if (canvas.value === null || popup !== null) return
  const features = `popup=yes,left=${rect.x},top=${rect.y},width=${rect.width},height=${rect.height}`
  const opened = window.open('', 'lkg-quilt-studio', features)
  if (opened === null) {
    emit('error', '別窓を開けなかった。ポップアップの許可を確認する')
    return
  }
  opened.document.title = 'lkg-quilt-studio — Looking Glass'
  const style = opened.document.createElement('style')
  style.textContent =
    'html,body{margin:0;overflow:hidden;background:#000}canvas{display:block}'
  opened.document.head.append(style)
  opened.document.body.append(canvas.value)
  opened.addEventListener('pagehide', closeWindow)
  opened.addEventListener('resize', fitToPopup)
  popup = opened
  poppedOut.value = true
  renderer?.setLoopWindow(opened)
  fitToPopup()
}

function closeWindow(): void {
  if (popup === null) return
  const opened = popup
  popup = null
  poppedOut.value = false
  sizeNote.value = null
  opened.removeEventListener('resize', fitToPopup)
  renderer?.setLoopWindow(window)
  if (canvas.value !== null) {
    canvas.value.style.removeProperty('width')
    canvas.value.style.removeProperty('height')
    stage.value?.append(canvas.value)
  }
  opened.close()
  fitToStage()
}

defineExpose({ openWindow, closeWindow, poppedOut })

watch(
  () => props.mode,
  mode => renderer?.setMode(mode)
)
watch(
  () => props.singleView,
  index => renderer?.setSingleView(index)
)
watch(
  () => props.shift,
  pixels => renderer?.setShift(pixels)
)
watch(
  () => props.span,
  span => renderer?.setSpan(span)
)
watch(
  () => props.calibration,
  calibration => renderer?.setCalibration(calibration)
)
// 同じ種類のうちは要素が使い回されるので src の差し替えだけで済む。
// 動画と静止画を行き来したときは載せる要素ごと変わるので renderer を作り直す
watch(
  () => props.source,
  (source, previous) => {
    if (source.kind !== previous.kind) {
      renderer?.dispose()
      renderer = null
      void nextTick(start)
      return
    }
    renderer?.setLayout(source.layout)
  }
)

onMounted(() => {
  start()
  observer = new ResizeObserver(fitToStage)
  if (stage.value !== null) observer.observe(stage.value)
  window.addEventListener('pagehide', closeWindow)
})

onUnmounted(() => {
  window.removeEventListener('pagehide', closeWindow)
  observer?.disconnect()
  closeWindow()
  renderer?.dispose()
  renderer = null
})
</script>

<template>
  <!-- ルートは 1 つにする。複数だと親の flex の直下に並び、
       4092 px の動画が横へ張り出して画面が崩れる -->
  <div class="frame">
    <!-- 縦長のタイル（Go は 0.5625）だと幅いっぱいでは画面から溢れる。
         高さを画面に収めた上で縦横比を保つため、幅の上限を高さから逆算する -->
    <div
      class="stage"
      ref="stage"
      :style="{
        aspectRatio: String(source.layout.aspect),
        maxWidth: `calc(${STAGE_HEIGHT} * ${source.layout.aspect})`,
      }"
    >
      <canvas ref="canvas" class="surface" />
      <p v-if="poppedOut" class="moved">
        別窓へ移した。その窓を Looking Glass 側へ動かして全画面にする
      </p>
    </div>

    <p v-if="source.kind === 'video'" class="transport">
      <button type="button" @click="togglePlay">
        {{ playing ? '一時停止' : '再生' }}
      </button>
      <input
        type="range"
        min="0"
        :max="duration || 0"
        step="0.05"
        :value="position"
        @input="onSeek"
      />
      <span class="time">
        {{ clock(position) }} / {{ clock(duration) }}
      </span>
    </p>
    <p v-if="sizeNote" class="size-note">{{ sizeNote }}</p>

    <!-- 動画も静止画もテクスチャの供給元としてだけ要る。
         4092 px の生の絵を並べても読めないし、置き場所も無い -->
    <video
      v-if="source.kind === 'video'"
      ref="video"
      class="hidden"
      :src="source.url"
      :crossorigin="
        source.url.startsWith('blob:') ? undefined : 'anonymous'
      "
      autoplay
      muted
      loop
      playsinline
      @timeupdate="onTimeUpdate"
      @loadedmetadata="onTimeUpdate"
      @play="onTimeUpdate"
      @pause="onTimeUpdate"
    />
    <img v-else ref="image" class="hidden" :src="source.url" alt="" />
  </div>
</template>

<style scoped>
.stage {
  position: relative;
  width: 100%;
  margin-inline: auto;
  background: #000;
  border-radius: 6px;
  overflow: hidden;
}

.surface {
  display: block;
  width: 100%;
  height: 100%;
}

.moved {
  position: absolute;
  inset: 0;
  display: grid;
  place-content: center;
  margin: 0;
  color: #cfd8dc;
}

.size-note {
  color: #b26500;
}

.frame {
  /* 親が flex の行。空いた幅は絵に使わせるが、はみ出しは許さない
     （4092 px の動画がここに入ると画面が横へ崩れる） */
  flex: 1;
  min-width: 0;
}

.transport {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0.4rem 0 0;
}

.transport input[type='range'] {
  flex: 1;
  min-width: 4rem;
}

.time {
  color: #546e7a;
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
}

.hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}
</style>
