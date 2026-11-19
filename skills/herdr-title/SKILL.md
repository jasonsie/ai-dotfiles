---
name: herdr-title
description: "The tag on an agent's row in Herdr's sidebar, such as [GRILLING] or [EXECUTED]. Use when the user asks what a tag means, why one is wrong, stale or missing, or wants the tags or what decides them changed."
---

# Herdr title

Inside a Herdr pane, each prompt the user submits gets one **tag** for its purpose, and
Herdr draws it before the tab's name: `[GRILLING] · herdr-title-hooks`. The hook in
[scripts/herdr_title.py](scripts/herdr_title.py) picks the tag and reports it; the session's
agent does nothing for it. The tags, their meanings and what decides one are
[config/herdr-title.json](../../config/herdr-title.json) in the ai-dotfiles repo, the single
source for every answer below.

## Read a tag

- `[GRILLING]`: the agent is working on a prompt with that purpose. `[GRILLED]`: it stopped,
  and the move is the user's. `[BLOCKED]`: a permission dialog is open. Herdr switches between
  the three from the state it detects.
- A tag's purpose is its `means` under `tags` in the config.
- Herdr's own word (`idle`, `working`) where a tag would be: nothing has tagged the session.

## Who picked it

1. **At once, by the hook:** the prompt is a command word (`commands`: `approve`,
   `approve 57`) or names a skill that has a tag (`skills` for this repo's, `outside` for a
   plugin's or a built-in: `/grilling`, `$tutor`, `/zkfy:zk-note`).
2. **About three seconds later, by Haiku:** every other prompt. The model reads the session's
   current tag, the end of the agent's last message and the prompt, under the instruction in
   `model.ask`. A short answer keeps the tag unless it starts other work: `1` inside a grill
   stays GRILL, `y` to "confirm and I will build it" becomes EXECUTE.
3. **Kept as it was:** a prompt the user did not type (`machine`), a model that answers KEEP,
   a model call that fails.

The tag comes off when the session ends.

## A tag is wrong or stale

Name which of the three cases above produced it, then fix that case's source: the wording of
`model.ask` or of a tag's `means` for a wrong pick by the model; a missing entry in
`commands`, `skills` or `outside` for a prompt that should be tagged at once.

## A tag is missing

Check in this order: the session runs outside a Herdr pane; the CLI is Antigravity, which has
no hook for a submitted prompt; the hooks are not installed (`ai-dotfiles install --dry-run`
lists what is pending) or Codex's are not approved (`/hooks`); the sidebar's rows lack
`state_text` (the lines for `~/.config/herdr/config.toml` are in `docs/how-it-works.md`,
section Herdr); the session has had no prompt since it started.

## Change the tags or what decides them

Edit `config/herdr-title.json` in the ai-dotfiles repo, in a worktree of its own;
`scripts/tests/test_herdr_title.py` checks the file. The hook reads it on every prompt, so the
change is live once the main checkout has it.
