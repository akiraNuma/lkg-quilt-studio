---
paths:
  - "converter/**/*.py"
---

# Conversion CLI (Python + uv) coding rules

Run checks on the host:

```bash
(cd converter && uv run poe check)    # ruff format --check → ruff check → mypy → pytest
(cd converter && uv run poe format)   # Fix formatting
```

Add dependencies with `uv add` (`uv add --dev` for development dependencies).
Do not edit `pyproject.toml` or `uv.lock` by hand.

**uv manages Python itself (`uv python install`). Do not install Python through mise.**
mise can select a free-threaded build that installs without a `lib` directory and fails with
"Python installation is missing a lib directory". uv selects a build with the GIL.

## Principles

- **Add type hints** sufficient to pass mypy. Explain any use of `Any` in a comment.
- **Use one module per stage** (disparity estimation / view synthesis / quilt layout / encoding).
  Keep each stage capable of saving intermediate results (depth maps and view images) to files.
  Without a way to restart partway through, every retry repeats all the expensive work.
- **Handle errors thoroughly at I/O boundaries** (video reads/writes, ffmpeg calls, model weight loading).
  Fail with a message that identifies the problem, including the path, codec, or shape as appropriate.
  Trust calls between internal functions.
- **Report progress for expensive work.** Frame loops must show the total frame count and current position.
- Do not commit model weights or actual input/output data (already covered by `.gitignore`).

## Python 3.14 syntax (previously misread)

**`except ValueError, TypeError:` is valid syntax.** PEP 758 in Python 3.14 makes the parentheses optional,
and `ruff format` **removes** them. It resembles Python 2 syntax and can look broken,
but restoring the parentheses makes `ruff format --check` fail. Follow the formatter.

## ffmpeg pitfalls encountered and fixed

- **If audio is shorter than the requested range, `-shortest` can produce an mp4 with zero streams and exit code 0.**
  This occurs when `--start` exceeds the audio duration, for example. Specify the duration with `-t`
  and extend short audio with silence using `-af apad` (`mux_audio` in `video.py`).
- **Count the frames written and fail if the count is zero.** ffmpeg exits successfully even if no frame arrives.
- **Seeking by frame number with the `trim` filter decodes everything from the beginning.**
  At frame 20,000 this took 1.82 s, versus 0.20 s with `-ss` before `-i` (verified to return identical pixels).
  Current ffmpeg input-side `-ss` does not round to a keyframe. Aim half a frame early to avoid rounding up.
  The frame-number-to-time mapping assumes a constant frame rate (`read_frames` in `video.py`).
- **Quilt frames are huge, so x264's default settings run out of memory.**
  A 4092² yuv420p frame is 25 MB. x264 retains frames for lookahead and each thread,
  using a measured 2.66 GB and hitting the container memory limit, where **the kernel kills it**.
  The only symptom is an ffmpeg failure with **empty stderr** (it cannot write anything after being killed).
  Check `State.OOMKilled` in `docker inspect`. Longer inputs fail **at the same frame every time**
  (frame 82 in the observed case), which resembles a code bug.
  `rc-lookahead=10:sliced-threads=1` reduces memory use to 1.55 GB.
- **Inputs with rotation metadata need `-noautorotate`; otherwise output width and height swap relative to ffprobe.**
  The byte count still matches, so `reshape` succeeds and processing continues with a corrupted image.
- **`ffmpeg -metadata:s:v rotate=0` does not remove rotation metadata** (current ffmpeg uses displaymatrix).
  Re-encoding (`-c:v libx264`) applies the rotation and removes the metadata.

## Tests (pytest)

- Test pure logic: quilt layout calculations, view-position assignment, and argument validation.
- Do not test model inference itself: it requires weights and takes impractically long.
  For functions that call inference, validate only input/output shape and dtype.
