// Looking Glass lenticular conversion. For each subpixel on screen it works out which view is
// visible there, then samples the colour from the matching quilt tile.
//
// The formulas come from `Shader()` and `LookingGlassConfig`'s `get pitch / tilt / subp` in
// `dist/bundle/webxr.js` of the official polyfill `@lookingglass/webxr@0.6.0`. The meaning of the
// calibration values is absent from the official documentation, and that implementation is the
// only source (`.claude/rules/external-apis.md`).

import { viewCount, type QuiltLayout } from './quilt'

/** The calibration fields this conversion needs from Bridge's `getDisplays()`. */
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

/** Calibration reshaped into the form baked into the shader. */
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
    // Raw pitch is relative to DPI, so convert it to lenses across the screen width
    pitch:
      calibration.pitch *
      (screenW / DPI) *
      Math.cos(Math.atan(1 / slope)),
    tilt: (screenH / (screenW * slope)) * flip,
    center: calibration.center,
    // Distance to the neighbouring subpixel: one pixel holds three of them (RGB)
    subp: (1 / (screenW * 3)) * flip,
    invertView: calibration.invView === 1,
  }
}

/**
 * The fraction of the quilt actually covered by tiles.
 *
 * Tiles sit on an integer-sized grid, so a resolution that does not divide evenly
 * (4096 / 5 = 819.2) leaves padding at the right and top edges. Without excluding that padding
 * through UVs, tile seams shift. The rounding down matches the converter (`QuiltSpec.tile_size`).
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

/** What to display. `lenticular` targets the hardware; the rest inspect the content on an
 * ordinary monitor.
 */
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

/** To a GLSL literal. Even integers need a decimal point or compilation fails. */
function glsl(value: number): string {
  return value.toPrecision(10)
}

export function fragmentShader(
  params: LenticularParams,
  layout: QuiltLayout
): string {
  const total = viewCount(layout)
  // The precision guard the official implementation carries: taking mod with the column count
  // as is wraps the last column to 0 on some devices
  const columns = glsl(layout.columns - 0.00001)
  // The official code always inverts without checking invView. Every current model reports
  // invView=1, but the branch stays for a model where Bridge returns something else
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

// View 0 is the quilt's bottom-left tile, and texture coordinates also start at the bottom
// left, so no vertical flip is needed
vec2 quiltUv(vec2 tileUv, float view) {
  // The ceiling is tileCount - 1. The official code clamps at tileCount, which can point
  // outside the grid
  float clamped = clamp(view, 0.0, tileCount - 1.0);
  // Camera position: 0 is the left camera, 1 the right, widened outwards by span
  // (the same formula as the converter's dibr.view_positions)
  float position = 0.5 + span * (clamped / max(tileCount - 1.0, 1.0) - 0.5);
  // Moving convergence by shift moves that view's image sideways by shift * position (the
  // forward warp in the converter's dibr.view() becomes a plain translation). Sampling runs the
  // other way, so the sign flips
  float offset = -shift * position;
  // Straying outside a tile would grab the neighbouring view; stretching the edge looks better
  float shifted = clamp(tileUv.x + offset, 0.0, 1.0);
  float column = mod(clamped, columns);
  float row = floor(clamped / columns);
  vec2 uv = vec2((column + shifted) / columns, (row + tileUv.y) / rows);
  return uv * viewPortion;
}

// R / G / B sit side by side on screen, so each channel sees a different view
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
