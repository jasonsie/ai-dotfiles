---
name: approve-pr
description: "Approve the branch's PR as this repo's reviewer account, a second GitHub login cached per repo. Use when a PR needs its approval before merging, when no reviewer is cached for a repo, or when an approve run stopped at reviewer or review."
---

# Approve PR

GitHub refuses self-approval, so each repo names its own reviewer login, cached in
`git config --local approve.reviewer`. Run `ai-dotfiles git review`: it approves the branch's
PR with that login's token.

## The reviewer

- **Exit 3**: none cached. Ask the user which GitHub login reviews in this repo, then rerun with
  `--reviewer <login>`. The login is cached once it has a `gh auth` token, is not the PR's
  author, and can read the repo.
- **"cannot read"**: that account is not a collaborator. Ask the user to invite it (triage is
  enough) and accept the invite, then rerun. Repository membership is the user's to change.
- **"no gh token"**: the user logs that account in with `gh auth login`.
- `ai-dotfiles git reviewer [LOGIN | --unset]` shows, sets or clears the cache.
