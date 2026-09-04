"""ffmpeg 経由の動画入出力。

OpenCV の VideoCapture ではなく ffmpeg のパイプを使う。ピクセル形式（rgb24）と
フレーム範囲を明示でき、対応コーデックがホストの ffmpeg に揃うため。
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
"""(高さ, 幅, 3) の rgb24 フレーム。"""


class FfmpegError(RuntimeError):
    """ffmpeg / ffprobe の呼び出しが失敗した。"""


def _binary(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise FfmpegError(f"{name} が見つからない。ffmpeg を入れて PATH に通す")
    return found


@dataclass(frozen=True)
class VideoInfo:
    """入力動画のメタデータ。`frame_count` は不明なら 0。"""

    path: Path
    width: int
    height: int
    fps: Fraction
    frame_count: int
    has_audio: bool


def probe(path: Path) -> VideoInfo:
    """ffprobe で解像度・フレームレート・フレーム数を読む。"""
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
    """映像ストリームの回転メタデータ（度）。無ければ 0。

    今の ffprobe は displaymatrix の side data に正規化するが、古いツールが書いた
    `tags.rotate` だけのファイルもあるので両方見る。
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
    """rgb24 のフレームを順に返す。範囲はフレーム番号で指定する。"""
    if start < 0:
        raise ValueError(f"start は 0 以上（受け取った値: {start}）")
    if count is not None and count <= 0:
        raise ValueError(f"count は 1 以上（受け取った値: {count}）")

    command = [
        _binary("ffmpeg"),
        "-v",
        "error",
        "-nostdin",
        # 回転メタデータを適用させない（適用されると出力の縦横が probe の値と入れ替わる）。
        # probe が回転付きの入力を弾くので通常は効かない。probe を通らない呼び出しへの保険
        "-noautorotate",
    ]
    if start:
        # -i より前の -ss は今の ffmpeg では正確で、目的のフレームまでデコードを飛ばす。
        # trim フィルタで頭から数えると 2 万フレーム先で数十秒掛かる（実測 1.82s → 0.20s）。
        # 半フレーム手前を狙うのは、丸めで次のフレームに乗らないようにするため。
        # フレーム番号と時刻の対応は一定フレームレートが前提（probe の fps を信じる）
        command += ["-ss", f"{(start - 0.5) / float(info.fps):.6f}"]
    command += ["-i", str(info.path)]
    if count is not None:
        command += ["-frames:v", str(count)]
    command += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]

    frame_bytes = info.width * info.height * 3
    with tempfile.TemporaryFile() as errors:
        # stderr をファイルに逃がす。パイプのままにすると、こちらが stdout を読み切る前に
        # stderr のバッファが埋まって ffmpeg ごと止まる
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
    """映像だけの mp4 に、元動画の音声を重ねて `output` に書く。

    尺を `-t` で明示し、足りない音声は `apad` で無音を継ぎ足す。`-shortest` に任せると、
    音声が要求範囲より短いときに出力全体が切られ、**ストリーム 0 本の mp4 が
    終了コード 0 で出る**（`--start` が音声の長さを越えた場合など）。
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
    """ffmpeg の stderr の 1 行目。後続はスレッドごとの後始末で、原因は 1 行目に出る。

    `[aac @ 0x880c21c00] ` のような接頭辞は毎回アドレスが変わって読みにくいので落とす。
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
"""x264 のメモリを削る設定。**quilt は 1 フレームが巨大なので既定のままでは足りない。**

4092² は yuv420p で 1 枚 25 MB。x264 は先読みとスレッドごとにフレームを抱えるので、
既定では 2.66 GB 使い、コンテナのメモリ上限に当たって**カーネルに殺される**
（実測: `OOMKilled`、82 フレーム目で毎回落ちた。stderr は空のまま死ぬので原因が出ない）。
フレーム単位の並列をやめて（`sliced-threads`）先読みを詰めると 1.55 GB に下がる。
1 枚 0.10 s → 0.16 s と遅くなるが、視点合成の 0.46 s に隠れて全体の時間は変わらない。
"""


class QuiltEncoder:
    """quilt フレームを映像だけの mp4 に書き出す。`with` で使う。

    音声は混ぜない。混ぜるなら書き出し後に `mux_audio` で重ねる（理由はそちらの docstring）。
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
        # エンコーダの寿命と同じだけ開いておく必要があるので with では包めない
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
        # tobytes() だと 4092² で 50 MB の複製が毎フレーム増える。連続配列ならそのまま渡す
        data = frame if frame.flags["C_CONTIGUOUS"] else np.ascontiguousarray(frame)
        if data.nbytes != self._frame_bytes:
            raise ValueError(f"quilt の大きさが違う（{data.nbytes} / {self._frame_bytes} バイト）")
        try:
            stdin.write(data.data)
        except BrokenPipeError as broken:
            # 一時ファイルのこともあるのでパスは出さない
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
            # 一時ファイルのこともあるのでパスは出さない
            raise FfmpegError(f"quilt の書き出しに失敗した: {_first_line(message)}")
        if self._frames == 0:
            # 中身の無い mp4 を成功として残さない（--start が範囲外のときに起きる）
            self._path.unlink(missing_ok=True)
            # 一時ファイルのこともあるのでパスは出さない
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
