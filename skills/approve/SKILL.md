---
name: approve
description: "Land a branch the user has reviewed and said 'approve' to: commit, PR body, push, approval by this repo's reviewer account, merge commit, archive tag, branch deleted. Use when the user says 'approve', 'land it' or 'ship it' after reviewing agent work on a branch, or when an `ai-dotfiles approve` run stopped and has to be resumed."
---

# Approve

The user reviewed the uncommitted work on this branch and said "approve". Everything after
that is one pipe, and [scripts/approve.py](scripts/approve.py), run as `ai-dotfiles approve`,
does the part that needs no judgment. Never land to `main` directly, never approve as the PR's
author, never invite an account to a repository.

## On "approve"

1. **Commit** per the `small-commits` skill: the plan, then the commits with their trailers.
2. **Write the PR body** per the `pr` skill to a file in the scratchpad; pick a
   `type(scope): outcome` title.
3. **Run** `ai-dotfiles approve --dry-run --title "<title>" --body-file <file>`, read the plan,
   then the same without `--dry-run`. The script pushes, opens or reuses the PR, approves it as
   the repo's reviewer, tags the branch tip `archive/<name>`, merges by merge commit, deletes
   the branch locally and on origin. Report its last line (the PR URL) and `git log --oneline -3`.

## The reviewer

Each repo has its own reviewer account, cached in `git config --local approve.reviewer`.

- **Exit 3** means none is cached: ask the user which GitHub login reviews in this repo, then
  rerun with `--reviewer <login>`. The script checks that login has a `gh auth` token, is not
  the author, and can read the repo before caching it.
- **"cannot read"** means that account is not a collaborator: tell the user to invite it
  (triage is enough) and accept; rerun after. Do not invite it yourself.
- `ai-dotfiles approve reviewer [LOGIN | --unset]` shows, sets or clears the cache.

## When it stops

Nothing is undone. The message names the step and the fix; fix that, rerun the same command,
and the steps already done are skipped (branch pushed, PR open, approved, tagged, merged).
