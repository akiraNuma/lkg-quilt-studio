# Codex project entry point

Read [CLAUDE.md](CLAUDE.md) and `.claude/rules/documentation.md` before working.
They are the authoritative sources for operations, validation, and design decisions.
This file contains only Codex loading instructions.

## Rules to read for each task

The shared hook supplies unconditional rules and rules matching `paths:`.
If hooks are untrusted or disabled, read the references below yourself.
Read the applicable rules before editing, including when working from the repository root.

| Scope | Read |
| --- | --- |
| `viewer/` | `.claude/rules/viewer-vue.md` |
| `converter/` | `.claude/rules/converter-python.md` |
| Looking Glass specifications, models, or external APIs | `.claude/rules/external-apis.md` |

## Skills and review

- `.agents/skills/` contains relative links to `.claude/skills/`.
  Do not copy the authoritative procedures into a second managed source.
- After code changes, pass the mechanical checks in `CLAUDE.md`.
  Then read `.agents/skills/review-loop/SKILL.md` and run the review.
- For harness changes, read `.agents/skills/harness-audit/SKILL.md`.
  Check the consistency of the entry points, references, and settings changed in this task.
- The Codex reviewer is `.codex/agents/code_reviewer.toml`.
  If named agents are unavailable, ask a regular subagent to read
  `.claude/agents/code-reviewer.md` and review without editing files.

## Permissions and hooks

The authority for permissions and hooks is `.claude/settings.json`.
Generate Codex machine settings with `python3 scripts/sync-harness.py`; do not edit
`.codex/hooks.json` or `.codex/rules/claude.rules` by hand.
Validate synchronization, references, and input formats with `scripts/check-harness.sh`.
Hooks and synchronization need Python 3.9 or later on PATH.

In Codex CLI, open `/hooks`, inspect and trust the session-start and pre-edit hooks, then start
a new session. Inspect them again after their definitions change. The pre-edit hook covers
Claude's `Edit` and `Write` and Codex's `apply_patch`; before editing through a shell or another
tool, read the matching rules yourself.

The tracked `.codex/config.toml` sets `approval_policy = "never"` and
`sandbox_mode = "danger-full-access"`, so Codex runs in this repository without approval prompts.
Managed settings and launch options take precedence if you want something stricter.
Checked against `codex-cli 0.153.4`; a passing static check does not prove the client trusted
or executed the hooks. See the [hook documentation](https://learn.chatgpt.com/docs/hooks) and
[permission rule documentation](https://learn.chatgpt.com/docs/agent-configuration/rules).
