---
paths:
  - "viewer/**/*.ts"
  - "viewer/**/*.vue"
  - "viewer/**/*.css"
---

# Playback web app (Vue 3 + Vite) coding rules

Run checks on the host:

```bash
(cd viewer && npm run check)   # format:check → typecheck → lint → build → test
(cd viewer && npm run format)  # Fix formatting
```

**`check` includes `build` because nothing else checks `<style>` syntax errors.**
Observed broken CSS passed both format:check and lint; only `vite build` failed.
Lint catches template-expression syntax errors and mismatched closing tags (`vue/no-parsing-error`).

## Follow existing patterns

- Use **`<script setup lang="ts">` and the Composition API**. Do not use the Options API.
- Type props with `defineProps<T>()` and emitted events with `defineEmits<T>()`.
- **Mark fire-and-forget asynchronous calls with `void`.**
  Lint rejects omissions (`no-floating-promises`).
- Clean up in `onUnmounted`: `requestAnimationFrame`, event listeners,
  WebGL resources, and `URL.revokeObjectURL`.
- **Do not put multiple statements in a template attribute** (`@click="a(); b()"`).
  Prettier inserts a line break and drops `;`, breaking template parsing.
  Put the operation in a `<script setup>` function and call it.

**`npm run typecheck` runs `vue-tsc -b --force`.** `tsconfig.json` uses the solution format with `files: []`,
so `vue-tsc --noEmit` checks no files at all. A green result would be meaningless.

## State ownership and layers

- **Composables own state; `App.vue` only wires components together and defines layout.**
  `composables/usePreview.ts` owns sources, conversion settings, and automatic preview rendering;
  `useConvertJob.ts` owns job progress; `useQuiltSource.ts` owns the quilt being played.
- **Keep HTTP in `src/api.ts`**, independent of Vue and throwing exceptions on failure.
  Composables turn failures into display text through `api.describe()`.
- **Panels receive each setting through its own `defineModel`.** Passing the entire settings object
  through `v-model` and writing `settings.value.layout = x` in the child mutates the parent's object
  without emitting `update:settings`, defeating v-model's contract.
  It silently breaks as soon as the parent supplies a computed or frozen object.

## Keep shared appearance in `src/styles.css`

**Do not hard-code colors in scoped CSS.** The palette lives in `:root` CSS variables.
Buttons, inputs, and sliders are styled there once. The app is dark-only (`color-scheme: dark`).

`.panel` / `.row` / `.note` / `.warn` / `.error` are global because they provide shared layout
across the app. Scoped styles should contain only layout specific to that component.

Do not give library subheadings and empty-state text the same font size and color.
Make subheadings brighter and bolder; place empty-state text in its own padded area.
Keep both the file-selection button and drag-and-drop for importing sources.

## Put UI text in `src/i18n.ts` (Japanese / English)

**Do not hard-code visible text in components.** Retrieve it with `t('key')`.
For a key containing `{name}`, substitute it with `t('key', { name })`.

- **Add keys to `ja`. `en` is typed as `Record<keyof typeof ja, string>`, so missing English entries
  fail typecheck.** This catches omissions mechanically and is why vue-i18n was not adopted.
  The design rationale is in `CLAUDE.md`.
- For keys selected by status or kind, use a `Record<Type, MessageKey>` lookup table.
  Constructing keys by string concatenation loses type checking.
- Calls from `.ts` are supported: units in `format.ts`, mismatch text in `quilt.ts`, and status in `useBridge.ts`.
- **Set the locale explicitly in tests.** The default depends on `navigator.language`, so tests comparing
  text need `beforeEach(() => setLocale('ja'))`. Otherwise they fail under a different environment language,
  as observed in this project.
- **The browser language controls `<input type="file">` appearance and text.** Since the app cannot translate it,
  open it through `input.click()` from a custom button (`SourcePanel.vue`).
- **Write text that reads as a complete sentence.** Avoid fragments such as “まだ無い” (user feedback).
  Empty lists should use **the “まだありません” form**. Replacing the text with an instruction goes too far;
  “書き出すとここに並ぶ” was rejected.
- **Do not store `t()` results in refs.** The text stays in the old language after a locale change.
  This happened with the preview's “N フレーム目” label. Derive text in a computed where it is displayed.
- Conversion API error messages arrive from the server in English and are shown as they are.
  They do not pass through `i18n.ts`, so the Japanese UI shows them in English.

## When the dev server misses file changes

**`npm run dev` started inside the agent sandbox does not receive FSEvents, so HMR goes silent.**
The symptom is an unchanged page after edits; even `touch` produces no `hmr update` in Vite's log.
Start with `VITE_USE_POLLING=1 npm run dev` to detect changes (`vite.config.ts` reads this variable).

## Sharing localhost ports with other projects (observed pitfall)

Use a dedicated, isolated Chromium profile for browser validation.
Playwright MCP's shared profile cannot launch while another session holds its lock.

**A Service Worker registered by another project survives port reuse and intercepts this app's fetch requests.**
A leftover `sw.js` on `localhost:5173` hit `/api/projects` 500 times per second, preventing previews from arriving.
This app uses no Service Worker, so `main.ts` unregisters all of them at startup.

