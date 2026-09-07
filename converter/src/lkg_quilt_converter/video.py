"""Video I/O through ffmpeg.

Uses an ffmpeg pipe rather than OpenCV's VideoCapture: it makes the pixel format (rgb24) and the
frame range explicit, and the supported codecs match the host's ffmpeg.
"""

import json
import shutil
import subprocess
import tempfile
from collections.abc import Generator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from types import TracebackType

import numpy as np
from numpy.typing import NDArray

Frame = NDArray[np.uint8]
"""An rgb24 frame of (height, width, 3)."""


class FfmpegError(RuntimeError):
    """An ffmpeg / ffprobe invocation failed."""


def _binary(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise FfmpegError(f"{name} が見つからない。ffmpeg を入れて PATH に通す")
    return found


@dataclass(frozen=True)
class VideoInfo:
    """Input video metadata. `frame_count` is 0 when unknown."""

    path: Path
    width: int
    height: int
    fps: Fraction
    frame_count: int
    has_audio: bool


def probe(path: Path) -> VideoInfo:
    """Read resolution, frame rate, and frame count with ffprobe."""
    command = [
        _binary("ffprobe"),
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise FfmpegError(f"{path} を ffprobe で読めない: {completed.stderr.strip()}")
    probed = json.loads(completed.stdout)
    streams = probed.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise FfmpegError(f"{path} に映像ストリームが無い")

    fps = Fraction(video.get("avg_frame_rate") or "0/1")
    if fps <= 0:
        fps = Fraction(video.get("r_frame_rate") or "0/1")
    if fps <= 0:
        raise FfmpegError(f"{path} のフレームレートを判定できない")

    rotation = _rotation(video)
    if rotation:
        raise FfmpegError(
            f"{path} に {rotation} 度の回転メタデータがある。左右の視差が縦方向になって"
            "推定できないので、回転を焼き込んでから渡す"
            "（例: ffmpeg -i in.mp4 -c:v libx264 out.mp4。再エンコードで回転が適用され、"
            "メタデータは落ちる）"
        )

    return VideoInfo(
        path=path,
        width=int(video["width"]),
        height=int(video["height"]),
        fps=fps,
        frame_count=_frame_count(video, probed.get("format", {}), fps),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
    )


def _rotation(video: dict[str, object]) -> int:
    """The video stream's rotation metadata in degrees, or 0 when absent.

    Current ffprobe normalises it into displaymatrix side data, but files written by older tools
    carry only `tags.rotate`, so both are read.
    """
    side_data = video.get("side_data_list")
    if isinstance(side_data, list):
        for entry in side_data:
            angle = entry.get("rotation") if isinstance(entry, dict) else None
            if isinstance(angle, int | float) and int(angle) % 360:
                return int(angle)
    tags = video.get("tags")
    tagged = tags.get("rotate") if isinstance(tags, dict) else None
    if isinstance(tagged, str):
        try:
            return int(float(tagged)) % 360
        except ValueError:
            return 0
    return 0


def _frame_count(video: dict[str, object], container: dict[str, object], fps: Fraction) -> int:
    declared = video.get("nb_frames")
    if isinstance(declared, str) and declared.isdigit():
        return int(declared)
    duration = video.get("duration") or container.get("duration")
    if isinstance(duration, str):
        try:
            return int(float(duration) * fps)
        except ValueError:
            pass
    return 0


def read_frames(info: VideoInfo, *, start: int = 0, count: int | None = None) -> Generator[Frame]:
    """Yield rgb24 frames in order. The range is given in frame numbers."""
    if start < 0:
        raise ValueError(f"start は 0 以上（受け取った値: {start}）")
    if count is not None and count <= 0:
        raise ValueError(f"count は 1 以上（受け取った値: {count}）")

    command = [
        _binary("ffmpeg"),
        "-v",
        "error",
        "-nostdin",
        # Do not let rotation metadata be applied (it would swap the output's width and height
        # against what probe reported). probe rejects rotated input, so this normally does
        # nothing; it guards calls that bypass probe
        "-noautorotate",
    ]
    if start:
        # -ss before -i is accurate in current ffmpeg and skips decoding up to the target frame.
        # Counting from the start with the trim filter takes tens of seconds 20,000 frames in
        # (measured 1.82 s -> 0.20 s). Aiming half a frame early keeps rounding from landing on
        # the next frame. Mapping frame numbers to timestamps assumes a constant frame rate
        # (probe's fps is trusted)
        command += ["-ss", f"{(start - 0.5) / float(info.fps):.6f}"]
    command += ["-i", str(info.path)]
    if count is not None:
        command += ["-frames:v", str(count)]
    command += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]

    frame_bytes = info.width * info.height * 3
    with tempfile.TemporaryFile() as errors:
        # Send stderr to a file. Left as a pipe, its buffer fills before we finish reading
        # stdout and ffmpeg stalls
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
        assert process.stdout is not None
        try:
            while True:
                raw = process.stdout.read(frame_bytes)
                if not raw:
                    break
                if len(raw) != frame_bytes:
                    raise FfmpegError(
                        f"{info.path} のフレームが途中で切れた（{len(raw)} / {frame_bytes} バイト）"
                    )
                yield np.frombuffer(raw, dtype=np.uint8).reshape(info.height, info.width, 3)
        finally:
            process.stdout.close()
            returncode = process.wait()
            errors.seek(0)
            message = errors.read().decode("utf-8", "replace").strip()
        if returncode != 0:
            raise FfmpegError(f"{info.path} の読み込みに失敗した: {message}")


def mux_audio(video: Path, source: Path, output: Path, *, start: float, duration: float) -> None:
    """Mux the source video's audio onto a video-only mp4 and write it to `output`.

    The duration is stated with `-t`, and short audio is padded with silence by `apad`. Left to
    `-shortest`, audio shorter than the requested range truncates the whole output and **produces
    an mp4 with zero streams and exit code 0** (for instance when `--start` is past the end of
    the audio).
    """
    command = [
        _binary("ffmpeg"),
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(video),
        "-ss",
        f"{start:.6f}",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-af",
        "apad",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-t",
        f"{duration:.6f}",
        "-movflags",
        "+faststart",
        str(output),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise FfmpegError(f"音声を重ねられなかった: {_first_line(completed.stderr)}")


def _first_line(message: str) -> str:
    """The first line of ffmpeg's stderr. Later lines are per-thread cleanup; the cause is first.

    Prefixes such as `[aac @ 0x880c21c00] ` carry an address that changes every run and are
    dropped for legibility.
    """
    for line in message.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[") and "] " in stripped:
            return stripped.split("] ", 1)[1]
        return stripped
    return "（ffmpeg は理由を出さなかった）"


X264_PARAMS = "rc-lookahead=10:sliced-threads=1"
"""Settings that cut x264's memory use. **One quilt frame is huge, and the defaults do not fit.**

4092 squared is 25 MB per frame in yuv420p. x264 holds frames for lookahead and per thread, so at
the defaults it uses 2.66 GB, hits the container's memory limit, and **is killed by the kernel**
(measured: `OOMKilled`, always at frame 82; it dies with an empty stderr, so no cause is
reported). Dropping frame-level parallelism (`sliced-threads`) and shortening lookahead brings it
to 1.55 GB. A frame slows from 0.10 s to 0.16 s, which hides behind view synthesis at 0.46 s and
leaves the total unchanged.
"""


class QuiltEncoder:
    """Write quilt frames to a video-only mp4. Use it as a context manager.

    Audio is not mixed in. To add it, mux afterwards with `mux_audio` (its docstring says why).
    """

    def __init__(
        self,
        path: Path,
        *,
        width: int,
        height: int,
        fps: Fraction,
        crf: int = 20,
        preset: str = "slow",
        faststart: bool = True,
    ) -> None:
        if width % 2 or height % 2:
            raise ValueError(f"yuv420p は偶数の解像度が必要（{width}x{height}）")
        self._path = path
        self._frame_bytes = width * height * 3
        self._frames = 0
        # Must stay open as long as the encoder lives, so it cannot be wrapped in `with`
        self._errors = tempfile.TemporaryFile()  # noqa: SIM115
        command = [
            _binary("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-r",
            str(fps),
            "-i",
            "-",
        ]
        command += [
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            str(crf),
            "-preset",
            preset,
            "-x264-params",
            X264_PARAMS,
        ]
        if faststart:
            command += ["-movflags", "+faststart"]
        command += [str(path)]
        self._process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=self._errors)

    @property
    def frames_written(self) -> int:
        return self._frames

    def write(self, frame: Frame) -> None:
        stdin = self._process.stdin
        assert stdin is not None
        # tobytes() would copy 50 MB per frame at 4092 squared; a contiguous array is passed as is
        data = frame if frame.flags["C_CONTIGUOUS"] else np.ascontiguousarray(frame)
        if data.nbytes != self._frame_bytes:
            raise ValueError(f"quilt の大きさが違う（{data.nbytes} / {self._frame_bytes} バイト）")
        try:
            stdin.write(data.data)
        except BrokenPipeError as broken:
            # The path can be a temporary file, so it is not reported
            raise FfmpegError(f"quilt の書き込み中に ffmpeg が落ちた: {self._stderr()}") from broken
        self._frames += 1

    def close(self) -> None:
        stdin = self._process.stdin
        assert stdin is not None
        if not stdin.closed:
            stdin.close()
        returncode = self._process.wait()
        message = self._stderr()
        self._errors.close()
        if returncode != 0:
            # The path can be a temporary file, so it is not reported
            raise FfmpegError(f"quilt の書き出しに失敗した: {_first_line(message)}")
        if self._frames == 0:
            # Do not leave an empty mp4 behind as a success (happens when --start is out of range)
            self._path.unlink(missing_ok=True)
            # The path can be a temporary file, so it is not reported
            raise FfmpegError(
                "書き出すフレームが 1 枚も無かった。"
                "--start / --frames が入力の範囲に収まっているか確かめる"
            )

    def _stderr(self) -> str:
        self._errors.seek(0)
        return self._errors.read().decode("utf-8", "replace").strip()

    def __enter__(self) -> QuiltEncoder:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc is None:
            self.close()
            return
        self._process.kill()
        self._process.wait()
        self._errors.close()
