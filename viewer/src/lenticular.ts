// Looking Glass のレンチキュラー変換。画面のサブピクセルごとに「どの視点が見えるか」を
// 求め、quilt の該当タイルから色を拾う。
//
// 式の出典は公式ポリフィル `@lookingglass/webxr@0.6.0` の
// `dist/bundle/webxr.js` にある `Shader()` と `LookingGlassConfig` の
// `get pitch / tilt / subp`。キャリブレーション値の意味は公式ドキュメントに無く、
// この実装が唯一の出典（`.claude/rules/external-apis.md`）。

import { viewCount, type QuiltLayout } from './quilt'

/** Bridge の `getDisplays()` が返すキャリブレーションのうち、変換に使う項目。 */
export type Calibration = {
  pitch: number
  slope: number
  center: number
  DPI: number
  screenW: number
  screenH: number
  flipImageX: number
  invView: number
}

/** シェーダーに焼き込む形へ直したキャリブレーション。 */
export type LenticularParams = {
  pitch: number
  tilt: number
  center: number
  subp: number
  invertView: boolean
}

export function lenticularParams(
  calibration: Calibration
): LenticularParams {
  const flip = calibration.flipImageX ? -1 : 1
  const { screenW, screenH, slope, DPI } = calibration
  if (screenW <= 0 || screenH <= 0 || DPI <= 0 || slope === 0) {
    throw new Error(
      `キャリブレーション値が不正: screenW=${screenW} screenH=${screenH} DPI=${DPI} slope=${slope}`
    )
  }
  return {
    // 生の pitch は DPI 基準なので、画面横幅あたりのレンズ本数へ直す
    pitch:
      calibration.pitch *
      (screenW / DPI) *
      Math.cos(Math.atan(1 / slope)),
    tilt: (screenH / (screenW * slope)) * flip,
    center: calibration.center,
    // 隣のサブピクセルまでの距離。1 画素に RGB の 3 本が並ぶ
    subp: (1 / (screenW * 3)) * flip,
    invertView: calibration.invView === 1,
  }
}

/**
 * quilt のうち実際にタイルが並んでいる割合。
 *
 * タイルは整数サイズの格子に並ぶので、割り切れない解像度（4096 / 5 = 819.2）では
 * 右端と上端に余白が残る。UV でその余白を除外しないと、タイルの継ぎ目がずれる。
 * 切り捨ては converter 側（`QuiltSpec.tile_size`）と揃えている。
 */
export function viewPortion(
  layout: QuiltLayout,
  width: number,
  height: number
): { u: number; v: number } {
  if (width < layout.columns || height < layout.rows) {
    throw new Error(
      `quilt の解像度がタイル数より小さい: ${width}x${height} / ${layout.columns}x${layout.rows}`
    )
  }
  return {
    u: (layout.columns * Math.floor(width / layout.columns)) / width,
    v: (layout.rows * Math.floor(height / layout.rows)) / height,
  }
}

/** 表示の内容。`lenticular` が実機向けで、残りは通常のモニタで中身を確かめるためのもの。 */
export type ViewMode = 'lenticular' | 'single' | 'quilt'

export const VIEW_MODES: readonly ViewMode[] = [
  'lenticular',
  'single',
  'quilt',
]

export const VIEW_MODE_CODES: Record<ViewMode, number> = {
  lenticular: 0,
  single: 1,
  quilt: 2,
}

/** GLSL のリテラルへ。整数でも小数点が付く形にしないとコンパイルが通らない。 */
function glsl(value: number): string {
  return value.toPrecision(10)
}

export function fragmentShader(
  params: LenticularParams,
  layout: QuiltLayout
): string {
  const total = viewCount(layout)
  // 公式実装が入れている桁落ち対策。列数そのままで mod を取ると最終列が 0 に回る環境がある
  const columns = glsl(layout.columns - 0.00001)
  // 公式は invView を見ずに常に反転する。現行機はすべて invView=1 だが、
  // Bridge が別の値を返す機種のために分岐を残す
  const fract = params.invertView
    ? '1.0 - fract(views)'
    : 'fract(views)'
  return `precision mediump float;

uniform sampler2D quilt;
uniform vec2 viewPortion;
uniform int viewMode;
uniform float singleView;
uniform float shift;
uniform float span;

in vec2 vUv;
out vec4 fragColor;

const float pitch = ${glsl(params.pitch)};
const float tilt = ${glsl(params.tilt)};
const float center = ${glsl(params.center)};
const float subp = ${glsl(params.subp)};
const float tileCount = ${glsl(total)};
const float columns = ${columns};
const float rows = ${glsl(layout.rows)};

// 視点 0 は quilt の左下タイル。テクスチャ座標も左下が原点なので上下の読み替えは要らない
vec2 quiltUv(vec2 tileUv, float view) {
  // 上限は tileCount - 1。公式は tileCount で切っているが、それだと格子の外を指せる
  float clamped = clamp(view, 0.0, tileCount - 1.0);
  // カメラ位置。0 が左カメラ、1 が右カメラで、span で外へ広がる
  // （converter の dibr.view_positions と同じ式）
  float position = 0.5 + span * (clamped / max(tileCount - 1.0, 1.0) - 0.5);
  // 収束面を shift ずらすと、その視点の絵は shift * position だけ横へ動く
  // （converter の dibr.view() の前進ワープがそのまま平行移動になる）。
  // 拾う側は逆向きなので符号が反転する
  float offset = -shift * position;
  // タイルの外へ出ると隣の視点を掴む。端の絵が伸びるほうがまだ見られる
  float shifted = clamp(tileUv.x + offset, 0.0, 1.0);
  float column = mod(clamped, columns);
  float row = floor(clamped / columns);
  vec2 uv = vec2((column + shifted) / columns, (row + tileUv.y) / rows);
  return uv * viewPortion;
}

// R / G / B は画面上で横にずれて並ぶので、チャンネルごとに別の視点が見える
vec3 subpixelViews(vec2 uv) {
  vec3 views = vec3(uv.x) + subp * vec3(0.0, 1.0, 2.0);
  views += uv.y * tilt;
  views = views * pitch - center;
  views = ${fract};
  return clamp(views, vec3(0.00001), vec3(0.999999));
}

void main() {
  if (viewMode == 2) {
    fragColor = texture(quilt, vUv);
    return;
  }
  if (viewMode == 1) {
    fragColor = texture(quilt, quiltUv(vUv, singleView));
    return;
  }
  vec3 views = subpixelViews(vUv);
  fragColor = vec4(
    texture(quilt, quiltUv(vUv, floor(views.r * tileCount))).r,
    texture(quilt, quiltUv(vUv, floor(views.g * tileCount))).g,
    texture(quilt, quiltUv(vUv, floor(views.b * tileCount))).b,
    1.0
  );
}
`
}