The symptom is a slow or unresponsive API, with no cause apparent in the code.
**If API logs show repeated 404s for unfamiliar paths, suspect a Service Worker first.**
Check the Application panel in DevTools.

## Do not place a multi-root SFC inside flex layout (observed pitfall)

**Every root of a multi-root `<template>` becomes a direct child in the parent's layout.**
A Fragment adds no box. In a `display: flex` row, a 4092 px `<video>` used as a texture source
stretched the layout sideways. Use a single root element.

**Hide `<video>` / `<img>` elements used as texture sources** (reduce them to 1 px and hide them).
A visible `<video controls>` takes up space with the raw 4092² image.
Provide playback, pause, and seeking through custom buttons and sliders
(`.transport` in `QuiltStage.vue`).

## Do not use `type="number"` for numeric inputs (observed pitfall)

**`<input type="number">` silently discards full-width digits, `1,000`, and trailing whitespace,
setting `value` to an empty string.** This is easy to trigger with an IME.
**Where blank input has meaning, discarded input turns into default behavior.**
A request for 1,000 frames became “blank = to the end of the video” and started a 58,735-frame conversion.

Use `type="text"` with `inputmode="numeric"`, normalize full-width digits to ASCII, and validate explicitly.
**Reject unreadable values and show them in red**; do not silently fall back to defaults.
Before execution, describe the planned operation in a sentence so users can check it
(`parseCount` in `format.ts`, `plan` in `ExportPanel.vue`).

## Do not reuse a WebGL canvas (observed pitfall)

**A canvas where `forceContextLoss()` was called before `WebGLRenderer.dispose()` cannot acquire
another context.** Creating a new `WebGLRenderer` on the same `<canvas>` fails with
`Cannot read properties of null (reading 'precision')`, leaving the image blank.
Switching from a still preview to a converted video always exercises this path.

**Recreate the canvas itself** (`:key="source.kind"` and `restart()` in `QuiltStage.vue`).
If it has been moved to a separate window, insert the replacement canvas into that window.

## Custom shader pitfalls

- **Use `RawShaderMaterial`, not `ShaderMaterial`.** The latter injects `position` / `uv` declarations
  and the fragment output variable, creating duplicate definitions and compile failures in custom shaders.
  Console symptoms include `'uv' : redefinition` and `no valid shader program in use`.
- **Shader compile errors appear only in the console.** `npm run check`, including build, does not fail on them.
- **Do not put backticks in shader comments.** GLSL lives inside a template literal, so a backtick terminates
  the string. Prettier then reports `SyntaxError: ';' expected` on a GLSL line.
- **Disable mipmap generation for quilt textures** (`generateMipmaps = false` and `minFilter = LinearFilter`).
  In lenticular rendering, adjacent pixels sample different tiles. The GPU interprets this as extreme
  minification and selects coarse mip levels, reducing the screen to the quilt's average color.
  Measured contrast fell from a standard deviation of 48 to 9.
  **`VideoTexture` disables mipmaps by default, so this affects still previews, not videos.**

## Known WebXR polyfill pitfalls (verified on hardware)

**This section does not apply to the current implementation.** Rendering uses calibration from Bridge
and a custom shader (see the design decisions in `CLAUDE.md`). These notes are retained for a possible
switch to `@lookingglass/webxr`.

The polyfill replaces `navigator.xr`. three.js does not distinguish it from native WebXR,
so there are constraints absent from the three.js documentation.

- **Dynamically import the polyfill only when starting its display path.** It replaces `navigator.xr`,
  so an unconditional import also affects ordinary display.
- **Wait for Bridge calibration before `requestSession`.** The polyfill fetches it asynchronously.
  Opening a session before it arrives locks the canvas at the default resolution:
  the first attempt is distorted, while subsequent attempts work.
- **Call `isSessionSupported()` once before `requestSession`.** This polyfill-specific requirement otherwise
  produces "Must call navigator.xr.isSessionSupported()...".
- **Set `optionalFeatures: ['local-floor']`.** three.js defaults to the `local-floor` reference space,
  but it is not enabled in the session unless requested, causing `NotSupportedError`.
- **Hide `window.XRWebGLBinding` only during `renderer.xr.setSession()`.** Its presence makes three.js
  take the XRProjectionLayer path, but the polyfill's XRSession cannot be passed to native `XRWebGLBinding`.
  The polyfill replaces only `XRWebGLLayer`.
- **Restore the app's camera after XR ends.** three.js changes camera position and fov during XR
  but does not restore them afterward.
- **Wait one frame after XR ends before restoring the canvas size.** The shutdown path leaves it at quilt resolution.
- **Polyfill settings (the bottom-right panel and dragging inside the window) change without passing
  through app state.** Listen for `on-config-changed` and copy them back into app state, or the UI retains stale values.

## Tests (Vitest)

- Test pure logic: quilt tile-coordinate calculations, video metadata interpretation, and argument validation.
- Do not test WebGL / WebXR rendering paths automatically. Verify them on hardware.
