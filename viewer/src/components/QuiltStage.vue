<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { Calibration, ViewMode } from '../lenticular'
import { clock } from '../format'
import { t } from '../i18n'
import { QuiltRenderer } from '../quiltRenderer'
import type { QuiltSource } from '../composables/useQuiltSource'

const props = defineProps<{
  source: QuiltSource
  mode: ViewMode
  singleView: number
  /** Convergence offset in disparity pixels, applied during playback */
  shift: number
  /** The view span, needed to map the offset onto a per-view translation */
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
const volume = ref(1)
const muted = ref(true)

const STAGE_HEIGHT = '72vh'

function onVolumeChange(): void {
  if (video.value === null) return
  volume.value = video.value.volume
  muted.value = video.value.muted
}

function setVolume(event: Event): void {
  const element = video.value
  if (element === null) return
  element.volume =
    Number((event.target as HTMLInputElement).value) / 100
  element.muted = element.volume === 0
  onVolumeChange()
}

function toggleMute(): void {
  const element = video.value
  if (element === null) return
  if (element.muted || element.volume === 0) {
    if (element.volume === 0) element.volume = 1
    element.muted = false
  } else element.muted = true
  onVolumeChange()
}

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
 * Map the separate window's canvas one-to-one to physical pixels. `pitch` is normalised as lenses
 * across the screen width, so every stripe shifts unless the drawing buffer matches the physical
 * pixels.
 */
function fitToPopup(): void {
  if (popup === null || renderer === null || canvas.value === null)
    return
  const ratio = popup.devicePixelRatio
  const width = Math.round(popup.innerWidth * ratio)
  const height = Math.round(popup.innerHeight * ratio)
  // Scoped CSS only reaches the original document's head, so style is applied inline in the
  // separate window
  canvas.value.style.width = `${popup.innerWidth}px`
  canvas.value.style.height = `${popup.innerHeight}px`
  renderer.setSize(width, height)
  const target = props.calibration
  sizeNote.value =
    target !== null &&
    (width !== target.screenW || height !== target.screenH)
      ? t('stage.sizeNote', {
          actual: `${width}x${height}`,
          expected: `${target.screenW}x${target.screenH}`,
        })
      : null
}

function start(): void {
  const media =
    props.source.kind === 'video' ? video.value : image.value
  if (canvas.value === null || media === null) return
  // The muted attribute alone can arrive too late for the autoplay decision, so set it on the
  // DOM as well
  if (video.value !== null) {
    video.value.volume = volume.value
    video.value.muted = muted.value
  }
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
  // Even when rebuilt while moved to the separate window, the render loop runs in that window.
  // Once the original is hidden its rAF stops and the Looking Glass freezes on the last frame
  renderer.setLoopWindow(popup ?? window)
  renderer.setCalibration(props.calibration)
  renderer.setMode(props.mode)
  renderer.setSingleView(props.singleView)
  renderer.setSpan(props.span)
  renderer.setShift(props.shift)
  fitToStage()
  renderer.start()
}

/**
 * Move the canvas to a separate window. The Looking Glass is a separate OS display, so the window
 * taken there must be full screen for lenticular display to work. Moving the window while keeping
 * the WebGL context is done the same way as in the official polyfill.
 *
 * `rect` is only a hint: without Window Management permission the browser confines a popup to the
 * current screen, so a person drags it onto the other display. Full screen needs a user gesture
 * inside that window, so a double-click toggles it
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
    emit('error', t('stage.popupBlocked'))
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
  opened.addEventListener('dblclick', toggleFullscreen)
  popup = opened
  poppedOut.value = true
  renderer?.setLoopWindow(opened)
  fitToPopup()
}

/**
 * Toggle the separate window in and out of full screen. `requestFullscreen()` demands a user
 * gesture inside that window, so a button in the original window cannot call it; a double-click
 * inside the window does
 */
function toggleFullscreen(): void {
  const opened = popup
  if (opened === null) return
  if (opened.document.fullscreenElement === null) {
    void opened.document.documentElement.requestFullscreen()
  } else {
    void opened.document.exitFullscreen()
  }
}

function closeWindow(): void {
  if (popup === null) return
  const opened = popup
  popup = null
  poppedOut.value = false
  sizeNote.value = null
  opened.removeEventListener('resize', fitToPopup)
  opened.removeEventListener('dblclick', toggleFullscreen)
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
// Within one kind the element is reused, so swapping src is enough. Moving between video and
// image changes the element itself, so the renderer is rebuilt
watch(
  () => props.source,
  (source, previous) => {
    if (source.kind !== previous.kind) {
      void restart()
      return
    }
    renderer?.setLayout(source.layout)
  }
)

/**
 * Redraw when moving between video and image, **rebuilding the canvas itself** (`:key` in the
 * template). `dispose()` calls `forceContextLoss()`, after which the same canvas can never
 * acquire a WebGL context again (the symptoms are three.js's
 * `Cannot read properties of null (reading 'precision')` and a blank picture). Going from a
 * preview to playing the converted result always takes this path.
 */
async function restart(): Promise<void> {
  renderer?.dispose()
  renderer = null
  await nextTick()
  // While moved to the separate window, the rebuilt canvas is inserted there as well
  if (popup !== null && canvas.value !== null) {
    popup.document.body.append(canvas.value)
  }
  start()
  if (popup !== null) fitToPopup()
}

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
  <!-- Keep a single root. Several roots become direct children of the parent's flex layout, and
       the 4092 px video stretches sideways and breaks the layout -->
  <!-- A portrait tile (0.5625 on the Go) overflows the screen at full width. To keep the aspect
       ratio while fitting the height, the maximum width is derived from the height. The playback
       controls follow the picture's width -->
  <div
    class="frame"
    :style="{
      maxWidth: `calc(${STAGE_HEIGHT} * ${source.layout.aspect})`,
    }"
  >
    <div
      class="stage"
      ref="stage"
      :style="{ aspectRatio: String(source.layout.aspect) }"
    >
      <canvas :key="source.kind" ref="canvas" class="surface" />
      <p v-if="poppedOut" class="moved">
        {{ t('stage.moved') }}
      </p>
    </div>

    <p v-if="source.kind === 'video'" class="transport">
      <button type="button" @click="togglePlay">
        {{ playing ? t('stage.pause') : t('stage.play') }}
      </button>
      <input
        type="range"
        :aria-label="t('stage.seek')"
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
    <p v-if="source.kind === 'video'" class="audio-controls">
      <button type="button" @click="toggleMute">
        {{
          muted || volume === 0 ? t('stage.unmute') : t('stage.mute')
        }}
      </button>
      <label>
        {{ t('stage.volume') }}
        <input
          type="range"
          min="0"
          max="100"
          step="1"
          :value="muted ? 0 : volume * 100"
          @input="setVolume"
        />
      </label>
      <span class="time"
        >{{ muted ? 0 : Math.round(volume * 100) }}%</span
      >
    </p>
    <p v-if="sizeNote" class="size-note">{{ sizeNote }}</p>

    <!-- Both the video and the image exist only as texture sources. Showing the raw 4092 px
         picture would be illegible and there is nowhere to put it -->
    <video
      v-if="source.kind === 'video'"
      ref="video"
      class="hidden"
      :src="source.url"
      :crossorigin="
        source.url.startsWith('blob:') ? undefined : 'anonymous'
      "
      autoplay
      :muted="muted"
      :volume="volume"
      loop
      playsinline
      @timeupdate="onTimeUpdate"
      @loadedmetadata="onTimeUpdate"
      @play="onTimeUpdate"
      @pause="onTimeUpdate"
      @volumechange="onVolumeChange"
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
  border-radius: var(--radius);
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
  color: var(--muted);
}

.size-note {
  color: var(--warn);
  font-size: 0.8rem;
  margin: 0.4rem 0 0;
}

.frame {
  /* The width follows the picture's aspect ratio. Overflow is not allowed
     (a 4092 px video here would break the layout sideways) */
  width: 100%;
  min-width: 0;
  margin-inline: auto;
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
  color: var(--muted);
  font-size: 0.8rem;
  font-variant-numeric: tabular-nums;
}

.audio-controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin: 0.5rem 0 0;
}

.audio-controls label {
  flex: 1;
  font-size: 0.8rem;
}

.audio-controls input {
  width: 5rem;
  min-width: 0;
  flex: 1;
}

.hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}
</style>
