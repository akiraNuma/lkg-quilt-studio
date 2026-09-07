// Draws the quilt video onto a single full-screen quad. The lenticular conversion lives in the
// fragment shader (lenticular.ts); this file holds only three.js resource management and the
// render loop.

import {
  GLSL3,
  LinearFilter,
  Mesh,
  OrthographicCamera,
  PlaneGeometry,
  RawShaderMaterial,
  Scene,
  Texture,
  Vector2,
  VideoTexture,
  WebGLRenderer,
} from 'three'
import {
  fragmentShader,
  lenticularParams,
  viewPortion,
  VIEW_MODE_CODES,
  type Calibration,
  type ViewMode,
} from './lenticular'
import { viewCount, type QuiltLayout } from './quilt'
import { t } from './i18n'

// RawShaderMaterial rather than ShaderMaterial: the latter injects declarations for position /
// uv and the fragment output variable, duplicating definitions in our own shader
const VERTEX_SHADER = `in vec3 position;
in vec2 uv;
out vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}
`

/** The element carrying the quilt: either a video (playback) or an image (preview). */
export type QuiltMedia = HTMLVideoElement | HTMLImageElement

export type QuiltRendererOptions = {
  canvas: HTMLCanvasElement
  media: QuiltMedia
  layout: QuiltLayout
  /** Where failures raised by the render loop or events are reported */
  onError?: (message: string) => void
}

export class QuiltRenderer {
  private readonly renderer: WebGLRenderer
  private readonly scene = new Scene()
  private readonly camera = new OrthographicCamera()
  private readonly geometry = new PlaneGeometry(2, 2)
  private readonly texture: Texture
  private readonly media: QuiltMedia
  private readonly portion = new Vector2(1, 1)
  private readonly onReady = () => this.onMediaReady()
  private readonly onError: (message: string) => void
  private layout: QuiltLayout
  private material: RawShaderMaterial
  private mesh: Mesh
  private calibration: Calibration | null = null
  private mode: ViewMode = 'quilt'
  private singleView: number
  /** Convergence offset in tile pixels, applied during playback without re-rendering */
  private shiftPixels = 0
  /** The view span, needed to map the offset onto a per-view translation */
  private span = 1.0
  private frame: number | null = null
  /** The window driving the render loop, swapped when the canvas moves to a separate window */
  private loopWindow: Window = window

  constructor(options: QuiltRendererOptions) {
    this.layout = options.layout
    this.media = options.media
    this.onError = options.onError ?? (() => {})
    this.singleView = Math.floor(viewCount(options.layout) / 2)
    this.renderer = new WebGLRenderer({
      canvas: options.canvas,
      antialias: false,
    })
    if (!this.renderer.capabilities.isWebGL2) {
      throw new Error(t('stage.noWebgl'))
    }
    // A still image cannot be a VideoTexture, which assumes an update every frame
    this.texture =
      options.media instanceof HTMLVideoElement
        ? new VideoTexture(options.media)
        : new Texture(options.media)
    // The assumption that view 0 is bottom-left depends on this flip; false swaps top and bottom
    this.texture.flipY = true
    // Do not generate mipmaps. In lenticular display, adjacent pixels grab different tiles, so
    // the GPU reads it as extreme minification, picks the coarsest mip (1x1, the quilt's average
    // colour), and floods the screen with one colour. VideoTexture disables mipmaps by default,
    // so videos escape it; only the still preview hit this (the hardware turned a flat
    // rgb(80,103,49) green)
    this.texture.generateMipmaps = false
    this.texture.minFilter = LinearFilter
    this.material = this.buildMaterial()
    this.mesh = new Mesh(this.geometry, this.material)
    this.scene.add(this.mesh)
    this.media.addEventListener(READY_EVENT[this.kind], this.onReady)
    this.onMediaReady()
  }

  setMode(mode: ViewMode): void {
    this.mode = mode
    this.material.uniforms.viewMode.value = VIEW_MODE_CODES[mode]
  }

  setSingleView(index: number): void {
    this.singleView = index
    this.material.uniforms.singleView.value = index
  }

  /**
   * Shift convergence during playback, in disparity pixels, the same quantity as the converter's
   * `--convergence`. A convergence change is equivalent to a per-view translation, so it applies
   * without redoing the conversion
   */
  setShift(pixels: number): void {
    this.shiftPixels = pixels
    this.material.uniforms.shift.value = this.shiftFraction()
  }

  /** The view span. Pass the same value given to the conversion. */
  setSpan(span: number): void {
    this.span = span
    this.material.uniforms.span.value = span
  }

