---
name: worktree-guard
description: Name work and edit in its own worktree, or finish work in a linked worktree that worktree-guard moved this session into. Use when a worktree-guard message says to name this work, or that a worktree is busy or this session was moved, when work in a .claude/worktrees/ folder is done, or when the user asks about agents' linked worktrees (new, list, merge, rm, release, share).
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

`ai-dotfiles worktree on | off | new | shipped | list | done | rm | prune | release | share`; `--help`
describes each. `shipped` is what `ship` runs. `on`/`off`, `release` (clear a stale owner) and `share` (let every session
edit a worktree) are the person's, run in a terminal; the guard refuses them from an agent,
so ask the user.

## Flow switch

`ai-dotfiles worktree on` sets the local git config `worktree-guard.flow true` in a repo;
`off` removes it; `list` shows `flow: on|off`. In a repo that is on, an edit of a file in the
main checkout (or a git command that changes it) is stopped with "name this work". Reads pass.
The edited file's repo decides, wherever the session started; a file outside git is never
gated. A repo that is off behaves as before.

## Name the work (first edit, repo on)

1. **Name it.** Run `ai-dotfiles worktree new <type>/<slug>` (for example
   `fix/prune-worktrees`; lowercase letters, digits, hyphens). It fetches origin and makes
   `.claude/worktrees/<type>-<slug>` detached at origin's default branch, with no local
   branch, and copies the files `.worktreeinclude` lists. A name taken by that folder, a
   local branch or an origin branch is refused: pick another.
2. **Enter.** The session owns the worktree. Claude Code: call `EnterWorktree` with the path
   the command prints. Codex, Pi and Antigravity: calls that name files in the main checkout
   are moved into the worktree for you; name files by their paths there.
3. **Work there only.** Edit, test and commit in the worktree, on its detached HEAD. The
   main checkout is never edited by an agent, and another session's worktree is refused.
4. **Finish.** Done and committed: run the `ship` skill (`ai-dotfiles ship`). It runs the
   repo's checks, pushes the work as the branch `<type>/<slug>`, opens the PR and deletes
   the worktree; your session is then back in the main checkout, and your next first edit
   starts a new task.
5. **Gone for good.** Work that was never shipped: `list` shows a worktree with no branch as `<type>/<slug> (no branch)`;
   `rm` tags its tip `archive/<slug>`, and refuses unpushed or uncommitted work without
   `--force`.

Run `new` as its own command in the shell, not inside a script or a quoted string: the hook
that binds the worktree to your session reads the command line. Run by hand (no session
bound), it still makes the worktree and prints its path; the first edit there claims it.

## Claude's own worktrees

The installer adds Claude Code `WorktreeCreate` and `WorktreeRemove` hooks (Claude Code only;
no other CLI has them). `claude -w <name>`, `EnterWorktree` with a name and a subagent's
`isolation: worktree` then ask the guard for the worktree:

- **Repo on:** our shape, as `new` makes it: `.claude/worktrees/<name>` detached at freshly
  fetched origin's default branch, no local branch, `.worktreeinclude` copied, owned by the
  session. Remove deletes the folder and its record; commits it made stay under an
  `archive/<name>` tag.
- **Repo off, or any other repo:** what Claude does itself, so nothing changes there:
  `.claude/worktrees/<name>` on a new branch `worktree-<name>` from the session's HEAD.
  Remove deletes the folder and that branch.
- The hook is global, so it runs in every repo. Outside git, or with a name that is not a
  plain folder name, it fails with the reason on stderr and no path; Claude reports the failed
  creation. Asking again for a name that exists returns that worktree untouched.
- Claude does not call remove for a subagent's or a workflow's worktree; they stay until
  someone removes them (`prune`, `rm`).

Desktop's Worktree toggle stays off: whether it fires the hook is untested here (it needs the
Desktop app), so use `worktree new` from a session started in the repo instead.

## Messages

- **Uncommitted changes already there** when you first edit an unowned worktree: leave them
  out of your commits unless your task is to finish them.
- **"worktree-guard failed ... not protected"**: that edit ran unguarded; say so in your reply.
- The guard sees file-edit tools and git; in a busy worktree, change files through those
  rather than `sed -i`, redirects or generators.
