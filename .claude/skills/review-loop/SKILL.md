---
name: review-loop
description: "Review lkg-quilt-studio changes with a code-reviewer subagent and repeat review, fixes, and re-review until MUST and SHOULD findings are zero. Use before committing."
---

# review-loop — iterative LLM review

## Prerequisites: mechanical checks first

Pass the mechanical checks for the changed layer before starting. Fix failures first.
For documentation or harness-only changes, verify references, links, and configuration syntax.
In that case, do not report application checks as having passed.

```bash
(cd converter && uv run poe check)   # If converter changed
(cd viewer && npm run check)         # If viewer changed
```

## Loop

1. Ask a `code-reviewer` subagent to review. The authoritative criteria are in
   **this repository's** `.claude/agents/code-reviewer.md`; do not duplicate them here.
   Codex uses `.codex/agents/code_reviewer.toml`.
   If named agents are unavailable, have a regular subagent read the authoritative criteria.
   Include the affected files, completed validation, and unverified scope in the request.
2. Receive findings classified as MUST / SHOULD / NICE.
3. **Stop when MUST and SHOULD are both zero.** Address NICE items within the requested scope.
   Explain deferred items; ask the user only about decisions they own, such as product behavior.
4. Fix remaining findings. Resolve disagreements using facts (code or official references).
   If a finding is a false positive, provide evidence and downgrade it to NICE.
5. Rerun the applicable prerequisite checks after fixes and confirm they pass.
6. Return to step 1.

## Guardrails

- If the same finding recurs twice or the loop exceeds five rounds, stop and consult the user;
  the fixes are not addressing the problem.
- Do not expand scope with unrelated refactoring while addressing findings.
- Check official references before fixing findings involving Looking Glass specifications or model I/O.
