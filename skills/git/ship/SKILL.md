---
name: ship
description: "Finish your own work in a worktree made by `worktree new` or `worktree pr`: run the repo's checks, push it as a new branch <type>/<slug> (or onto the open PR's branch), open the PR (or update it), delete the worktree. Use when your task in such a worktree is done and committed, or when an `ai-dotfiles ship` run stopped. Not for the user's 'approve' (that is the approve skill)."
---

# Ship

For the agent, once its task is done and committed in the worktree `ai-dotfiles worktree new
<type>/<slug>` made. The person then reviews the PR and says "approve <n>" (`approve` skill).

1. **Commit** per the `small-commits` skill. Nothing tracked may be left uncommitted.
2. **Write the PR body** per the `pr` skill to a file in the scratchpad; pick a
   `type(scope): outcome` title.
3. **Run, from inside the worktree**, `ai-dotfiles ship --dry-run --title "<title>" --body-file
   <file>`, read the plan, then the same without `--dry-run`.
4. **Report** its link line (`shipped <url>`). Then go back: Claude Code, call `ExitWorktree`
   with action `keep` (or `cd` to the main checkout the last line names); the other CLIs need
   nothing. Your next first edit starts a new task: name it with `worktree new`.

`ship` runs, in order, each step skipped when already done:

| Step | What |
|---|---|
| preflight | no tracked changes; commits ahead of the default branch |
| checks | the commands of the repo's `AGENTS.md` "Verify" block, run in the worktree; a repo with no Verify block stops here unless `--no-checks` |
| push | HEAD as the new branch `<type>/<slug>` (the work name); a branch of that name already on origin at another commit is refused |
| pr | the PR against the default branch (`open-pr`); one already open is reused |
| worktree | deleted once the PR exists, by `worktree shipped`; your session's record of it is cleared |

## Fixing an open PR

In a worktree `ai-dotfiles worktree pr <n>` made, the same command, with no `--title` or
`--body-file`: `ship` pushes to the PR's own branch, so the PR updates and no new PR opens, then
deletes the worktree. Only this worktree may push to a branch already on origin, and only as a
fast-forward of it: if the branch moved on, fetch it, merge or rebase it in, commit and rerun. A
PR no longer open, or no commit on top of the branch, stops the run.

## When it stops

The message names the step, e.g. `ship stopped at checks: ...`; nothing is undone.

- **preflight, the work name is not `<type>/<slug>`**: the worktree was made by `claude -w foo` or
  by a subagent, so its name is Claude's, never a branch. Rerun with `--work <type>/<slug>`.
- **checks**: the message names the failing command. Fix it in the worktree, commit, rerun.
  Nothing was pushed. "No Verify block": the repo has no checks to run; ask the user whether to
  add one or ship with `--no-checks`.
- **push, origin has the branch** (PR fix): it moved on, or origin refused the push (a protected
  branch). Nothing is deleted; fix the cause and rerun.
- **push, origin already has the branch**: the name is taken. Start the work under another name
  (`worktree new`), moving the commits there.
- **pr**: see `open-pr`; the branch is pushed, rerun once fixed.
- **worktree, kept**: the PR is open but the worktree holds uncommitted files or a commit on no
  remote. Deal with it, then `ai-dotfiles worktree rm <folder>`.

The archive tag is not made here; `approve <n>` makes it at the PR's head.
