import importlib.util
import json
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path
from types import ModuleType
from typing import cast

ROOT = Path(__file__).resolve().parents[2]


def module(name: str, path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"{path} を読み込めない")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class HarnessTests(unittest.TestCase):
    def test_all_skills_and_agents_have_resolving_adapters(self) -> None:
        for canonical in (ROOT / ".claude/skills").iterdir():
            adapter = ROOT / ".agents/skills" / canonical.name
            self.assertTrue(adapter.is_symlink(), str(adapter))
            self.assertEqual(adapter.resolve(), canonical.resolve())
            self.assertTrue((adapter / "SKILL.md").is_file())
        for canonical in (ROOT / ".claude/agents").glob("*.md"):
            name = canonical.stem.replace("-", "_")
            config = tomllib.loads((ROOT / f".codex/agents/{name}.toml").read_text())
            self.assertEqual(config["name"], name)
            self.assertEqual(config["sandbox_mode"], "read-only")
            self.assertIn(str(canonical.relative_to(ROOT)), config["developer_instructions"])
        config = tomllib.loads((ROOT / ".codex/config.toml").read_text())
        self.assertEqual(config["project_doc_fallback_filenames"], ["CLAUDE.md"])
        self.assertTrue(config["features"]["hooks"])
        self.assertIn("](CLAUDE.md)", (ROOT / "AGENTS.md").read_text())

    def test_permission_conversion_and_unknown_formats(self) -> None:
        sync = module("sync", "scripts/sync-harness.py")
        result = sync.permission_rules(
            {
                "allow": ["Bash(git status:*)"],
                "ask": ["Bash(git push:*)"],
                "deny": ["Bash(git reset:*)"],
            }
        )
        for prefix, decision in [("status", "allow"), ("push", "prompt"), ("reset", "forbidden")]:
            self.assertIn(f'pattern=["git", "{prefix}"], decision="{decision}"', result)
        for entry in [
            "Bash(git reset*)",
            "Bash(git * status)",
            "Read(secret)",
            "Bash(git status; echo hi:*)",
        ]:
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                sync.permission_rules({"allow": [entry]})
        with self.assertRaises(ValueError):
            sync.permission_rules({"defaultMode": "bypassPermissions"})

    def run_hook(self, payload: dict[str, object]) -> str:
        result = subprocess.run(
            [sys.executable, str(ROOT / ".claude/hooks/harness.py")],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        return cast(str, context)

    def test_session_only_loads_unconditional_rules(self) -> None:
        context = self.run_hook({"hook_event_name": "SessionStart"})
        self.assertIn("documentation.md", context)
        self.assertNotIn("viewer-vue.md ---", context)
        self.assertNotIn("converter-python.md ---", context)

    def test_claude_and_codex_load_same_path_rules(self) -> None:
        base = {"hook_event_name": "PreToolUse", "cwd": str(ROOT)}
        claude = self.run_hook({**base, "tool_input": {"file_path": "viewer/src/App.vue"}})
        codex = self.run_hook(
            {
                **base,
                "tool_input": {
                    "command": (
                        "*** Begin Patch\n*** Update File: viewer/src/App.vue"
                        "\n@@\n+x\n*** End Patch"
                    )
                },
            }
        )
        self.assertEqual(claude, codex)
        self.assertIn("viewer-vue.md", codex)
        self.assertIn("external-apis.md", codex)
        self.assertNotIn("converter-python.md ---", codex)

    def test_patch_checks_add_and_move_destination(self) -> None:
        hook = module("hook", ".claude/hooks/harness.py")
        paths = hook.edited_paths(
            {
                "cwd": str(ROOT),
                "tool_input": {
                    "command": "*** Begin Patch\n*** Add File: converter/example.py\n+x\n"
                    "*** Update File: old.vue\n*** Move to: viewer/src/New.vue\n"
                    "@@\n+x\n*** Delete File: gone.vue\n*** End Patch"
                },
            }
        )
        context = hook.rule_context(paths)
        self.assertIn("converter-python.md", context)
        self.assertIn("viewer-vue.md", context)
        self.assertIn(ROOT / "gone.vue", paths)

    def test_malformed_hook_input_fails(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / ".claude/hooks/harness.py")],
            input="{",
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
