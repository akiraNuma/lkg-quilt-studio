"""Claude / Codex の hook 入力から共通ルールを選ぶ。"""
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]


def edited_paths(payload):
    tool_input = payload['tool_input']
    if not isinstance(tool_input, dict):
        raise ValueError('tool_input must be an object')
    cwd = Path(payload.get('cwd', os.getcwd()))
    if 'file_path' in tool_input:
        names = [tool_input['file_path']]
    else:
        patch = tool_input.get('command', '')
        if not isinstance(patch, str) or not patch.startswith('*** Begin Patch\n'):
            raise ValueError('expected file_path or an apply_patch command')
        names = re.findall(r'^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$', patch, re.M)
    return list(dict.fromkeys((cwd / name).resolve() for name in names))


def rule_context(paths=None):
    sections = []
    for rule in sorted((ROOT / '.claude/rules').glob('*.md')):
        content = rule.read_text()
        match = re.match(r'^---\n(.*?)\n---\n', content, re.S)
        patterns = re.findall(r'^  - ["\'](.+)["\']$', match[1], re.M) if match else []
        if paths is None:
            selected = not patterns
        else:
            relative = [p.relative_to(ROOT).as_posix() for p in paths if p.is_relative_to(ROOT)]
            expressions = [re.escape(glob).replace(r'\*\*/', '(?:.*/)?')
                           .replace(r'\*\*', '.*').replace(r'\*', '[^/]*') for glob in patterns]
            selected = any(re.fullmatch(expression, p) for p in relative for expression in expressions)
        if selected:
            sections.append(f'\n--- {rule.relative_to(ROOT)} ---\n{content}')
    return '\n'.join(sections)


def main():
    payload = json.load(sys.stdin)
    event = payload.get('hook_event_name')
    if event == 'SessionStart':
        context = rule_context()
    elif event == 'PreToolUse':
        context = rule_context(edited_paths(payload))
    else:
        raise ValueError(f'unsupported event: {event}')
    print(json.dumps({'hookSpecificOutput': {'hookEventName': event,
                     'additionalContext': context}}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f'harness hook failed: {error}', file=sys.stderr)
        sys.exit(2)
