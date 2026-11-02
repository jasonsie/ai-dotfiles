---
name: worktree-guard
description: Finish work in a linked worktree that worktree-guard moved this session into. Use when a worktree-guard message says a worktree is busy or this session was moved, when work in a .claude/worktrees/ folder is done, or when the user asks about agents' linked worktrees (list, merge, rm, release, share).
---

# Worktree guard

Sessions sharing a checkout stay apart. The first session to edit a worktree owns it until it
ends; a second session's first edit there moves that session into a linked worktree,
`.claude/worktrees/<cli>-<session>` on branch `agent/<cli>-<session>`, started from the busy
worktree's last commit. The hook in [scripts/worktree_guard.py](scripts/worktree_guard.py)
does the moving; this skill is what the moved session does.

## Moved

1. **Enter.** Claude Code: call `EnterWorktree` with the path the message gives, then redo the
   change. Codex, Pi and Antigravity: your calls are steered there already; name files by
   their paths there.
2. **Re-read** every file before editing it: the linked worktree holds the last commit, not
   the other session's uncommitted changes.
3. **Base.** Unrelated to the busy branch? Before any edit, restart from the default branch
   with the `reset --hard` command the message gives. Once the task is clear, give the branch
   the repo's name for it: `git -C <linked worktree> branch -m <type>/<slug>`.
4. **Finish.** Done when the work is committed on the branch, `ai-dotfiles worktree done
   "<one-line description>"` has run from the linked worktree, and your final reply names the
   branch, its base, and the person's two commands: `git merge <branch>` in the busy
   worktree, then `ai-dotfiles worktree rm <name>`.

Merging and removing belong to the person: `rm` archives the branch as `archive/<name>`
(the description becomes the tag's) before deleting worktree and branch.

## Commands

`ai-dotfiles worktree list | done | rm | prune | release | share`; `--help` describes each.
`release` (clear a stale owner) and `share` (let every session edit a worktree) are the
person's, run in a terminal; the guard refuses them from an agent, so ask the user.

## Messages

- **Uncommitted changes already there** when you first edit an unowned worktree: leave them
  out of your commits unless your task is to finish them.
- **"worktree-guard failed ... not protected"**: that edit ran unguarded; say so in your reply.
- The guard sees file-edit tools and git; in a busy worktree, change files through those
  rather than `sed -i`, redirects or generators.
