---
name: merge-pr
description: "Merge the branch's approved PR by merge commit. Use when an approved PR is ready to land, or when an approve run stopped at merge."
---

# Merge PR

Run `ai-dotfiles git merge` on the branch after it is approved and tagged (`archive-tag`). A
merge commit keeps each small commit in the base's history.

- **"PR #n is dirty"**: conflicts. Merge the base into the branch, resolve with the user, push
  (`push-branch`), rerun.
- **"blocked"**: a check or a required review is missing. `gh pr checks <n>` lists the checks,
  `gh pr view <n> --json reviewDecision` the review. Fix or wait for the check, or get the review
  (`approve-pr`), then rerun.
- **"behind"**: the base requires an up-to-date branch; merge the base in, push, rerun.
