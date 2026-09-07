#!/bin/sh
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"
python="$repo_root/converter/.venv/bin/python"
ruff="$repo_root/converter/.venv/bin/ruff"
mypy="$repo_root/converter/.venv/bin/mypy"
if [ ! -x "$python" ] || [ ! -x "$ruff" ] || [ ! -x "$mypy" ]; then
  printf '%s\n' 'Run uv sync in converter/ before checking the harness.' >&2
  exit 1
fi
# scripts/ falls outside both the converter and viewer checks, so it is checked here.
# ruff reads the root ruff.toml, which extends converter/pyproject.toml.
# mypy's files in converter/pyproject.toml are src / tests, so the target is passed as an argument
"$ruff" format --check scripts
"$ruff" check scripts
"$mypy" --strict --ignore-missing-imports scripts
"$python" scripts/sync-harness.py --check
"$python" scripts/check-translations.py
PYTHONDONTWRITEBYTECODE=1 "$python" -m unittest discover -s scripts/tests -p 'test_*.py'
