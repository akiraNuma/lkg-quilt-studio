# CLAUDE.md

This English document is authoritative. [README.ja.md](README.ja.md) is the only translated document.

## Project overview

Convert stereo video (two views, left and right) into **quilt video** for Looking Glass and play it in a browser.
Conversion runs as an offline rendering batch.

Pipeline:

1. Estimate disparity (depth) from stereo video.
2. Synthesize intermediate and extrapolated views using depth (DIBR: Depth Image Based Rendering).
3. Arrange the synthesized views into a quilt and encode it as video.
4. Display the quilt video on a Looking Glass through the browser.

[README.md](README.md) is the source of truth for setup and usage.

## Structure

| Directory | Responsibility | Stack |
| --- | --- | --- |
| `converter/` | Conversion (steps 1–3), with CLI and HTTP API entry points | Python + uv, FastAPI |
| `viewer/` | Playback web app (step 4) and conversion requests | Vue 3 + Vite |

`.mise.toml` is the source of truth for node and uv versions. **uv manages Python itself**
(see `.claude/rules/converter-python.md` for the reason).

There are two execution paths: `compose.yaml` defines Docker execution; `.mise.toml` defines local execution.
**Docker images are for running the application and contain no lint or test tools.**
Run the validation workflow below through the local path.

## Working principles

- Write code for human readers. Improve readability in files you touch within the same task:
  organize structure, split modules naturally, and improve names. Do the work instead of only suggesting it.
  Preserve behavior; discuss large rewrites that spread into untouched files beforehand.
- When a specification is unclear, compare the existing implementation with official documentation instead of guessing.
- **Commit and push only when explicitly instructed.** A request to fix something authorizes file edits only.
- **This is a public repository. Do not add generated footers, signatures, or session URLs to commit messages.**
  They become public history and require rewriting history to remove later.

## Validation after code edits

**Run computational checks (formatting, types, lint, build, tests) first. Run `/review-loop` (LLM review) only after they pass.**

```bash
scripts/check-harness.sh          # scripts/ format, lint, and types, then harness sync and hook input
(cd converter && uv run poe check)   # ruff format --check → ruff check → mypy → pytest
(cd viewer && npm run check)         # format:check → typecheck → lint → build → test
```

To validate everything, run `scripts/check.sh` from the repository root.
For harness-only changes, run `scripts/check-harness.sh` and check the affected references.
See “Shared Codex harness” in README.md for the Codex entry point, shared configuration sync, and initial trust setup.

Run computational checks outside containers. Neither image in `compose.yaml` includes development dependencies.

**Computational checks do not cover WebGL / WebXR rendering.** Shader compilation errors appear only in the
browser console. After changing rendering in `viewer`, open the development server and check the console.

**Computational checks cannot verify the Looking Glass display.** Check conversion output and playback on real hardware
(see “Validate on hardware” in README.md).

## Verify external references (important)

**Do not implement quilt layout conventions, calibration retrieval, or depth-model inputs and outputs from memory or guesses.**
Inspect the official documentation, paper, or reference implementation before implementing them.
`.claude/rules/external-apis.md` is the source of truth for reference URLs and known limitations.

## Design decisions (WHY)

- **Render conversions offline:** depth estimation and view synthesis are expensive. Pre-rendering removes that
  work from playback and lets us spend more computation on quality than real-time conversion would allow.
- **Use stereo matching instead of monocular depth estimation:** two input views let us derive depth directly
  from disparity without scale ambiguity. Depth variation between video frames appears as flicker, so temporal
  consistency takes priority.
- **Bake views into a quilt before playback:** playback only needs to distribute quilt tiles to their respective
  viewing directions, avoiding multi-view rendering in three.js on every frame.
- **Separate Python conversion from web playback:** the depth-model ecosystem centers on PyTorch, while browser
  display on Looking Glass requires WebGL / WebXR. Forcing both into one language makes one side unnecessarily difficult.
