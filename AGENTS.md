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

The authority for permissions and hooks is `.claude/settings.json`.
Generate Codex machine settings with `python3 scripts/sync-harness.py`.
Validate synchronization, references, and input formats with `scripts/check-harness.sh`.
Execution permission modes and hook trust follow the client's settings.
