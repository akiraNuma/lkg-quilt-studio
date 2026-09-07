# lkg-quilt-studio

English | [日本語](README.ja.md)

Convert stereo video (left and right views) into **quilt video** for
[Looking Glass](https://lookingglassfactory.com/) and play it in a browser.

<p align="center">
  <img src="docs/media/wiggle.gif" alt="One converted frame cycling through views taken from the quilt" width="300">
</p>

<p align="center">
  <sub>One converted frame, cycling through 11 of the quilt's 66 views, both ends included.<br>
  On a Looking Glass, the view changes with your viewing angle instead.</sub>
</p>

This English README is authoritative. The Japanese version is a human-readable
translation; update both in the same change. English takes precedence if they differ.

## How it works

Looking Glass displays dozens of views packed into a quilt, directing different
views to different viewing angles to create parallax. Stereo video contains only
two views, so it cannot provide that range of views directly. The converter
estimates depth from disparity, synthesizes the missing views, and packs them into a quilt.

```text
Stereo video → disparity (depth) → view synthesis (DIBR) → quilt layout → quilt video → browser playback
└──────────────── converter (Python, prerendered) ─────────────────┘   └─ viewer (Vue 3 + three.js) ─┘
```

![Left and right input, estimated disparity, and the 11x6 quilt built from them](docs/media/pipeline.jpg)

Left and right input, the disparity estimated from them, and the resulting quilt
for Looking Glass Go: 11 columns x 6 rows, 66 views in one 4092x4092 frame.

The converter has CLI and HTTP API entry points. Through the API, you can upload
video in the browser, follow conversion progress, and play or download the result.

Depth estimation and view synthesis are expensive. Prerendering keeps that work
out of playback.

## Structure

| Directory | Purpose |
| --- | --- |
| `converter/` | Conversion: disparity estimation → view synthesis → quilt encoding. CLI and HTTP API. |
| `viewer/` | Browser playback and conversion controls. |

## Requirements

- Docker Desktop (**recommended**; no separate ffmpeg, Python, or Node installation needed)
- A Looking Glass display and Looking Glass Bridge installed on the host, for hardware validation

For local execution without Docker, install these instead:

- [mise](https://mise.jdx.dev/) to manage Node and uv versions; `.mise.toml` is authoritative
- ffmpeg for video input and output

## Setup

### Docker

Build the images once. After that, use the `docker compose` commands below.

```bash
docker compose build
```

### Local

Run from the repository root:

```bash
mise install              # Install Node and uv
uv python install 3.14    # uv manages Python itself
(cd converter && uv sync) # Converter dependencies
(cd viewer && npm ci)     # Viewer dependencies
```

### Shared Codex harness

`CLAUDE.md` and `.claude/` are the authoritative operating instructions.
Codex reaches them through `AGENTS.md`. Skills are shared through relative symlinks;
the reviewer configuration directs it to the canonical review instructions.
Permissions and hooks are generated from `.claude/settings.json`.
Hooks and synchronization require Python 3.9 or later on PATH.
Harness checks use Python from `converter/.venv`, created by the local setup above.

```bash
python3 scripts/sync-harness.py   # After changing shared settings
scripts/check-harness.sh         # Check scripts/, synchronization, references, and hook inputs
scripts/check.sh                 # All harness, viewer, and converter checks
```

In Codex CLI, open `/hooks`, inspect and trust the session-start and pre-edit hooks,
then start a new session. Inspect them again after their definitions change.
In environments where hooks are untrusted or unsupported, follow `AGENTS.md` to
read the rules manually. Session start supplies always-loaded rules; pre-edit hooks
supply rules matching the target files. Pre-edit hooks cover Claude's `Edit` and
`Write` and Codex's `apply_patch`. Before editing through a shell or external tool,
read the relevant rules directly. After editing, follow the checks in `CLAUDE.md`.

The command allowlist is separate from the overall execution permission mode.
`approval_policy` and `sandbox_mode` live in the tracked `.codex/config.toml`.
This project configures full access without approval prompts.
Higher-priority managed settings and launch options take precedence.
Synchronization supports `Bash(command:*)` patterns and rejects unsupported forms.
Do not edit generated `.codex/hooks.json` or `.codex/rules/claude.rules` directly.

The configuration was checked against `codex-cli 0.153.4`.
Passing static checks does not prove that the client trusted or executed the hooks.
See the [official hook documentation](https://learn.chatgpt.com/docs/hooks) and
[official permission rule documentation](https://learn.chatgpt.com/docs/agent-configuration/rules).

## Usage

Examples below use Docker. For local execution, use the equivalents in this table.

| Task | Docker | Local |
| --- | --- | --- |
| Open the app | `docker compose up` | `cd viewer && npm run dev` and `cd converter && uv run lkg-quilt-api` in separate terminals |
| Convert with the CLI | `docker compose run --rm converter …` | `cd converter && uv run lkg-quilt-converter …` |

Place input videos inside the repository, for example in `samples/`.
The whole repository is mounted in the container, so repository-relative paths work there.
For local CLI commands run from `converter/`, use `../samples/` and `../out/`.

### 0. Get a sample

If you do not have stereo footage, this script downloads and extracts six seconds
from the top-bottom stereo version of [Big Buck Bunny](https://peach.blender.org/).

```bash
./scripts/fetch-sample.sh   # Creates samples/bbb_stereo_tb.mp4; downloads 57 MB
```

The sample is 1920×2160: two stacked 1920×1080 views, with the left eye on top.
Its detailed CG imagery works well for stereo matching. **Texture, such as grass
or fur, is needed to resolve disparity.** Keep this in mind with your own footage.

The default `--span` of 2.0 extrapolates too far for this sample, breaking thin
subjects such as the rabbit's ears. Values around 1.0–1.2 gave better results.

**A quilt for the wrong model will not display correctly.** The browser defaults
to `go`; the CLI defaults to `16`. Check your preset under “Check your display model”
below before converting.

### 1. Convert in the browser

```bash
docker compose up   # http://localhost:5173
```

![The viewer with a source loaded: preview on the left, four numbered panels on the right](docs/media/viewer.jpg)

The image is on the left and controls are on the right. Four panels follow the
workflow. Switch between **English and Japanese** with the top-right button;
the browser remembers your choice.

1. **Display** — Click **Connect to Bridge** to detect the model. **Connection is optional.**
   The default is `go`; preview and export work without Bridge if the model is correct.
2. **Source** — Click **Choose a video** or drop a video onto the surrounding area.
   Import one video at a time. It uploads once; **layout and projection are detected
   from the content**. **The first frame renders automatically** on the left.
3. **Tune** — Use **Move to Looking Glass** to view it on the device, then adjust
   convergence and depth strength.
4. **Export** — Click **Export** when ready. Playback and download links appear when it finishes.

During playback, use the volume slider and mute button below the image.
Autoplay starts muted. Raise the volume or unmute to hear audio.

**Rendering time depends on the machine, source, and settings.** Tune one frame first.
Preview uses the same rendering path as conversion, so **the preview matches the export**.
For long videos, select **Start** and **Frames** to export a portion. Before exporting,
the app shows the frame range and count. **Leaving Frames empty exports to the end.**

Exports run one at a time; each uses the available CPU resources, so concurrent jobs
would slow one another down. Click **Cancel** to stop a running job. Partial output is removed.

### Preview updates automatically

- **Convergence and view** use the playback shader, so their changes appear immediately.
- **Depth strength, field of view, frame**, and **Source** settings rebuild the views.
  Releasing a slider **automatically renders a new frame**, with a rendering message
  at the top left of the image.

**Every slider has a numeric field.** Drag the slider or type a value.
Out-of-range values are clamped; invalid numbers are rejected and shown in red.

The convergence you see is baked into the export; no need to copy values manually.
The app shows the **breakdown**, for example: “Convergence written into the export:
4.75 px (auto -2.50 + manual 7.25)”. The offset is equivalent to a translation of
each view, so playback and export produce the same image (measured residual below 0.1 px).

### Library: manage stored files

Uploaded videos remain in `out/sources/`; exported quilts remain in `out/jobs/`.
Each can occupy tens or hundreds of MB. **List and delete them in the Library panel.**

- **Exported quilts** — Play, download, or delete them; counts and total size are shown.
- **Uploaded sources** — **Use** returns to tuning without uploading again.
  The active source is marked as being tuned. **Deleting it also clears the image.**
- **Failed or canceled jobs** — Only the name and status are shown, since deletion is the remaining action.
- **Deletion takes two steps:** delete, then confirm. **A source cannot be deleted during conversion**
  because the converter is still reading it.

### Fisheye footage (VR180)

VR180 footage contains a circular 180° fisheye image for each eye.
**This is not a planar stereo pair.** Stereo matching searches horizontally for
corresponding points on the same row. Without rectification, fisheye footage gives
inconsistent disparity and a blurred result. The black border outside the circle
also enters the quilt (22.9% of a tile in a measured sample).

Set **Projection** in **Source** to `fisheye`. The converter measures each eye's
circle separately and **rectifies the central field of view onto a plane**.
This removes the black border (0.0% in the measured sample). Set the horizontal
crop angle with **Field of view** in **Tune**. Narrower angles reduce distortion;
wider angles include more of the scene but stretch the edges.

1080p VR180 records 180° across 960 pixels: only **5.3 pixels per degree**.
Showing 50° in a Go tile needs 7.4 pixels per degree, so the image remains soft
regardless of conversion quality.

### 1a. Convert with the CLI

Use the same converter from a terminal for batch work or detailed parameter control.

```bash
docker compose run --rm converter frame   samples/movie.mp4 --output-dir out   # Try one frame
docker compose run --rm converter convert samples/movie.mp4 --output-dir out

# Set projection and field of view for fisheye (VR180)
docker compose run --rm converter convert samples/vr180.mp4 --projection fisheye --fov 50
```

Output names follow `<input>_qs<columns>x<rows>a<aspect>.mp4`.
The viewer reads the layout from this name, so do not rename it.

Useful options (see `--help` for the full list):

| Option | Effect |
| --- | --- |
| `--display go\|portrait\|16\|32` | Display preset; CLI default: `16`. |
| `--layout sbs\|sbs-half\|tb\|tb-half\|separate` | Input stereo layout; default: `sbs`. |
| `--fit crop\|pad` | Fit mismatched aspect ratios; default: `crop`. |
| `--span` | View span. Larger values increase depth and expose more hole-filling artifacts. |
| `--convergence` | Disparity of the plane placed at screen depth. `auto` uses the first frame's median. |
| `--work-dir` | Cache disparity to skip estimation when rerunning. |

Tune `--span` and `--convergence` with `frame` before running `convert`.

At the start of conversion, the CLI reports disparity statistics (median and
10th–90th percentiles) and photometric residual. The residual measures how well
the right-eye image reproduces the left-eye image using the estimated disparity;
lower is better. Disparity is the horizontal coordinate difference `x_left - x_right`.
The renderer subtracts `--convergence` before synthesizing views, so the raw sign alone
does not determine depth relative to the output screen. Set `--convergence` to the disparity
of the plane you want on the screen.

**Swapped eyes cannot be detected reliably from the images.** Swapping produces
a valid stereo pair of a depth-reversed scene. If view movement looks reversed
on the device, rerun with `--swap-eyes`.

### Check your display model

Start Looking Glass Bridge and click **Connect to Bridge** in **Display**.
The app shows the model and quilt layout. Match `--display` to this model.

| Preset / model | Quilt (columns × rows / resolution) | Tile aspect ratio |
| --- | --- | --- |
| `go` / Looking Glass Go | 11 × 6 / 4092² | 0.5625 (portrait) |
| `portrait` / Looking Glass Portrait | 8 × 6 / 3360² | 0.75 (portrait) |
| `16` / Looking Glass 16" | 5 × 9 / 4096² | 1.777 (landscape) |
| `32` / Looking Glass 32" | 5 × 9 / 8192² | 1.777 (landscape) |

**Go and Portrait have portrait tiles**, so landscape footage has a different
aspect ratio. The default `--fit crop` trims the sides to fill the tile.
`--fit pad` adds space above and below to preserve the whole source.
Cropping 16:9 footage for Go retains roughly one third of its width.

**Crop is the default because it produces stronger depth.** Enlarging the cropped
region also enlarges disparity. In the Big Buck Bunny sample, disparity spanned
15 px with crop versus 5 px with pad. To show the full image, use pad and increase `--span`.

### 2. Play in the browser

- After converting in the app, click **Play it** to open the result.
- Select a local MP4 to inspect individual views (**single**) or the whole quilt.
- The development server also serves `out/`. Enter `http://localhost:5173/out/<name>.mp4`
  in the URL field to load it.
- Use **play/pause and seek** below the image; the raw 4092² video is not shown directly.
- **lenticular** maps views to Looking Glass's physical pixels. Stripes on a regular monitor are expected.

### Troubleshooting

- **The image is split in half:** the input layout is wrong. Detection can fail; select it manually.
- **The API hangs or is slow:** another project using `localhost:5173` may have left
  a Service Worker that intercepts fetch requests. This app unregisters it on startup;
  **reload once** to resolve that case.
- **Depth looks flat:** stereo matching cannot resolve disparity on textureless surfaces.
  A large photometric residual in the conversion log (above 10) indicates a poor match.
- **Black borders or a blurred image:** fisheye (VR180) footage is being treated as planar.
  Set **Projection** in **Source** to `fisheye`.
- **Conversion fails with an ffmpeg exit error:** Docker may have insufficient memory.
  Measured conversion usage is about 2 GB, including 1.5 GB for 4092² encoding alone.
  Stop other containers or increase Docker Desktop's memory allocation.
  Failure at the same frame count each time is a useful clue.
- **Export never seems to finish:** an empty Frames field exports from Start to the end.
  One minute at 60 fps contains 3,600 frames. At a measured 0.5 seconds per frame,
  that took 30 minutes; speed varies by machine and settings. Try a short portion first.

## Validate on hardware

Start Looking Glass Bridge, then open the development server described above.

1. Click **Connect to Bridge** in **Display** and select the detected model.
2. If a warning says the quilt layout does not match the model, export it again for that model.
3. Click **Move to Looking Glass**. Move the new window onto the display, then
   **double-click inside that window** to make it full screen.
4. If view movement is reversed or foreground objects appear behind, enable **Swap left and right** in **Source**.
5. Adjust **Convergence** in **Tune** if the scene sits too far forward or back. This updates without rerendering.
6. Increase depth strength in **Tune** if the effect is weak. Higher values expose
   more occlusion-filling artifacts, so judge the tradeoff on the device.

## Development

Run checks locally. The Docker images are for execution and do not include lint
or test dependencies. Run these commands from the repository root:

```bash
(cd converter && uv run poe check)   # ruff format --check → ruff check → mypy → pytest
(cd converter && uv run poe format)  # Fix formatting

(cd viewer && npm run dev)           # Development server
(cd viewer && npm run check)         # format:check → typecheck → lint → build → test
(cd viewer && npm run format)        # Fix formatting
```

The figures in this README are conversion output, so a change to the pipeline makes
them stale. Rebuild them after preparing the sample with `scripts/fetch-sample.sh`:

```bash
converter/.venv/bin/python scripts/make-readme-media.py   # docs/media/*
```

The screenshot of the app is taken by hand; the script does not produce it.

One commit only retranslated comments and would otherwise dominate `git blame`. Skip it with
`git config blame.ignoreRevsFile .git-blame-ignore-revs`.

When developing through Docker:

- `viewer/` source is mounted, so saves trigger HMR. On Windows, files under `C:\`
  (`/mnt/c`) may not send change events. Use `VITE_USE_POLLING=1 docker compose up` in that case.
- After changing `viewer/package.json`, remove the volumes with `docker compose down -v`,
  then run `docker compose up --build`. `node_modules` uses a named volume;
  rebuilding the image alone does not replace its contents.

[CLAUDE.md](CLAUDE.md) is authoritative for agent operating rules, checks, and design decisions.
Claude Code and Codex share the rules, review criteria, and skills in `.claude/`.
Those documents exist only in English; this README is the only translated document.

## Status

Conversion and playback are implemented. **Visual quality on Looking Glass hardware
has not been fully validated.**

Synthetic stereo tests confirm that estimated disparity and movement between views
match theoretical values. Hardware validation must establish whether depth looks
correct, view order is right, and artifacts at extrapolated edge views are acceptable.

For the same reason there is no photograph of the display here yet. The figures above
are conversion output, not a picture of a Looking Glass showing it.

## License

[MIT License](LICENSE)

Big Buck Bunny, downloaded by `scripts/fetch-sample.sh`, is
(c) copyright 2008, Blender Foundation / [peach.blender.org](https://peach.blender.org/),
released under [Creative Commons Attribution 3.0](https://creativecommons.org/licenses/by/3.0/). The downloaded video itself is not
included in this repository, but the figures in `docs/media/` are converted from it
and are covered by the same license and attribution.

Looking Glass is a trademark of Looking Glass Factory, Inc. This is an unofficial
project, unaffiliated with and not endorsed or supported by the company.
