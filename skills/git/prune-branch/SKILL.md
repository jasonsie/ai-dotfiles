---
name: prune-branch
description: "After a merge, check out the base, pull it, and delete the branch locally and on origin. Use when a merged branch is left behind, or when an approve run stopped at prune."
---

# Prune branch

Tag the branch first (`archive-tag`): a deleted branch is kept nowhere else. Then run
`ai-dotfiles git prune` while on the merged branch. It checks out the base, pulls it
fast-forward, and deletes the branch locally and on origin, skipping what is gone already.
