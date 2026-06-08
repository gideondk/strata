---
name: strata:promote-to-pr
disable-model-invocation: true
description: Post a session summary as a comment on the open PR for the current branch. Use when the user asks to "share this on the PR", "post a summary", "let reviewers know", "update the PR with what we did", or at the end of substantial work that reviewers should see. Requires `gh` CLI authenticated. Always two-step with --dry-run first. PR comments are visible to the whole team and shouldn't be sent on a single prompt's say-so. NEVER auto-invoke; always confirm with user before posting.
---

# strata:promote-to-pr

Take what just happened in this session, decisions made, files touched,
open questions, anything reviewers should see, and post it as a comment on
the open PR for the current branch.

This is the **deliberate** counterpart to the silent `pr-context/` notes:
it makes Claude's session visible to everyone watching the PR.

## When to use

- After a substantive working session where reviewers should know what
  changed since their last look.
- To leave a "what's left" handoff before stepping away.
- To answer a reviewer's question with context Claude already gathered.

Not for: every small commit. PR comments accumulate quickly, be selective.

## How

User runs `/strata:promote-to-pr [--pr N]`. You:

1. Compose the summary as a focused comment. Markdown, links to commits/
   files where useful, no large diffs. Aim for under 800 chars.
2. Invoke:

```bash
"${CLAUDE_PLUGIN_ROOT}/bin/strata" promote-to-pr --dry-run <<'STRATA_PR_COMMENT'
<summary body>
STRATA_PR_COMMENT
```

3. Read the dry-run output back to the user. They confirm or edit.
4. Re-run without `--dry-run` to post.

This two-step is on purpose. PR comments are public-ish (visible to
Everyone on the PR) and shouldn't be sent on a prompt's say-so.

## Targeting a specific PR

If the branch has multiple PRs (rare) or you want to comment on a different
PR, pass `--pr <number>`.

## Failure modes

- `gh` not installed → script exits 2 with a clear message.
- `gh` not authenticated → same.
- No open PR for the branch → exits 2.
- Network error during `gh pr comment` → exits 1, prints the gh error.
