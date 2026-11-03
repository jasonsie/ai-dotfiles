---
name: archive-tag
description: "Keep a branch's record as an annotated archive/<name> tag at its tip, pushed, before the branch is deleted. Use when a branch is about to be deleted, merged or not, or when an approve run stopped at tag."
---

# Archive tag

Run `ai-dotfiles git tag` on the branch; `--unmerged` when it goes without being merged,
`--description` to say what it was (default: the last commit's subject). A tag already at the
branch tip is reused, and a name taken by another commit gets the date.

This is the one archive format: `approve` and `worktree-guard` import
[scripts/archive_tag.py](scripts/archive_tag.py), and new code that archives a branch imports it
too.
