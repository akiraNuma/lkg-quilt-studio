import json
import tempfile
import unittest
from pathlib import Path

from test_harness import ROOT, module

translations = module("translations", "scripts/check-translations.py")


class TranslationTests(unittest.TestCase):
    def test_repository_translations_are_reviewed(self) -> None:
        self.assertEqual(translations.check(ROOT), [])

    def test_only_the_readme_is_translated(self) -> None:
        # 指示文書の訳は置かない（.claude/rules/documentation.md）。docs/ja が復活したら落とす
        self.assertEqual(translations.document_pairs(), {"README.md": "README.ja.md"})
        self.assertFalse((ROOT / "docs/ja").exists())

    def test_translation_stays_outside_agent_entry_points(self) -> None:
        for target in translations.document_pairs().values():
            path = Path(target)
            self.assertNotIn(path.name.casefold(), {"agents.md", "claude.md"})
            self.assertNotIn(path.parts[0], {".claude", ".agents", ".codex"})
            self.assertFalse((ROOT / path).read_text().startswith("---\n"))

    def test_changes_in_either_language_require_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            for source, target in translations.document_pairs().items():
                (root / source).write_text("English source\n")
                (root / target).write_text("日本語訳\n")
            (root / translations.REGISTRY).write_text(json.dumps(translations.snapshot(root)))
            self.assertEqual(translations.check(root), [])
            for path in ("README.md", "README.ja.md"):
                original = (root / path).read_text()
                (root / path).write_text("changed\n")
                self.assertTrue(translations.check(root))
                (root / path).write_text(original)

    def test_missing_translation_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs").mkdir()
            (root / "README.md").write_text("English source\n")
            (root / translations.REGISTRY).write_text("{}")
            with self.assertRaises(FileNotFoundError):
                translations.check(root)


if __name__ == "__main__":
    unittest.main()
