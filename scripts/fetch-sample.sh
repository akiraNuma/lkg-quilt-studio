#!/usr/bin/env bash
# Cut 6 seconds out of the top-and-bottom stereo version of Big Buck Bunny
# (Blender Foundation / CC-BY 3.0) into samples/ for a quick check.
#
# The download is a 434 MB zip, but the mp4 inside carries moov at the front and deflate can be
# decompressed incrementally. Taking only the first 57 MB and expanding it yields the opening
# 90 seconds, so the whole file need not be fetched.
set -euo pipefail

ZIP_URL=https://download.blender.org/demo/movies/BBB/bbb_sunflower_1080p_30fps_stereo_abl.mp4.zip
PREFIX_BYTES=60000000
CLIP_START=53
CLIP_SECONDS=6

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
output=$repo/samples/bbb_stereo_tb.mp4

if [ -f "$output" ]; then
    echo "$output already exists; delete it first to rebuild"
    exit 0
fi

work=$(mktemp -d "$repo/samples/.fetch.XXXXXX")
trap 'rm -rf "$work"' EXIT

echo "1/3 fetching the first $((PREFIX_BYTES / 1000000)) MB"
curl -fL --progress-bar -r "0-$PREFIX_BYTES" "$ZIP_URL" -o "$work/prefix.zip"

echo "2/3 expanding the mp4 inside the zip"
python3 - "$work/prefix.zip" "$work/head.mp4" <<'PY'
import sys, zlib, pathlib

source, target = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
raw = source.read_bytes()
# A local file header is a 30-byte fixed part plus the filename plus the extra field
name_length = int.from_bytes(raw[26:28], "little")
extra_length = int.from_bytes(raw[28:30], "little")
body = raw[30 + name_length + extra_length :]
# The deflate stream is cut short, so the trailing Error is ignored and what decoded is written
target.write_bytes(zlib.decompressobj(-zlib.MAX_WBITS).decompress(body))
PY

echo "3/3 cutting ${CLIP_SECONDS} seconds from ${CLIP_START}s"
relative=${work#"$repo"/}
docker compose --project-directory "$repo" run --rm --entrypoint ffmpeg converter \
    -hide_banner -v error \
    -ss "$CLIP_START" -t "$CLIP_SECONDS" -i "$relative/head.mp4" \
    -map 0:v:0 -map 0:a:0 \
    -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac -b:a 128k \
    -movflags +faststart -y "samples/$(basename "$output")"

echo
echo "done: samples/$(basename "$output") (1920x2160 top-and-bottom, 30 fps)"
echo "convert it: docker compose run --rm converter convert samples/$(basename "$output") --layout tb --span 1.2 --output-dir out"
