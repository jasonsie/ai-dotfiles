---
name: push-branch
description: "Push the branch being landed to origin, refusing a remote branch that diverged. Use when a reviewed branch has to reach origin before its PR, or when an approve run stopped at push."
---

# Push branch

Run `ai-dotfiles git push` (`--dry-run` first when unsure) on the branch, with every change
committed. It is skipped when origin already has this commit or the branch has nothing ahead of
the base.

- **"origin/<branch> is at <sha>, not behind HEAD"**: someone pushed elsewhere. Show the user
  `git log HEAD..origin/<branch>` and let them choose: rebase onto it, or overwrite. Never
  force-push on your own.
