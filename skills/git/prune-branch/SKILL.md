---
name: prune-branch
description: "After a merge, check out the base, pull it, and delete the branch locally and on origin; run in a linked worktree, delete that worktree too, last. Use when a merged branch or its worktree is left behind, or when an approve run stopped at prune."
---

# Prune branch

Tag the branch first (`archive-tag`): a deleted branch is kept nowhere else. Then run
`ai-dotfiles git prune` while on the merged branch. It checks out the base, pulls it
fast-forward, and deletes the branch locally and on origin, skipping what is gone already.

Run in a linked worktree, it detaches there instead, fast-forwards the main checkout when git
can, and deletes the worktree last, so only the archive tag is left. worktree-guard keeps it,
as a `skipped:` line with why, unless the guard made it in a repo whose flow is on, no other
live session owns it, and it holds nothing origin lacks. Deleted: go back as the last line says
(Claude Code: `ExitWorktree` with action `keep`).
