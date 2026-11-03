---
name: open-pr
description: "Open the branch's pull request from a title and a body file, or reuse the one already open. Use when a pushed branch needs its PR, or when an approve run stopped at pr."
---

# Open PR

1. Write the body per the `pr` skill to a file in the scratchpad; pick a
   `type(scope): outcome` title.
2. Run `ai-dotfiles git pr --title "<title>" --body-file <file>`. An open or merged PR for the
   branch is reused, and the title and body are then ignored. It prints the PR's URL.

- **"no commits ahead … nothing to land"**: the branch has nothing of its own; tell the user.
