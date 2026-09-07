#!/usr/bin/env python3
"""Check README.ja.md for changes since its bilingual review."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = Path("docs/translations.json")


# Only the README is translated. Agents do not read translated instruction documents, so adding
# one would only demand a second edit for every English change
# (.claude/rules/documentation.md).
def document_pairs() -> dict[str, str]:
    return {"README.md": "README.ja.md"}


def snapshot(root: Path) -> dict[str, dict[str, str]]:
    return {
        source: {
            "translation": translation,
            "source_sha256": digest(root / source),
            "translation_sha256": digest(root / translation),
        }
        for source, translation in document_pairs().items()
    }


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(root: Path) -> list[str]:
    current = snapshot(root)
    recorded = json.loads((root / REGISTRY).read_text())
    errors = []
    for source in sorted(current.keys() | recorded.keys()):
        if current.get(source) != recorded.get(source):
            errors.append(f"{source}: missing pair or changes since bilingual review")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--record",
        action="store_true",
        help="record hashes only after reviewing both languages for equivalent meaning",
    )
    args = parser.parse_args()
    try:
        if args.record:
            (ROOT / REGISTRY).write_text(json.dumps(snapshot(ROOT), indent=2) + "\n")
            print("Recorded bilingual review hashes. This does not verify translation accuracy.")
            return 0
        errors = check(ROOT)
        if errors:
            print("\n".join(errors), file=sys.stderr)
            print(
                "Update and review both languages, then run"
                " scripts/check-translations.py --record.",
                file=sys.stderr,
            )
            return 1
        print("Document pairs match the recorded bilingual review.")
        return 0
    except (OSError, ValueError, TypeError) as error:
        print(f"translation check failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
