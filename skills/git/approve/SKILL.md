---
name: approve
description: "Land work the user has reviewed and said 'approve' to. 'approve <n>' lands PR n from any session (reviewer approval, archive tag, merge commit, remote branch deleted, main checkout fast-forwarded when safe); plain 'approve' commits and runs the git steps (push, PR, approval, archive tag, merge, prune) for the branch checked out. Use when the user says 'approve', 'approve 57', 'land it' or 'ship it', or when an `ai-dotfiles approve` run stopped and has to be resumed."
---

# Approve

The user reviewed the uncommitted work on this branch and said "approve". Everything after
that is one pipe. The steps that need judgment are skills of their own (`small-commits`,
`pr`); the rest are the six git step skills, which [scripts/approve.py](scripts/approve.py)
runs in order as `ai-dotfiles approve`. Work lands through a PR on its own branch, approved by
an account other than its author.

Two forms, one command:

- **`approve <n>`**: land PR #n from any session. Nothing is local: no branch, no worktree.
  The reviewer account approves, the archive tag is made at the PR's head, the PR is merged
  by merge commit, the remote branch is deleted, and the main checkout is fast-forwarded
  only when git can do it without touching uncommitted files (never a stash or reset;
  otherwise the `main` line says `skipped:` and why). Each step is skipped when done.
- **`approve`** (no number): the one-run form below, for the branch checked out here.

## On "approve <n>"

Run `ai-dotfiles approve <n> --dry-run`, read the plan, then the same without `--dry-run`.
Report its last line (the PR URL) and any `skipped:` line. A stop is resumed as below.

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

By number the steps are reviewer, review, tag, merge, branch (remote branch deleted) and
main (fast-forward); rerun `ai-dotfiles approve <n>`.
