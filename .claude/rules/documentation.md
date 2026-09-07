# Single source of truth for documentation and comments (always loaded)

## Where information belongs (one fact, one authority)

| Information | Location |
| --- | --- |
| Setup, CLI usage, and hardware validation | `README.md` |
| Agent operations, validation workflow, and design rationale | `CLAUDE.md` |
| Codex entry point and conditional references | `AGENTS.md` |
| Codex skill discovery and reviewer registration | Relative links in `.agents/skills/` / `.codex/agents/*.toml` |
| Command permissions and hook definitions | `.claude/settings.json` (generate Codex settings with `scripts/sync-harness.py`) |
| Codex execution settings and permission mode | `.codex/config.toml` (tracked in Git) |
| Layer-specific coding conventions | `.claude/rules/*.md` (shared hooks load conditionally; use `AGENTS.md` when untrusted) |
| External reference URLs, candidate models, and known limitations | `.claude/rules/external-apis.md` |
| Review criteria | `.claude/agents/code-reviewer.md` (authoritative; no independent copies) |
| README figures and how to rebuild them | `scripts/make-readme-media.py` (output in `docs/media/`) |
| Tool versions | `.mise.toml` |
| Python formatting and lint settings | `converter/pyproject.toml` (ruff) |
| Same settings for `scripts/` | `ruff.toml` at the root (extends the file above) |
| Web formatting rules | `viewer/.prettierrc` |
| Web lint settings | `viewer/eslint.config.js` |
| UI palette, form appearance, and shared classes | `viewer/src/styles.css` |
| UI text (Japanese / English) | `viewer/src/i18n.ts` |

- Do not transcribe information derivable by searching code, such as detailed directory trees,
  complete CLI argument lists, or type definitions.
- Describe the current state. Keep change history in git log, not in the document body.
- Update the corresponding documentation in the same change as a procedure or specification.

## English authority and the one Japanese translation

Every instruction document — `README.md`, `CLAUDE.md`, `AGENTS.md`, and `.claude/**` — is English only.
**Do not translate instruction documents.** Agents read English, so a translated rule has no reader,
while every English edit would require a second edit to keep the pair honest.
Instruction language does not change the user's conversation language or the code-comment policy below.

`README.ja.md` is the sole exception, because setup and usage are written for people and this repository
is public. Update it in the same change as `README.md`, then run
`python3 scripts/check-translations.py --record` after checking that both languages say the same thing.
`scripts/check-harness.sh` reports drift since that review. Hashes detect unreviewed changes;
they do not prove translation accuracy.

## Let formatters handle formatting

Do not debate indentation, line breaks, or quotes. Follow `ruff format` for Python and Prettier for Web.
**Do not add formatting rules to lint.** Conflicting tools otherwise undo each other's work.
Lint checks bugs and convention violations; formatters handle appearance.

**Formatters cover only `converter/` and `viewer/`.** Root Markdown and harness documents
(`CLAUDE.md`, `.claude/**`, `README.md`) are not checked for formatting by mechanical checks.

## Code comments: omit by default

Do not repeat information already expressed by types, function names, or schemas.

- Comment only where a capable developer would pause and ask why:
  - **WHY:** the reason for an implementation choice.
  - **Non-obvious external specifications:** quilt layout, calibration, or model I/O quirks.
    Include the source URL.
  - **Traps:** why seemingly unnecessary code is required.
- **One line is the default.** If you need three or more, check whether you are explaining WHAT.
- Omit line-by-line translations of code, searchable facts, change histories, and abandoned TODOs.
- **Write code comments in English.** This is a public repository meant to be read by others,
  and instruction documents are English already. UI text in `viewer/src/i18n.ts` keeps its `ja` entries,
  and the converter's runtime messages stay Japanese; neither is a comment.

## Harness self-improvement triggers

Apply these updates within the session in which they occur:

| Trigger | Action |
| --- | --- |
| The user corrects a working policy | Add 1–3 lines preventing recurrence to `CLAUDE.md` or the relevant rule |
| A documented command fails | Replace it with the correct command |
| A non-obvious trap occurs | Add one line to the relevant rule section |
| The user has to explain the same thing twice | Record it in the harness to prevent a third explanation |
| Documentation contradicts reality | Correct or remove it; ask the user if the correct behavior is uncertain |

## Discipline when adding instructions

- Record only facts a capable agent could not otherwise know: project-specific facts,
  observed non-obvious traps, and human decisions. Do not accumulate generic advice.
- **One observed failure, one entry.** Do not add speculative warnings in advance.
- On the second occurrence of the same issue, consider a mechanical check (such as a lint rule)
  instead of another prose warning.
- Check additions for duplication and conflicts, and remove superseded instructions.
  Use the ownership table above to choose the location.
