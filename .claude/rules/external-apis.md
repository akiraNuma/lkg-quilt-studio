---
paths:
  - "converter/**/*.py"
  - "viewer/src/**/*.ts"
  - "viewer/src/**/*.vue"
---

# External references (Looking Glass / depth estimation models)

**Do not guess parameter names, layout conventions, or model inputs and outputs.**
Check the sources below before implementation. Cite the source URL when encoding non-obvious constraints in code.

## Looking Glass

| Documentation | URL |
| --- | --- |
| What is a quilt? (layout and view-count concepts) | https://lookingglassfactory.com/tutorial/what-is-a-quilt |
| Quilt key concepts | https://lfdocs.lookingglassfactory.com/keyconcepts/quilts |
| Quilt video encoding conventions | https://lfdocs.lookingglassfactory.com/keyconcepts/quilts/quilt-video-encoding |
| Quilt video playback and audio | https://docs.lookingglassfactory.com/software/index/quilt-video-audio-and-playback |
| WebXR library (`@lookingglass/webxr`) | https://lfdocs.lookingglassfactory.com/software/creator-tools/webxr |
| Bridge SDK (calibration retrieval and display integration) | https://docs.lookingglassfactory.com/software/looking-glass-bridge-sdk |
| Bridge.js (official library for casting quilts from the web to Bridge's media player) | https://github.com/Looking-Glass/bridge.js |
| Community tools | https://lfdocs.lookingglassfactory.com/software/third-party-apps-and-tools/community-made-tools-and-projects |

- **Quilt columns × rows and view count depend on the display model** (for example, Looking Glass 16" uses 5 columns × 9 rows).
  Accept the model as an argument instead of hard-coding it in the converter.
- **Per-model tile counts can be looked up by serial prefix (`LKG-4K`, `LKG-P`, etc.).**
  The mapping is in `LookingGlassConfig`'s `get quiltWidth` / `get quiltHeight` in
  `dist/bundle/webxr.js` from `@lookingglass/webxr@0.6.0`. **Do not copy it into the code.**
  Its default resolutions differ from the hardware (the polyfill returns 4096² even for Portrait).
  Bridge's runtime `defaultQuilt` values are more accurate, so the viewer checks against them (`layoutMismatch`).
- High-resolution quilt videos may not play in browsers or the OS's default player because of codec limits.
  Check the encoding conventions linked above when choosing encoding settings.
- **The official Bridge.js documentation has no video (mp4) example.** It only shows casting a still-image (jpg)
  `QuiltHologram`. **Casting a quilt video was tried on hardware and did not play**, so the viewer no longer
  casts at all; it shows the quilt in its own window instead (see the design decisions in `CLAUDE.md`).
  `getDisplays()` for calibration is still used.

### Findings from inspecting Bridge.js (`@lookingglass/bridge`)

The bundled `dist/*.d.ts` and `dist/looking-glass-bridge.mjs` are the sole sources here.
The README does not describe the types.

- `getDisplays()` returns **plain numbers** in `calibration` (such as `pitch: 52.58`).
  `@lookingglass/webxr` wraps `LookingGlassConfig.calibration` values as `{ value: 52.58 }`.
  **These are different representations; do not mix them.**
- In `defaultQuilt`, `{ quiltWidth, quiltHeight }` are **pixel dimensions**, `{ columns, rows }` are **tile counts**,
  and `quiltAspect` is the aspect ratio of one tile. The webxr polyfill's `quiltWidth` means tile count,
  so the names collide.
- A `QuiltHologram`'s `uri` must point to **a location readable by Bridge, which is a separate process**.
  A `blob:` URL valid only inside the browser cannot be used.
- The package's `exports` has no `"types"` entry, so `moduleResolution: bundler` cannot reach the bundled declarations.
  `paths` in `viewer/tsconfig.app.json` points directly to `dist/index.d.ts`.
- The `import` and `require` entries in `exports` are **reversed** (`import` points to CJS, `require` to ESM).
  Vite resolves them, but this is an upstream bug.
- **The lenticular conversion formula is absent from the official documentation.** The sole sources are `Shader()`
  and `LookingGlassConfig`'s `get pitch / tilt / subp` in `dist/bundle/webxr.js` from `@lookingglass/webxr@0.6.0`.
  `viewer/src/lenticular.ts` follows them. **This package is not a viewer dependency**;
  retrieve it with `npm pack @lookingglass/webxr@0.6.0` when comparing implementations.
- **Arrange tiles on an integer-sized grid and exclude leftover edge pixels through UVs.**
  The official implementation builds the grid with `tileWidth = round(framebufferWidth / columns)`
  and excludes padding using `quiltViewPortion`. Fractional boundaries leave columns or rows outside every tile
  (`viewPortion` in `viewer/src/lenticular.ts`, `QuiltSpec.tile_size` in `converter/src/lkg_quilt_converter/quilt.py`).
- **The bundled `.d.ts` declares `Display.index` / `windowCoords` as `BridgeValue`, but the implementation
  (`tryParseDisplay`) unwraps every field before returning it.** Trusting the declarations and adding `.value`
  yields `undefined`, even though type checking passes.
- **Direct HTTP API calls return `calibration` and `defaultQuilt` as JSON strings**, requiring `JSON.parse`.
  When using bridge.js, the library parses them. **The list also includes non-Looking Glass monitors,
  whose `calibration` is an empty string** and cannot be parsed.

### Querying a device's quilt settings directly (no browser needed)

Bridge's local API uses **PUT** requests to `http://localhost:33334/<endpoint>`.
Use it as the source of truth when defining model presets.

```bash
TOKEN=$(curl -s -X PUT -H 'Content-Type: application/json' -d '{"name":"probe"}' \
  http://localhost:33334/enter_orchestration | python3 -c 'import sys,json;print(json.load(sys.stdin)["payload"]["value"])')
curl -s -X PUT -H 'Content-Type: application/json' -d "{\"orchestration\":\"$TOKEN\"}" \
  http://localhost:33334/available_output_devices
curl -s -X PUT -H 'Content-Type: application/json' -d "{\"orchestration\":\"$TOKEN\"}" \
  http://localhost:33334/exit_orchestration
```

- Returned `defaultQuilt` contains `tileX` / `tileY` (tile counts), `quiltX` / `quiltY` (pixel dimensions),
  and `quiltAspect` (the displayed aspect ratio of one tile).
- **The tile's pixel aspect ratio differs from `quiltAspect`.** Go uses 4092/11 x 4092/6 = 372x682 pixels,
  a ratio of 0.545, but the displayed ratio is 0.5625. Calculate padding using the displayed ratio.
- Measured values (Looking Glass Go, serial prefix `LKG-E`, `hardwareVersion: go_p`):
  `tileX 11 / tileY 6 / quiltX 4092 / quiltY 4092 / quiltAspect 0.5625`, screen 1440x2560, view cone 54°.
- `LookingGlassConfig` in `@lookingglass/webxr@0.6.0` also has a table indexed by serial prefix.
  Tile counts agree, but **resolutions can differ from the hardware**, so do not copy them.

## Existing implementations to consult

| Implementation | Useful reference for |
| --- | --- |
| https://github.com/9ballsyndrome/WebGL_LookingGlass_QuiltViewer | Minimal browser quilt display |
| https://github.com/amariichi/VideoDepthViewer3D | Overall depth estimation + three.js/WebXR + Looking Glass output architecture (monocular input) |
| https://github.com/JuanIrache/looking-glass-after-effects | Building quilts from lateral camera movement |
| https://github.com/peterwilli/Liquilt | Format conversion for easier quilt distribution on the web |

## Candidate depth (disparity) estimation models

The input provides two stereo views, so prefer **stereo matching over monocular depth estimation**.
Depth can be derived directly from disparity without scale ambiguity.

| Model | Role | URL |
| --- | --- | --- |
| Stereo Any Video | Video-oriented; addresses temporal consistency across frames | https://arxiv.org/html/2503.05549v1 |
| FoundationStereo | Prioritizes zero-shot accuracy; expensive per frame | https://arxiv.org/pdf/2501.09898 |
| Fast-FoundationStereo | About 10× faster than the above (CVPR 2026) | https://github.com/NVlabs/Fast-FoundationStereo |

- **For video, temporal consistency matters more than single-frame accuracy.**
  Depth fluctuations between frames appear as flicker during playback.
- **No stereo matcher can determine disparity on a textureless surface**: the same color matches everywhere.
  With the default SGBM, such surfaces collapse to the background disparity.
  This is the main motivation for replacing it with a deep model.
- PyTorch supports Python 3.10–3.14 (checked at https://pytorch.org/get-started/locally/).
