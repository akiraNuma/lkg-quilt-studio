#!/bin/sh
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"
python="$repo_root/converter/.venv/bin/python"
if [ ! -x "$python" ]; then
  printf '%s\n' 'Run uv sync in converter/ before checking the harness.' >&2
  exit 1
fi
"$python" scripts/sync-harness.py --check
PYTHONDONTWRITEBYTECODE=1 "$python" -m unittest discover -s scripts/tests -p 'test_*.py'
