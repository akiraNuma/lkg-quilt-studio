#!/bin/sh
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"
scripts/check-harness.sh
cd "$repo_root/viewer"
npm run check
cd "$repo_root/converter"
uv run poe check
