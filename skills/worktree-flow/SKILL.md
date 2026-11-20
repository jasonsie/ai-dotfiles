---
name: worktree-flow
description: Toggle this repository's worktree flow on or off, after the person's yes in a macOS dialog.
disable-model-invocation: true
---

# Worktree flow

The **flow switch** decides whether worktree-guard gates a repo: on, each task works in its own
worktree (the `worktree-guard` skill); off, the default, plain git. This skill is the only way to
flip it, and the person's invoking it is the only reason to.

1. Run `python3 <this skill's folder>/scripts/worktree_flow.py` from the repo (`--repo DIR` for
   another one). It asks "Turn the worktree flow on|off in <repo>?" in a macOS dialog and flips the
   switch only on OK. The dialog is the person's yes: run the script and let it ask, once. Allow
   the command 90 seconds (the shell tool's timeout, where it has one): the dialog waits 60.
2. Report the line it prints: `flow: on|off in <repo>`, or, exit 1, `unchanged` with the reason
   (Cancel, no answer within a minute, or no dialog, for example over SSH).

Done when the person has the new state or the reason it stayed. `ai-dotfiles worktree list` shows
the state at any time.
