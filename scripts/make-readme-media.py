"""README に載せる図と GIF を作り直す。

変換の結果そのものを載せるので、パイプラインを変えたら作り直す。
使い方（リポジトリ直下から。素材は scripts/fetch-sample.sh で用意する）:

    converter/.venv/bin/python scripts/make-readme-media.py

converter/.venv の Python で動かす。cv2 と numpy、それに editable install した
lkg_quilt_converter がそこにしか入っていない。

ラベルは英語で書く。README.md と README.ja.md で同じ画像を使うため、
言語ごとに画像を分けない（cv2.putText が ASCII しか描けないという制約もある）。
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

import cv2
import numpy as np
from lkg_quilt_converter.disparity import DisparityParams, SgbmDisparityEstimator
from lkg_quilt_converter.pipeline import ConvertOptions, render_single_frame
from lkg_quilt_converter.quilt import PRESETS
from lkg_quilt_converter.stereo import PIXEL_ASPECT, fit_content, plan_fit, split_stereo
from lkg_quilt_converter.video import Frame, probe, read_frames

ROOT = Path(__file__).resolve().parents[1]
DISPLAY = "go"
LAYOUT = "tb"
SPAN = 1.2
CARD = (255, 255, 255)
INK = (47, 41, 36)  # BGR。GitHub の本文色 #24292f に合わせる
LABEL = cv2.FONT_HERSHEY_DUPLEX
PANEL = 300
"""図の各パネルの画像部分の高さ（画素）。段の高さを揃えて横に並べる。"""

BAR = 24
"""ラベルの帯の高さ。パネルの画像部分はこの下にそろえて置く。"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "samples/bbb_stereo_tb.mp4")
    parser.add_argument("--frame", type=int, default=0, help="素材にする動画のフレーム番号")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/media")
    args = parser.parse_args()

    if not args.source.exists():
        print(f"no source: {args.source} (run scripts/fetch-sample.sh)", file=sys.stderr)
        return 1
    args.output_dir.mkdir(parents=True, exist_ok=True)

    options = ConvertOptions(
        source=args.source,
        # 1 フレームだけ描くので出力先は使わない。ConvertOptions が必須にしているだけ。
        # 追跡対象のディレクトリを指さないよう、出力先の下には置かない
        output=Path("unused.mp4"),
        spec=PRESETS[DISPLAY],
        layout=LAYOUT,
        span=SPAN,
        start=args.frame,
    )
    quilt = render_single_frame(options)
    left, right = eye_frames(args.source, args.frame)

    write_wiggle(quilt, args.output_dir / "wiggle.gif")
    write_pipeline(left, right, quilt, args.output_dir / "pipeline.jpg")
    return 0


def eye_frames(source: Path, index: int) -> tuple[Frame, Frame]:
    """タイルへ収めたあとの左眼・右眼を返す。視差推定が見ているのと同じ絵。

    収め方は pipeline の `_FlatFraming` と同じ引数で決める。あちらを変えたらここも変える。
    """
    info = probe(source)
    reader = read_frames(info, start=index, count=1)
    try:
        frame = next(reader)
    finally:
        reader.close()
    left, right = split_stereo(frame, LAYOUT)
    spec = PRESETS[DISPLAY]
    fit = plan_fit(
        left.shape[1],
        left.shape[0],
        pixel_aspect=PIXEL_ASPECT[LAYOUT],
        tile_size=spec.tile_size,
        tile_aspect=spec.aspect,
        mode="crop",
    )
    return fit_content(left, fit), fit_content(right, fit)


def write_wiggle(quilt: Frame, path: Path, *, width: int = 300, samples: int = 11) -> None:
    """quilt の視点を順に切り替えた GIF。実機の見え方に一番近い静止画の代わり。

    66 視点を 1 枚ずつ入れると GIF が 3 MB を超える。芝生のような高周波の絵は
    GIF の圧縮が効かないので、両端を含む 11 視点に間引いて 20 コマにする。
    """
    spec = PRESETS[DISPLAY]
    tile_width, tile_height = spec.tile_size
    height = round(width * tile_height / tile_width / 2) * 2
    views = sweep_views(spec.view_count, samples)

    with tempfile.TemporaryDirectory() as work:
        for position, index in enumerate(views):
            x, y = spec.tile_origin(index)
            tile = quilt[y : y + tile_height, x : x + tile_width]
            save(
                Path(work) / f"{position:03d}.png",
                cv2.resize(to_bgr(tile), (width, height), interpolation=cv2.INTER_AREA),
            )
        palette = f"{work}/palette.png"
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-framerate",
                "12",
                "-i",
                f"{work}/%03d.png",
                "-vf",
                "palettegen=max_colors=128:stats_mode=full",
                "-y",
                palette,
            ]
        )
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-framerate",
                "12",
                "-i",
                f"{work}/%03d.png",
                "-i",
                palette,
                "-lavfi",
                "paletteuse=dither=bayer:bayer_scale=3",
                "-loop",
                "0",
                "-y",
                str(path),
            ]
        )
    report(path, f"{len(views)} frames / {width}x{height}")


