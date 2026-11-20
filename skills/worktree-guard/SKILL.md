---
name: worktree-guard
description: Name work and edit in its own worktree, and clear linked worktrees. Use when a worktree-guard message says to name this work or that a worktree belongs to another session, when work in a .claude/worktrees/ folder is done, or when the user asks about agents' linked worktrees (new, list, rm, release, share).
---

# Worktree guard

A repo that is off gets nothing from the guard: every edit passes, with no owner and no
message. In a repo that is on (see Flow switch), each task has a worktree and each worktree
one session: the first session to edit a worktree owns it until it ends, and another
session's edit there is refused. The hook in [scripts/worktree_guard.py](scripts/worktree_guard.py)
does the gating; this skill is what a session does.

## Commands

`ai-dotfiles worktree new | pr | shipped | list | done | rm | prune | release | share`; `--help`
describes each. `shipped` is what `ship` runs; `approve`, run inside a worktree, deletes it the
same way once its PR is merged. `release` (clear a stale owner) and `share` (let every session
edit a worktree) are the person's, run in a terminal; the guard refuses them from an agent,
so ask the user.

## Where the work shows

Claude Code's and Antigravity's status lines show the work name while the session has a worktree.
Pi's footer shows it as the `worktree` status. Codex's footer cannot follow a steered session (it
keeps showing the main checkout), so on the session's next tool call after a worktree is made or
deleted the guard tells Codex in one line. Not an error: the notice is how Codex shows it.

## Flow switch

The local git config `worktree-guard.flow true` turns a repo on; unset, it is off. The person
flips it with `/worktree-flow` (the `worktree-flow` skill), never an agent on its own: the guard
refuses an agent's `git config` write of the key. `list` shows `flow: on|off`. In a repo that is on, an edit of a file in the
main checkout (or a git command that changes it) is stopped with "name this work". Reads pass.
The edited file's repo decides, wherever the session started; a file outside git is never
gated. A repo that is off gets nothing: no owner, no move, no message.
In a repo that is on, only the main checkout and the worktrees under `.claude/worktrees/` are gated
or claimed; a linked worktree elsewhere (Codex's or Antigravity's app makes them) is left alone.

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

## Fix an open PR

A first edit with no PR named is a new task. To change a PR that is open, run `ai-dotfiles
worktree pr <n>` instead of `new`: it fetches origin and makes `.claude/worktrees/<branch>`
(slashes become hyphens) detached at the PR's remote branch, with no local branch, bound to your
session as `new` does (enter it the same way). A PR that is not open or comes from a fork is
refused. Commit there, then run the `ship` skill: it pushes to the PR's branch, so the PR
updates, and deletes the worktree. A push that origin refuses, or a branch that moved on, stops
the run and deletes nothing.

Run `new` and `pr` as their own commands in the shell, not inside a script or a quoted string: the hook
that binds the worktree to your session reads the command line. Run by hand (no session
bound), it still makes the worktree and prints its path; the first edit there claims it.

## Leftovers

When a worktree is made, and when a session ends, the guard deletes the linked worktrees whose
owner is gone and that have nothing to lose: no uncommitted or untracked files, and every
commit on a remote-tracking ref (pushed). One nobody has claimed yet is spared for an hour.
A session's end sweeps every repo that is on where it edited, claimed a worktree or ran `worktree
new` or `pr`.
Anything else stays, and `list` marks it `LEFT BEHIND: owner gone, 2 commits not pushed, 1 file
uncommitted`.

- **Take it over.** Enter it (Claude Code: `EnterWorktree` with its path) and make your first
  edit there: you own it, and the guard names the uncommitted files and unpushed commits you
  now hold. Finish or discard them, then push.
- **Or drop it.** `ai-dotfiles worktree rm <name>` archive-tags its tip as `archive/<name>`,
  then deletes it; it refuses unpushed or uncommitted work without `--force`.

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
- **"belongs to ... session"**: another live session owns that worktree; do not edit it, work in
  your own (`worktree new`).
- **"worktree-guard failed ... not protected"**: that edit ran unguarded; say so in your reply.
- The guard sees file-edit tools and git; in a repo that is on, change files through those
  rather than `sed -i`, redirects or generators.

## Older agent worktrees

The guard used to move a second session's first edit into `.claude/worktrees/<cli>-<session>`
on branch `agent/<cli>-<session>`. It no longer makes them; ones already there stay and are
the person's to clear:

- `ai-dotfiles worktree list` shows them; from inside one, `ai-dotfiles worktree done
  "<one-line description>"` records its summary.
- `ai-dotfiles worktree rm <name>` archives the branch as `archive/<name>` (the description
  becomes the tag's), then deletes worktree and branch; merge the branch first
  (`git merge <branch>` in the main checkout), or it refuses an unmerged one without `--force`.
  `prune` removes every merged, clean, unowned one.
