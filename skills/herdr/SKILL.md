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
   `flow: on`, split each spawned agent's pane with `--cwd` set to the main checkout (the
   parent of `git rev-parse --path-format=absolute --git-common-dir`), then `agent start`
   in it. Its first edit there is stopped with "name this work", and it makes its own
   worktree with `ai-dotfiles worktree new` and ships its own PR (the `worktree-guard`
   skill). Your own worktree belongs to your session, so an agent started in it has its
   edits refused. Make worktrees with `ai-dotfiles worktree new`: those from
   `herdr worktree` sit outside `.claude/worktrees/`, where the guard does not reach.

## Setup, once per Mac, by hand

Herdr (`brew install herdr`) is a terminal multiplexer for coding agents: a background server
owns the panes and knows which agent runs in each, and its CLI lets one agent split a pane, start
another agent there, prompt it, wait on it and read its output. Herdr itself, its integrations and
`~/.config/herdr/config.toml` are set up by hand on each Mac: Herdr owns those files, and not
every Mac runs it. This repo adds this skill and the `herdr-title` hook, which labels each
agent's row in Herdr's sidebar (its `SKILL.md` has the sidebar lines).

- **Integrations:** `herdr integration install pi`, then `claude`, `codex` and
  `antigravity-cli`. Pi's is an extension, `~/.pi/agent/extensions/herdr-agent-state.ts`, that
  reports Pi's state (working, idle, blocked), which `herdr agent prompt --wait` waits on. The
  other three are a hook script plus Herdr's own entries in the CLI's hook file (Codex also gets
  `[features] hooks = true` in `config.toml`, and asks for the hook's approval in `/hooks`). They
  report the session, so a pane comes back in it after a server restart; Herdr still reads those
  three CLIs' state off the screen. The hooks step of the ai-dotfiles installer finds its own
  entries by their command and leaves Herdr's alone. `herdr integration status` lists them and
  their versions; `herdr integration uninstall <cli>` takes one out.
- **Upgrade:** `brew upgrade herdr`, then install the integrations again so their versions match
  the new binary. The running server keeps the old binary until it restarts (`herdr status`
  shows it). A restart stops every pane's process, the agent's that asked included, so the person
  does it from a terminal outside Herdr, once the integrations are in.
