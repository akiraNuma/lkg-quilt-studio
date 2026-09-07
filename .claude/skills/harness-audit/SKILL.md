---
name: harness-audit
description: "Audit project harness documentation (AGENTS.md, CLAUDE.md, .claude, .agents, .codex, README) against implementation and fix drift. Use after a substantial feature or when checking documentation consistency."
---

# harness-audit — audit the harness against implementation

Stale instructions can mislead subsequent work. Compare claims with the actual artifacts.
For a change limited to particular entry points or settings, audit those changes and their references.
For a requested full audit, perform all recurring checks below.

## Procedure

### 1. Extract claims

Find verifiable claims (commands, file paths, function names, procedures, and configuration values) in:

- `AGENTS.md`, `CLAUDE.md`, and `README.md`.
- `.claude/rules/*.md`, `.claude/agents/*.md`, and `.claude/skills/*/SKILL.md`.
- `.agents/skills/` link targets and `.codex/agents/*.toml`.

### 2. Compare with implementation

- Verify that documented commands work; run checks without side effects.
- Search for referenced files, functions, and CLI arguments.
- Check that rule `paths:` match the current directory structure.
- Check that the Codex entry point routes to the relevant rules and relative skill links resolve.
- Check that Codex agent settings refer to the authoritative review criteria.
- Check `README.ja.md` against `README.md` for meaning, plus `scripts/check-translations.py` results.
  No other document has a translation; report one as drift if it appears.

### 3. Classify and fix

| Category | Action |
| --- | --- |
| Stale documentation; implementation is correct | Rewrite the documentation to describe the current state |
| Code violates a correct rule | Fix it, or report a decision that requires the user |
| Unclear which is correct | Ask the user rather than guessing |
| Duplicated authority | Consolidate using the ownership table in `.claude/rules/documentation.md` |

### 4. Recurring checks

Always include these in a full audit:

- Run the commands in the validation workflow in `CLAUDE.md` as written.
- Check that `code-reviewer` criteria fit the current code structure.
- Check that `external-apis.md` URLs work and stated limitations still apply.
- Compare quilt layout claims with actual values for supported devices.

### 5. Report

Briefly report corrected items, remaining discrepancies awaiting decisions,
and items verified to need no change.