- **Get calibration from Bridge and render with our own lenticular shader:** the pre-rendered quilt can be used
  directly as a texture. Calibration from `getDisplays()` (pitch / slope / center / DPI / screen resolution)
  determines each subpixel's view (`viewer/src/lenticular.ts`). Looking Glass is a separate OS display, so move
  the canvas into a separate window and map it one-to-one to physical pixels. Full screen requires a user
  gesture **inside that window**, so a double-click there toggles it (`toggleFullscreen` in `QuiltStage.vue`).
  We do not use the `@lookingglass/webxr` polyfill because it targets rendering a 3D scene from multiple
  views on every frame.
- **Show on the device through our own window only, not by casting to Bridge:** an earlier `QuiltHologram`
  cast path handed a URI to Bridge's player. It was removed after it failed to play on hardware. It also
  could not show a preview at all, because **Bridge runs in a separate process and cannot read blob URLs**,
  so it required an exported file behind an http(s) URL or a local path. Keeping both meant two controls in
  two panels for one job, and a second axis in `QuiltSource` (where the file lives) on top of the one that
  matters (still preview or video).
- **Match device presets to values returned by Bridge on actual hardware:** `defaultQuilt` from
  `available_output_devices` (`tileX` / `tileY` / `quiltX` / `quiltY` / `quiltAspect`) is the only accurate source.
  The `@lookingglass/webxr` polyfill also has a device table, but its resolutions differ from actual hardware.
  See `.claude/rules/external-apis.md` for querying instructions.
  **Go is portrait: 11 columns × 6 rows / 4092² / aspect 0.5625.**
- **Default the browser device to `go`** (the available physical device is a Go): making users select a device every time
  has a greater cost than providing a default; without Bridge running, they could otherwise render no preview.
  Two safeguards prevent device mismatches: a Bridge connection automatically replaces the preset from
  `defaultQuilt` (`detected` in `usePreview.ts`), and a mismatch with the connected device produces a warning
  (`warning` in `SourcePanel.vue`). **Conversion succeeds even with the wrong device layout**, so the problem
  only becomes visible on real hardware (observed with a 5x9 quilt displayed on an 11x6 Go).
- **Preview and export do not require Bridge:** Bridge is only needed to fill in the device automatically
  and to place the separate window on the physical display. Conversion works once a device is selected
  (`ready` in `usePreview.ts` checks only the source and device). Lenticular rendering also works while
  disconnected, but uses dummy calibration, so its stripes do not align with the physical display.
- **Crop to fit mismatched aspect ratios (`--fit crop` by default):** Go and Portrait tiles are portrait-shaped
  and do not match landscape sources. Enlarging the crop to fill the display scales disparity by the same factor,
  producing stronger depth than padding (measured: 5 px → 15 px). This choice was made by comparing both on hardware.
  `pad` remains available, but padding is added **after disparity estimation**. Black padding is identical in both
  eyes, so stereo matching cannot determine its disparity and even the automatic convergence plane (median disparity)
  becomes incorrect (`fit_content` / `pad_to_tile` in `stereo.py`).
- **Search both positive and negative disparity (`min_disparity` defaults to a negative value):** valid input can contain negative `x_left - x_right` values. With SGBM's `minDisparity=0`,
  those correspondences fall outside the search range and depth is lost. Output convergence is applied separately
  in `dibr.py`; do not infer the side of the output screen from the raw disparity sign.
- **Images alone cannot determine whether the eyes are swapped:** a swapped pair is a valid stereo pair for a scene
  with reversed depth. A detector based on failure to explain a pair with positive disparity does not work when
  searching both signs; it also falsely identified valid sources whose scenes appeared behind the screen.
  A person must judge the eye order on real hardware.
- **Rectify fisheye (VR180) footage to a plane before estimating disparity:** stereo matching searches horizontally
  under the assumption that corresponding points share a row. Fisheye introduces vertical offsets farther from the
  center, breaking matching and blurring the result. The black border outside the circle would also enter the quilt
  (measured: 22.9% of a tile, reduced to 0.0% after rectification). Measure the circle center **per eye**, so differences
  in optical axes do not remain (measured vertical offset: 1.0 px).
  **Derive the radius from the widest row and tallest column; do not use a least-squares circle fit (Kåsa method).**
  The measured source outline was taller than a true circle, and circle fitting inflated its radius from 437 px to
  469 px. Accommodate differences between sources with field of view (`--fov`), judged on hardware (`fisheye.py`).