  /** Call after swapping the video. A changed layout rebuilds the shader. */
  setLayout(layout: QuiltLayout): void {
    const changed =
      layout.columns !== this.layout.columns ||
      layout.rows !== this.layout.rows
    this.layout = layout
    this.singleView = Math.min(this.singleView, viewCount(layout) - 1)
    if (changed) this.replaceMaterial()
    // The padding fraction is not computed here: videoWidth still holds the previous video's
    // value at this point, so wait for the new video's loadedmetadata
  }

  /** Calibration is baked into the shader as constants, so rebuild once it arrives. */
  setCalibration(calibration: Calibration | null): void {
    this.calibration = calibration
    this.replaceMaterial()
  }

  setSize(width: number, height: number): void {
    this.renderer.setSize(width, height, false)
  }

  /** After moving the canvas to a separate window, switch to that window's requestAnimationFrame. */
  setLoopWindow(target: Window): void {
    if (target === this.loopWindow) return
    const running = this.frame !== null
    this.stop()
    this.loopWindow = target
    if (running) this.start()
  }

  start(): void {
    if (this.frame !== null) return
    const loop = () => {
      this.frame = this.loopWindow.requestAnimationFrame(loop)
      this.renderer.render(this.scene, this.camera)
    }
    this.frame = this.loopWindow.requestAnimationFrame(loop)
  }

  stop(): void {
    if (this.frame === null) return
    this.loopWindow.cancelAnimationFrame(this.frame)
    this.frame = null
  }

  dispose(): void {
    this.stop()
    this.media.removeEventListener(
      READY_EVENT[this.kind],
      this.onReady
    )
    this.scene.remove(this.mesh)
    this.geometry.dispose()
    this.material.dispose()
    this.texture.dispose()
    // Once forceContextLoss() is called, this canvas can never acquire a context again.
    // dispose() runs only when the canvas itself is discarded, so releasing here is safe
    this.renderer.forceContextLoss()
    this.renderer.dispose()
  }

  private get kind(): 'video' | 'image' {
    return this.media instanceof HTMLVideoElement ? 'video' : 'image'
  }

  private onMediaReady(): void {
    const { width, height } = this.mediaSize
    // Setting needsUpdate before loading makes three warn that the image is incomplete
    if (width === 0 || height === 0) return
    // A still image is not updated every frame, so raise the flag explicitly once it loads
    if (!(this.media instanceof HTMLVideoElement)) {
      this.texture.needsUpdate = true
    }
    this.refreshViewPortion()
  }

  private get mediaSize(): { width: number; height: number } {
    return this.media instanceof HTMLVideoElement
      ? {
          width: this.media.videoWidth,
          height: this.media.videoHeight,
        }
      : {
          width: this.media.naturalWidth,
          height: this.media.naturalHeight,
        }
  }

  private refreshViewPortion(): void {
    const { width: videoWidth, height: videoHeight } = this.mediaSize
    if (videoWidth === 0 || videoHeight === 0) return
    // Called from an event, so throwing would only land in the console
    try {
      const portion = viewPortion(
        this.layout,
        videoWidth,
        videoHeight
      )
      this.portion.set(portion.u, portion.v)
      // The tile's pixel size is known only now, so redo the pixel-to-ratio conversion
      this.material.uniforms.shift.value = this.shiftFraction()
    } catch (failure) {
      this.onError(
        failure instanceof Error ? failure.message : String(failure)
      )
    }
  }

  /** Convert the offset to a fraction of tile width, since the shader moves in texture space. */
  private shiftFraction(): number {
    const tileWidth = this.mediaSize.width / this.layout.columns
    return tileWidth > 0 ? this.shiftPixels / tileWidth : 0
  }

  private replaceMaterial(): void {
    const rebuilt = this.buildMaterial()
    this.mesh.material = rebuilt
    this.material.dispose()
    this.material = rebuilt
  }

  private buildMaterial(): RawShaderMaterial {
    // Without calibration the lenticular formula cannot be built. Build it from meaningless
    // values so single / quilt remain viewable
    const params = lenticularParams(this.calibration ?? UNCALIBRATED)
    return new RawShaderMaterial({
      glslVersion: GLSL3,
      vertexShader: VERTEX_SHADER,
      fragmentShader: fragmentShader(params, this.layout),
      uniforms: {
        quilt: { value: this.texture },
        viewPortion: { value: this.portion },
        viewMode: { value: VIEW_MODE_CODES[this.mode] },
        singleView: { value: this.singleView },
        shift: { value: this.shiftFraction() },
        span: { value: this.span },
      },
    })
  }
}

/** The event name signalling load completion, which differs for images and videos. */
const READY_EVENT = {
  video: 'loadedmetadata',
  image: 'load',
} as const

/** Not hardware values. Constants that merely let the shader build before Bridge connects. */
const UNCALIBRATED: Calibration = {
  pitch: 50,
  slope: -7,
  center: 0,
  DPI: 300,
  screenW: 1536,
  screenH: 2048,
  flipImageX: 0,
  invView: 1,
}
