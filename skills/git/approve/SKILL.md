---
name: approve
description: "Land a branch the user has reviewed and said 'approve' to: commit, PR body, then the git steps (push, PR, approval, archive tag, merge, prune) in one resumable run. Use when the user says 'approve', 'land it' or 'ship it' after reviewing agent work on a branch, or when an `ai-dotfiles approve` run stopped and has to be resumed."
---

# Approve

The user reviewed the uncommitted work on this branch and said "approve". Everything after
that is one pipe. The steps that need judgment are skills of their own (`small-commits`,
`pr`); the rest are the six git step skills, which [scripts/approve.py](scripts/approve.py)
runs in order as `ai-dotfiles approve`. Work lands through a PR on its own branch, approved by
an account other than its author.

## On "approve"

1. **Commit** per the `small-commits` skill: the plan, then the commits with their trailers.
2. **Write the PR body** per the `pr` skill to a file in the scratchpad; pick a
   `type(scope): outcome` title.
3. **Run** `ai-dotfiles approve --dry-run --title "<title>" --body-file <file>`, read the plan,
   then the same without `--dry-run`. Report its last line (the PR URL) and
   `git log --oneline -3`.

## When it stops

The message names the step, e.g. `approve stopped at merge: …`. Open that step's skill for
the fix, then rerun the same command; the steps already done are skipped. Nothing is undone.

| Step | Skill | Alone |
|---|---|---|
| reviewer, review | `approve-pr` (exit 3: ask the user for the reviewer login) | `ai-dotfiles git review` |
| push | `push-branch` | `ai-dotfiles git push` |
| pr | `open-pr` | `ai-dotfiles git pr` |
| tag | `archive-tag` | `ai-dotfiles git tag` |
| merge | `merge-pr` | `ai-dotfiles git merge` |
| prune | `prune-branch` | `ai-dotfiles git prune` |
