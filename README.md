# lkg-quilt-studio

English | [日本語](README.ja.md)

Turns stereo video (a left and a right view) into quilt video for
[Looking Glass](https://lookingglassfactory.com/) displays, and plays it in the browser.

<p align="center">
  <img src="docs/media/wiggle.gif" alt="One converted frame stepping through views taken from the quilt" width="300">
</p>

<p align="center">
  <sub>One converted frame, stepping through 11 of the quilt's 66 views.<br>
  On a Looking Glass the view changes with your viewing angle instead.</sub>
</p>

## How it works

A Looking Glass shows dozens of views at once and sends a different one to each
viewing angle. Stereo video has only two. The converter estimates depth from the
disparity between them, synthesizes the views in between and beyond, and packs
them into a quilt.

```text
stereo video → disparity → view synthesis → quilt video → browser playback
└──────── converter (Python, offline) ────────┘  └─ viewer (Vue 3 + three.js) ─┘
```

![Left and right input, the estimated disparity, and the 11x6 quilt built from them](docs/media/pipeline.jpg)

Left and right input, the disparity estimated from them, and the resulting quilt
for a Looking Glass Go: 11 × 6 tiles, 66 views in one 4092 × 4092 frame.

`converter/` is a Python CLI with an HTTP API. `viewer/` is the web app that
uploads video, tunes the result, follows progress, and plays it. Conversion runs
ahead of time because depth estimation and view synthesis are too slow for playback.

## Requirements

- Docker Desktop. Nothing else needs installing.
- For output on the device: a Looking Glass and Looking Glass Bridge on the host.

Without Docker: [mise](https://mise.jdx.dev/) (installs Node and uv; versions
are in `.mise.toml`) and ffmpeg.

## Setup

Docker:

```bash
docker compose build
```

Local:

```bash
mise install
uv python install 3.14
(cd converter && uv sync)
(cd viewer && npm ci)
```

## Usage

The commands below use Docker. Local equivalents:

| | Docker | Local |
| --- | --- | --- |
| App | `docker compose up` | `cd viewer && npm run dev` and `cd converter && uv run lkg-quilt-api` |
| CLI | `docker compose run --rm converter …` | `cd converter && uv run lkg-quilt-converter …` |

Put input videos inside the repository, for example in `samples/`. The container
mounts the whole repository, so repository-relative paths work.

### Get a sample

No stereo footage at hand? This downloads six seconds of the top-bottom stereo
[Big Buck Bunny](https://peach.blender.org/):

```bash
./scripts/fetch-sample.sh   # samples/bbb_stereo_tb.mp4, 57 MB download
```

It is 1920 × 2160: two 1920 × 1080 views stacked, left eye on top. Stereo
matching needs texture. Grass and fur work well, flat walls do not.

### Convert in the browser

```bash
docker compose up   # http://localhost:5173
```

![The app with a source loaded: the picture on the left, numbered panels on the right](docs/media/viewer.jpg)

The picture is on the left. The panels on the right follow the workflow.
The top-right button switches between English and Japanese.

1. **Display.** Connect to Bridge to detect your model. This is optional: the
   default is `go`, and preview and export work without Bridge if the model is right.
2. **Source.** Choose or drop a video. It uploads once. Layout and projection are
   detected from the content, and the first frame appears on the left.
3. **Tune.** Move the picture to the Looking Glass and adjust while looking at
   the device. Convergence and view apply instantly. Depth strength, field of
   view and frame rebuild the picture; release the slider and it redraws by itself.
4. **Export.** Set the start frame and count if you want only part of the video,
   then export. When it finishes you can play or download the result.

Preview and export share one rendering path, so what you tune is what you get,
and the convergence you set is written into the export. A frame takes about a
second on a laptop and a video takes that long per frame, so tune on one frame first.

Exports run one at a time and can be cancelled. The Library panel lists uploaded
sources and exported quilts, which can be hundreds of megabytes, and deletes them.

### Convert from the command line

```bash
docker compose run --rm converter frame   samples/movie.mp4 --output-dir out   # one frame, to tune
docker compose run --rm converter convert samples/movie.mp4 --output-dir out
docker compose run --rm converter convert samples/vr180.mp4 --projection fisheye --fov 50
```

Output is named `<input>_qs<columns>x<rows>a<aspect>.mp4`. The viewer reads the
layout from the name, so keep it.

| Option | Meaning |
| --- | --- |
| `--display go\|portrait\|16\|32` | Display preset. Default `16`; the browser defaults to `go`. |
| `--layout sbs\|sbs-half\|tb\|tb-half\|separate` | Input stereo layout. Default `sbs`. |
| `--fit crop\|pad` | How a landscape source fits a portrait tile. Default `crop`. |
| `--span` | Depth strength. `1.0` spans the two cameras; more extrapolates. |
| `--convergence` | Disparity placed at screen depth. `auto` uses the first frame's median. |
| `--swap-eyes` | Use when depth looks inside out on the device. |
| `--work-dir` | Caches disparity so a rerun skips estimation. |

See `--help` for the rest. The default `--span` of 2.0 is too strong for the
sample: thin shapes such as the rabbit's ears break up. 1.0 to 1.2 looked best.

Swapped eyes cannot be detected from the images. A swapped pair is a valid pair
for a depth-reversed scene, so check on the device.

### Check your display model

A quilt built for the wrong model does not display correctly. Start Bridge, click
**Connect to Bridge** in the app, and match `--display` to what it reports.

| Preset / model | Quilt | Tile aspect |
| --- | --- | --- |
| `go` / Looking Glass Go | 11 × 6, 4092² | 0.5625 (portrait) |
| `portrait` / Looking Glass Portrait | 8 × 6, 3360² | 0.75 (portrait) |
| `16` / Looking Glass 16" | 5 × 9, 4096² | 1.777 (landscape) |
| `32` / Looking Glass 32" | 5 × 9, 8192² | 1.777 (landscape) |

Go and Portrait have portrait tiles. With landscape footage, `--fit crop` keeps
the middle third and fills the tile; `--fit pad` keeps the whole frame with bars
above and below. Crop is the default because enlarging the picture also enlarges
its disparity, so the depth is stronger.

### Fisheye footage (VR180)

VR180 stores a circular fisheye image per eye. Set **Projection** to `fisheye`
(`--projection fisheye` on the CLI). The converter finds each circle and
rectifies the centre onto a plane before matching, which removes the black rim.
**Field of view** (`--fov`) sets how much of the 180° to keep. Narrower is
sharper; wider shows more but stretches the edges.

1080p VR180 has only 5.3 pixels per degree, so it stays soft however it is converted.

### Play in the browser

- Play an export from the Export or Library panel. Video starts muted; the
  controls under the picture handle play, seek and volume.
- Open a local quilt MP4 or a URL from the Library panel. The dev server serves
  `out/` at `http://localhost:5173/out/<name>.mp4`.
- The buttons under the picture switch between **Lenticular** (what the Looking
  Glass shows; stripes on a normal monitor are expected), **Single view** and the whole **Quilt**.

### Troubleshooting

- **The picture is cut in half.** Wrong stereo layout. Detection can miss; pick it in Source.
- **Depth is flat.** Textureless surfaces give no disparity. A photometric
  residual above 10 in the conversion log means the match is poor.
- **Black rim or blurry picture.** Fisheye footage read as flat. Set Projection to `fisheye`.
- **ffmpeg exits during export.** Docker is probably out of memory; conversion
  uses about 2 GB. Failing at the same frame every time is the sign.
- **The export never ends.** A blank Frames field exports to the end. One minute
  at 60 fps is 3,600 frames. Try a short range first.
- **The API is slow or silent.** A Service Worker from another project on
  `localhost:5173` may be intercepting requests. The app unregisters it at startup; reload once.

## Validate on hardware

1. Start Looking Glass Bridge and open the app.
2. Click **Connect to Bridge** in Display. If a warning says the quilt does not
   match the model, export again for that model.
3. Click **Move to Looking Glass** in Tune. Drag the new window onto the Looking
   Glass and double-click inside it for full screen.
4. If near objects look far and far objects look near, turn on **Swap left and right** in Source.
5. Adjust **Convergence** to place the scene in front of or behind the screen. This does not rerender.
6. Raise **Depth strength** if the effect is weak. Higher values expose more
   hole-filling artifacts at the edge views, so judge on the device.

## Development

The Docker images contain no lint or test tools. Run the checks locally, from the
repository root:

```bash
scripts/check.sh                     # everything below
(cd converter && uv run poe check)   # ruff format --check, ruff check, mypy, pytest
(cd viewer && npm run check)         # prettier, vue-tsc, eslint, vite build, vitest
scripts/check-harness.sh             # scripts/ lint and types, agent configuration sync
```

`uv run poe format` and `npm run format` fix formatting.

The figures in this README are conversion output. After changing the pipeline,
fetch the sample and rebuild them:

```bash
converter/.venv/bin/python scripts/make-readme-media.py   # docs/media/*
```

The screenshot is taken by hand.

When editing through Docker, saves under `viewer/` trigger HMR. On Windows, files
under `/mnt/c` may not send change events; use `VITE_USE_POLLING=1 docker compose up`.
After changing `viewer/package.json`, run `docker compose down -v` and then
`docker compose up --build`, because `node_modules` lives in a named volume.

One commit only translated comments into English.
`git config blame.ignoreRevsFile .git-blame-ignore-revs` hides it from `git blame`.

Agent instructions, design decisions and the validation workflow are in
[CLAUDE.md](CLAUDE.md). Codex reads them through [AGENTS.md](AGENTS.md).

## License

[MIT](LICENSE).

Big Buck Bunny is (c) 2008 Blender Foundation, [peach.blender.org](https://peach.blender.org/),
[CC BY 3.0](https://creativecommons.org/licenses/by/3.0/). The video is not in this
repository, but the figures in `docs/media/` are made from it and carry the same license.

Looking Glass is a trademark of Looking Glass Factory, Inc. This is an unofficial
project, not affiliated with or endorsed by them.
