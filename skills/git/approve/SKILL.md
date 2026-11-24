---
name: approve
description: "Land work the user has reviewed and said 'approve' to. With a PR number ('approve 57') it lands that PR from any session (reviewer approval, archive tag, merge commit, remote branch deleted, main checkout fast-forwarded when safe); plain 'approve' commits and runs the git steps (push, PR, approval, archive tag, merge, prune) for the branch checked out. Run in the work's own linked worktree, either form deletes it last: only the archive tag is left. Use when the user says 'approve', 'approve 57', 'land it' or 'ship it', or when an `ai-dotfiles approve` run stopped and has to be resumed."
---

# Approve

The user reviewed the uncommitted work on this branch and said "approve". Everything after
that is one pipe. The steps that need judgment are skills of their own (`small-commits`,
`pr`); the rest are the six git step skills, which [scripts/approve.py](scripts/approve.py)
runs in order as `ai-dotfiles approve`. Work lands through a PR on its own branch, approved by
an account other than its author.

Two forms, one command:

- **`approve <n>`**: land PR #n from any session. The reviewer account approves, the archive
  tag is made at the PR's head, the PR is merged by merge commit, the remote branch is
  deleted, and the main checkout is fast-forwarded only when git can do it without touching
  uncommitted files (never a stash or reset; otherwise the `main` line says `skipped:` and
  why). Nothing else local changes, unless the run is in PR n's own worktree (below). Each
  step is skipped when done.
- **`approve`** (no number): the one-run form below, for the branch checked out here.

Either form, run in the linked worktree that holds the work, leaves only the archive tag: the
branch deleted (`prune`), the main checkout fast-forwarded (`main`), then the worktree deleted,
last (`worktree`). worktree-guard deletes it only when it made it in a repo whose flow is on, no
other live session owns it, and it holds nothing origin lacks; otherwise the `worktree` line
says `skipped:` and why. A worktree holding other work is never touched; by number, nor is
PR n's own while it holds uncommitted files or commits the PR lacks: its branch and folder stay.

## On "approve <n>"

Run `ai-dotfiles approve <n> --dry-run`, read the plan, then the same without `--dry-run`.
Report its `landed` line (the PR URL) and any `skipped:` line. A last line `Back in ...` means
the session's worktree is gone: Claude Code, call `ExitWorktree` with action `keep` (or `cd`
to the main checkout it names). A stop is resumed as below.

## On "approve"

1. **Commit** per the `small-commits` skill: the plan, then the commits with their trailers.
2. **Write the PR body** per the `pr` skill to a file in the scratchpad; pick a
   `type(scope): outcome` title.
3. **Run** `ai-dotfiles approve --dry-run --title "<title>" --body-file <file>`, read the plan,
   then the same without `--dry-run`. Report its `landed` line (the PR URL), any `skipped:`
   line and `git log --oneline -3`; after a last line `Back in ...`, call `ExitWorktree`
   (action `keep`) first.

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
main (fast-forward), with prune before main and worktree after it in PR n's own worktree;
rerun `ai-dotfiles approve <n>`.

A `worktree` line with `skipped:` is not a stop: the PR has landed. Say why the folder stays;
once it is clean, `ai-dotfiles worktree shipped <folder>` deletes it, with no second tag.
