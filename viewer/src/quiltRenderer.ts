// quilt 動画を 1 枚のフルスクリーン矩形に描く。レンチキュラー変換はフラグメントシェーダー
// （lenticular.ts）に任せ、ここは three.js のリソース管理と描画ループだけを持つ。

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

// ShaderMaterial ではなく RawShaderMaterial を使う。前者は position / uv の宣言と
// フラグメントの出力変数を自動で足すので、自前のシェーダーと二重定義になる
const VERTEX_SHADER = `in vec3 position;
in vec2 uv;
out vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}
`

/** quilt を載せている要素。動画（再生）と静止画（プレビュー）の両方を受ける。 */
export type QuiltMedia = HTMLVideoElement | HTMLImageElement

export type QuiltRendererOptions = {
  canvas: HTMLCanvasElement
  media: QuiltMedia
  layout: QuiltLayout
  /** 描画ループやイベント経由で起きた失敗の受け口 */
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
  /** 収束面のずらし（タイルの画素）。焼き直さずに再生側で効かせる */
  private shiftPixels = 0
  /** 視点の広がり。ずらし量を視点ごとの平行移動へ写すのに要る */
  private span = 1.0
  private frame: number | null = null
  /** 描画ループを回すウィンドウ。別窓へ移したらそちらへ差し替える */
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
      throw new Error('WebGL2 が使えないブラウザでは表示できない')
    }
    // 静止画は VideoTexture にできない（毎フレーム更新を前提にしている）
    this.texture =
      options.media instanceof HTMLVideoElement
        ? new VideoTexture(options.media)
        : new Texture(options.media)
    // 視点 0 が左下という前提はこの反転に依存する。false にすると上下が入れ替わる
    this.texture.flipY = true
    // ミップマップを作らせない。レンチキュラー表示では隣り合う画素が別のタイルを掴むので、
    // GPU は「極端に縮小されている」と見て一番粗いミップ（1x1 = quilt 全体の平均色）を引き、
    // 画面が単色に染まる。VideoTexture は既定でミップを作らないため動画では出ず、
    // 静止画のプレビューだけで踏んだ（実機が rgb(80,103,49) の緑一色になった）
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
   * 収束面を再生側でずらす。単位は視差の画素で、converter の `--convergence` と同じ量。
   * 収束面の変更は視点ごとの平行移動と等価なので、変換をやり直さずに効かせられる
   */
  setShift(pixels: number): void {
    this.shiftPixels = pixels
    this.material.uniforms.shift.value = this.shiftFraction()
  }

  /** 視点の広がり。変換に渡す値と同じものを入れる。 */
  setSpan(span: number): void {
    this.span = span
    this.material.uniforms.span.value = span
  }

  /** 動画を差し替えたときに呼ぶ。レイアウトが変わればシェーダーを組み直す。 */
  setLayout(layout: QuiltLayout): void {
    const changed =
      layout.columns !== this.layout.columns ||
      layout.rows !== this.layout.rows
    this.layout = layout
    this.singleView = Math.min(this.singleView, viewCount(layout) - 1)
    if (changed) this.replaceMaterial()
    // 余白の割合はここで計算しない。この時点の videoWidth はまだ前の動画の値なので、
    // 新しい動画の loadedmetadata を待つ
  }

  /** キャリブレーションはシェーダーに定数として焼くので、届いたら組み直す。 */
  setCalibration(calibration: Calibration | null): void {
    this.calibration = calibration
    this.replaceMaterial()
  }

  setSize(width: number, height: number): void {
    this.renderer.setSize(width, height, false)
  }

  /** 別窓へ canvas を移したら、その窓の requestAnimationFrame に載せ替える。 */
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
    // forceContextLoss() を呼ぶとこの canvas では二度と context を取れない。
    // dispose() は canvas ごと捨てるときにしか呼ばないので、ここで解放してよい
    this.renderer.forceContextLoss()
    this.renderer.dispose()
  }

  private get kind(): 'video' | 'image' {
    return this.media instanceof HTMLVideoElement ? 'video' : 'image'
  }

  private onMediaReady(): void {
    const { width, height } = this.mediaSize
    // 読み込み前に needsUpdate を立てると three が image is incomplete で警告する
    if (width === 0 || height === 0) return
    // 静止画は毎フレーム更新されないので、読み込めた時点で明示的に上げる
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
    // イベント経由で呼ばれるので、投げても console に落ちるだけになる
    try {
      const portion = viewPortion(
        this.layout,
        videoWidth,
        videoHeight
      )
      this.portion.set(portion.u, portion.v)
      // タイルの画素数はここで初めて分かるので、画素→比の換算をやり直す
      this.material.uniforms.shift.value = this.shiftFraction()
    } catch (failure) {
      this.onError(
        failure instanceof Error ? failure.message : String(failure)
      )
    }
  }

  /** ずらし量をタイル幅に対する比へ直す。シェーダーはテクスチャ座標で動かすため。 */
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
    // キャリブレーションが無い間はレンチキュラー変換の式を作れない。single / quilt だけを
    // 見られるように、意味のない値で組んでおく
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

/** 読み込み完了を知らせるイベント名。静止画と動画で違う。 */
const READY_EVENT = {
  video: 'loadedmetadata',
  image: 'load',
} as const

/** 実機の値ではない。Bridge に繋がるまでシェーダーを組めるようにするためだけの定数。 */
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