def sweep_views(count: int, samples: int) -> list[int]:
    """視点を等間隔に間引いて、端で折り返す並びを返す。

    両端（視点 0 と最後の視点）を必ず含める。外挿した端の視点は穴埋めの粗さが出るところなので、
    そこを見せない GIF は実機の見え方を実物より良く見せてしまう。
    """
    if count < 2 or not 2 <= samples <= count:
        raise ValueError(f"視点の間引きが不正（count={count} samples={samples}）")
    picks = [round(position * (count - 1) / (samples - 1)) for position in range(samples)]
    return picks + picks[-2:0:-1]


def write_pipeline(left: Frame, right: Frame, quilt: Frame, path: Path) -> None:
    """入力ステレオ → 視差 → quilt を横一列に並べた図。パネルの高さを揃える。

    視差は色を入れ替える前の絵から求める。推定器は rgb24 を前提にしている。
    """
    spec = PRESETS[DISPLAY]
    depth = colorize(disparity(left, right))
    eyes = beside([scaled(to_bgr(left), PANEL), scaled(to_bgr(right), PANEL)], gap=6)
    figure = row(
        [
            labelled(eyes, "Stereo input (left / right)"),
            labelled(scaled(depth, PANEL), "Disparity"),
            labelled(
                scaled(to_bgr(quilt), PANEL),
                f"Quilt {spec.columns}x{spec.rows} ({spec.view_count} views)",
            ),
        ],
        captions=["stereo matching", "view synthesis"],
    )
    save(path, figure, cv2.IMWRITE_JPEG_QUALITY, 92)
    report(path, f"{figure.shape[1]}x{figure.shape[0]}")


def disparity(left: Frame, right: Frame) -> np.ndarray:
    return cast(np.ndarray, SgbmDisparityEstimator(DisparityParams()).estimate(left, right))


def colorize(values: np.ndarray) -> np.ndarray:
    """視差を色に置き換える。外れ値で全体が潰れないよう 5〜95 パーセンタイルで伸ばす。"""
    low, high = np.percentile(values, (5, 95))
    span = max(high - low, 1e-6)
    normalized = np.clip((values - low) / span, 0.0, 1.0)
    # cv2 の型定義は戻り値を Any にするので、分かっている型へ読み替える
    return cast(
        np.ndarray, cv2.applyColorMap((normalized * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    )


def scaled(image: np.ndarray, height: int) -> np.ndarray:
    width = round(height * image.shape[1] / image.shape[0])
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)


def labelled(image: np.ndarray, text: str) -> np.ndarray:
    """画像の上にラベルの帯を足す。"""
    height, width = image.shape[:2]
    card = np.full((height + BAR, width, 3), CARD, dtype=np.uint8)
    card[BAR:] = image
    cv2.putText(card, text, (0, BAR - 9), LABEL, 0.4, INK, 1, cv2.LINE_AA)
    return card


def beside(images: list[np.ndarray], *, gap: int) -> np.ndarray:
    height = max(image.shape[0] for image in images)
    width = sum(image.shape[1] for image in images) + gap * (len(images) - 1)
    card = np.full((height, width, 3), CARD, dtype=np.uint8)
    left = 0
    for image in images:
        card[: image.shape[0], left : left + image.shape[1]] = image
        left += image.shape[1] + gap
    return card


def row(panels: list[np.ndarray], *, captions: list[str], gap: int = 92) -> np.ndarray:
    """パネルを横に並べ、間に矢印と処理名を描く。矢印は画像部分の中心に合わせる。"""
    margin = 14
    height = max(panel.shape[0] for panel in panels) + margin * 2
    width = sum(panel.shape[1] for panel in panels) + gap * (len(panels) - 1) + margin * 2
    card = np.full((height, width, 3), CARD, dtype=np.uint8)
    middle = margin + BAR + PANEL // 2
    left = margin
    for position, panel in enumerate(panels):
        card[margin : margin + panel.shape[0], left : left + panel.shape[1]] = panel
        left += panel.shape[1]
        if position < len(captions):
            cv2.arrowedLine(
                card,
                (left + 14, middle),
                (left + gap - 14, middle),
                INK,
                1,
                cv2.LINE_AA,
                tipLength=0.22,
            )
            text = captions[position]
            (text_width, _), _ = cv2.getTextSize(text, LABEL, 0.36, 1)
            cv2.putText(
                card,
                text,
                (left + gap // 2 - text_width // 2, middle - 12),
                LABEL,
                0.36,
                INK,
                1,
                cv2.LINE_AA,
            )
            left += gap
    return card


def to_bgr(frame: Frame) -> np.ndarray:
    """パイプラインは rgb24 を扱うが cv2 の書き出しは BGR 順を前提にする。"""
    return cast(np.ndarray, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))


def save(path: Path, image: np.ndarray, *params: int) -> None:
    # cv2.imwrite は失敗しても例外を投げず False を返す。黙って進むと ffmpeg 側で分かりにくく落ちる
    if not cv2.imwrite(str(path), image, list(params)):
        raise ValueError(f"{path} に書き出せなかった")


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def report(path: Path, detail: str) -> None:
    shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    print(f"wrote {shown} ({detail} / {path.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    sys.exit(main())