- **Parallelize view synthesis across views:** a measured frame took 31 ms for disparity, 1602 ms for view synthesis
  (66 views), and 11 ms for quilt assembly: **95% was view synthesis**. Views are independent. Threads suffice because
  cv2 and numpy release the GIL; measured frame time fell from 1.66 s to 0.46 s. Do not parallelize across frames,
  because temporal smoothing depends on the previous frame.
- **Default to stereo matching (SGBM + WLS filtering):** it requires no model-weight downloads and runs immediately
  on the host CPU. Only the `DisparityEstimator` interface in `converter/src/lkg_quilt_converter/disparity.py` is fixed,
  so a temporally consistent deep model can replace it (candidates are in `.claude/rules/external-apis.md`).
  **Disparity is fundamentally indeterminate on textureless surfaces**, so untextured subjects can collapse into
  the background in depth.
- **Apply temporal smoothing only to pixels with small changes:** a plain exponential moving average leaves trails
  behind moving subjects. Pixels whose difference from the previous frame exceeds the threshold are not smoothed
  (`blend_temporal`).
- **Determine convergence (the zero-disparity plane) on the first frame and keep it fixed:** recomputing it every
  frame makes the whole scene drift forward and backward. `--convergence` also allows an explicit value.
- **Read quilt layout from the filename convention:** avoid maintaining columns, rows, and aspect ratio separately
  in conversion and playback. `<stem>_qs<columns>x<rows>a<aspect>.mp4` is the official convention; the viewer reads
  it to determine layout (`converter/src/lkg_quilt_converter/quilt.py` and `viewer/src/quilt.ts`).
- **Make Docker the default execution path:** conversion can be tried without installing ffmpeg, Python, or node
  on the machine. **Looking Glass Bridge and the physical display remain on the host**, so the viewer's development
  server runs in a container while the browser runs on the host; physical display does not happen entirely inside
  containers. `out/` is mounted into the development server's `public/` so exported quilts are reachable at
  an http URL, which is what the library's playback loads.
- **Adjust convergence during playback and bake in that exact value:** moving convergence by Δ shifts the image
  of a view at `position` horizontally by `position × Δ` pixels (the forward warp in `dibr.py`'s `view()` becomes a
  translation). Measurements agree: at span 1.2 / Δ=20, view 65 moved 22.00 px in theory, 22.00 px in conversion,
  and 21.93 px in the shader; all five tested views had residuals at most 0.13 px. The shader therefore calculates
  view positions with the same formula as `dibr.view_positions` (`quiltUv` in `lenticular.ts`). Export **bakes the
  hardware-adjusted convergence as an absolute value**. Leaving it `auto` would recompute it on the first video frame
  and differ from the preview. **Changing `span` (depth strength) requires a new render because it creates different views.**
- **Arrange four panels in workflow order (display → source → adjustment → export):** a device must be selected
  before anything can render, so Bridge connection belongs at the start. Keep the image on the left and numbered
  controls in the right column (the `App.vue` layout and each `*Panel.vue`).
- **Re-render automatically instead of requiring a button:** otherwise users can adjust a stale image and discover
  the mismatch only on hardware. Wait 400 ms after a setting changes, then render one frame; if settings change during
  rendering, run again (`renderKey` / `run` in `usePreview.ts`). Do not submit while dragging (a frame takes 2 seconds
  in the observed case). Show “描き直している…” over the image while re-rendering.
- **Keep UI text in `viewer/src/i18n.ts` and support Japanese and English:** the small custom implementation makes
  **missing English strings fail type checking** (`en` is declared as `Record<keyof typeof ja, string>`).
  No vue-i18n features were needed. Conventions are in `.claude/rules/viewer-vue.md`.
- **Always pair sliders with numeric inputs (`ValueSlider.vue`):** dragging alone cannot enter finer values than
  the slider step or reproduce values tuned on hardware. Accept input **only when committed**, and clamp out-of-range
  values to the limits; otherwise the image and slider position disagree. Reject unparseable values and mark them red
  (see `.claude/rules/viewer-vue.md` for why we avoid `type="number"`).
- **Show the components of baked convergence:** “baked value -2.25 px” alone does not explain the number. Display it
  as **automatic convergence plus the manual adjustment** (`baked` in `TunePanel.vue`).
