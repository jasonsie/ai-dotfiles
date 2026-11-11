---
name: herdr
description: Drive Herdr, the terminal multiplexer for coding agents, from inside one of its panes. Use only when the user names Herdr or asks to use it to split panes, run commands, or start, prompt, read or wait on other agents.
---

# Herdr

Herdr ships its own skill, matched to the installed binary, and it changes with each release.
This skill is the pointer to it.

1. **Load it.** Run `herdr --skill` and follow what it prints for the rest of the task. It
   opens with the `HERDR_ENV` check: outside a Herdr pane, say so and stop. When `herdr` is
   not on PATH, say Herdr is not installed (`brew install herdr`) and stop.
2. **Spawned agents, worktree flow on.** In a repo where `ai-dotfiles worktree list` shows
   `flow: on`, start each agent you spawn with `--cwd` set to the main checkout. Its first
   edit there is stopped with "name this work", and it makes its own worktree with
   `ai-dotfiles worktree new` and ships its own PR (the `worktree-guard` skill). Your own
   worktree belongs to your session, so an agent started in it has its edits refused. Make
   worktrees with `ai-dotfiles worktree new`: those from `herdr worktree` sit outside
   `.claude/worktrees/`, where the guard does not reach.
