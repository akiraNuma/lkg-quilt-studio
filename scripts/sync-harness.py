"""Generate and verify only the machine-readable Codex settings from .claude/settings.json."""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def permission_rules(permissions: dict[str, list[str]]) -> str:
    unknown = set(permissions) - {"allow", "deny", "ask"}
    if unknown:
        raise ValueError(f"unsupported permission keys: {sorted(unknown)}")
    lines = ["# Generated from .claude/settings.json. Run python3 scripts/sync-harness.py."]
    for key, decision in [("allow", "allow"), ("ask", "prompt"), ("deny", "forbidden")]:
        entries = permissions.get(key, [])
        if not isinstance(entries, list):
            raise ValueError(f"permissions.{key} must be an array")
        for entry in entries:
            match = re.fullmatch(r"Bash\(([a-zA-Z0-9_./-]+(?: [a-zA-Z0-9_./-]+)*):\*\)", entry)
            if not match:
                raise ValueError(
                    f"permission that cannot be converted automatically: {entry}"
                    " (never skip one silently)"
                )
            pattern = json.dumps(match[1].split())
            lines.append(f'prefix_rule(pattern={pattern}, decision="{decision}")')
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    settings = json.loads((ROOT / ".claude/settings.json").read_text())
    unknown = set(settings) - {"permissions", "hooks"}
    if unknown:
        raise ValueError(f"settings whose Codex support needs checking: {sorted(unknown)}")
    hooks = settings.get("hooks", {})
    for event, groups in hooks.items():
        if event not in {"SessionStart", "PreToolUse", "PostToolUse"}:
            raise ValueError(f"unverified hook event: {event}")
        for group in groups:
            for handler in group["hooks"]:
                if handler.get("type") != "command":
                    raise ValueError("a hook other than command needs its support checked")
                if "CLAUDE_PROJECT_DIR" in handler["command"]:
                    raise ValueError("a shared hook command must resolve from the git root")
    outputs = {
        ROOT / ".codex/hooks.json": json.dumps({"hooks": hooks}, indent=2, ensure_ascii=False)
        + "\n",
        ROOT / ".codex/rules/claude.rules": permission_rules(settings.get("permissions", {})),
    }
    drift = []
    for path, expected in outputs.items():
        if path.exists() and path.read_text() == expected:
            continue
        if args.check:
            drift.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected)
    if drift:
        missing = ", ".join(drift)
        raise ValueError(f"out of sync: {missing}. run python3 scripts/sync-harness.py")
    print("harness adapters OK" if args.check else "harness adapters synced")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"harness sync failed: {error}", file=sys.stderr)
        sys.exit(1)