- **Let users list and delete files left in `out/` through the UI (`LibraryPanel.vue`):** a source can be hundreds of
  MB and a quilt video more than 40 MB. Users need to see and remove accumulated files. **Do not delete a source while
  it is being converted**, as that would interrupt reading; check `JobStore.uses_source` and return 409. “Use” on a
  source returns to adjustment without uploading it again.
- **Show explanatory messages only for abnormal states:** routine confirmations such as “matches the connected
  device” bury warnings that need attention. Show one line only when settings disagree with detection
  (`warning` in `SourcePanel.vue`).
- **Tune parameters on one frame before rendering the full video:** full conversion can take 200 times as long
  (Go / crop: 1.2 seconds per preview frame, about 4 minutes for a 6-second video). Preview uses the same
  `pipeline.preview_frame()` as conversion, so **what users see matches the baked result**. Reimplementing DIBR in
  the browser would be real-time, but different hole filling would make the preview misleading, so we do not do it.
- **Detect stereo layout on import:** a wrong layout splits the image incorrectly yet still completes conversion,
  making it hard to notice. The two eyes of a stereo pair differ only by disparity, so comparing differences after
  horizontal and vertical splitting reveals the layout (`guess_layout` in `stereo.py`). **This does not hold for
  uniform noise**, which becomes uncorrelated after a few pixels of shift; use smooth synthetic images in tests.
- **Store input videos separately from jobs (`sources.py`):** parameter tuning reuses the same video for many previews.
  Tying input storage to a job would re-upload hundreds of MB each time. Jobs reference a source ID without copying video.
- **Provide both CLI and HTTP API conversion entry points:** the UI needs uploads and progress, while the CLI is
  faster for batch work. Keep actual processing in one `pipeline.convert()` implementation and report progress through
  a `progress` callback (stderr for CLI, job state for API). `jobs.JobStore` owns the queue with **a single worker**.
  Views within a frame are already synthesized in parallel, so concurrent jobs do not make conversion faster.
  **Remaining time for a running job comes from that job's measurements (start time and completed frames).**
  Do not display an estimate before export: preview and conversion times differ substantially. Multiplying a preview
  frame's time is inaccurate because preview includes circle detection, JPEG compression, and HTTP; measured preview
  time was 2.9 seconds per frame versus 0.52 seconds for conversion.
  **Running jobs can be canceled**: forgetting to limit duration would render to the end, taking 27 hours for a
  16-minute video at 60 fps. Cancellation raises an exception from the progress callback to unwind processing and
  removes the incomplete output. Keep the web framework inside `server.py` so `jobs.py` can be tested independently.
- **Hole filling in extrapolated views determines quality:** the stereo baseline is only about the distance between
  human eyes and covers less than the Looking Glass view cone. Edge views inevitably reveal occlusion holes
  (disocclusions), so filling them determines the overall appearance.

## AI-driven development harness

The harness has two axes: guides versus sensors, and computational versus inferential.

| | Computational (deterministic) | Inferential (LLM / human) |
| --- | --- | --- |
| **Guides** (shape input) | This CLAUDE.md / `.claude/rules/*.md` (conditional loading with `paths:`) | AskUserQuestion / user instructions |
| **Sensors** (judge output) | `uv run poe check` / `npm run check` | `/review-loop` (repeat until zero MUST/SHOULD findings) / display checks on hardware |

Principle: **run computational checks first. LLM review starts only after they pass.**

- Layer-specific conventions live in `.claude/rules/` and load automatically only when working on matching files.
- `.claude/agents/code-reviewer.md` is the source of truth for review criteria; do not duplicate them elsewhere.
- Documentation and comment ownership is defined in @.claude/rules/documentation.md
  (always loaded because the rule has no `paths:` condition).
- After a substantial feature addition, run `/harness-audit` to check documentation against the actual code.
- Delegate to subagents only for substantial independent tasks. Do not delegate work that takes only a few tool calls.

## Harness self-improvement

Treat this harness as **an operational asset that improves with each session**, rather than static configuration.
Follow `.claude/rules/documentation.md` for triggers and writing rules: incorporate user corrections, non-obvious traps,
and discrepancies between documentation and reality within the same session.
