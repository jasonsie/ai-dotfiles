# Worktrees per session: design record

Working record of the `grill-with-docs` interview of 2026-11-09. Every branch is settled except
agent-team teammates (parked). Once built, fold it into `docs/how-it-works.md` and delete this
file. Flow page (swimlanes: who runs each step): https://claude.ai/artifact/XnSURY1ovsu8h1MXFKXzdd
Spec: issue #57; tickets #58-#70 (sub-issues of #57, with blocked-by links).

## Requirements (user)

- **R1.** Sessions developing in the same codebase at the same time never interfere.
- **R2.** A finished session's changes end up as a new PR.
- **R3.** Project specific: off unless a project turns it on; a directory with no git repo never
  uses it.
- Simplify: the same work never has a worktree and a branch at the same time.

## Facts, 2026-11-09

- Three tools made worktrees in `.claude/worktrees/`, each with its own names: worktree-guard
  (`<cli>-<id8>`, branch `agent/<cli>-<id8>`; its skill renamed the branch only), Claude Code `-w`
  and `EnterWorktree` (branch `worktree-<name>`), Desktop's Worktree toggle (inferred:
  `claude/<slug>-<hex6>`, or `<adjective>-<name>-<hex6>`).
- An owner held a checkout until its process ended. The owners of the ai_dotfiles and CS main
  checkouts were alive and in use for days, so every other session that edited was moved.
- Split-pane agent-team teammates counted as other sessions and were moved away from their lead.
- `approve` run inside a linked worktree detached HEAD and deleted the branch but kept the folder
  (CS: PRs #6, #7, #8).
- `ai-dotfiles worktree rm | prune` ran only by hand; prune skipped owned worktrees.
- Of about 50 local repos plus CS, 13 have no GitHub origin; 4 have an `approve` reviewer
  (ai_dotfiles, zkfy, web-clipper, CS).
- Docs (`docs/upstream/claude/`): `WorktreeCreate` replaces worktree creation for `-w`,
  `EnterWorktree` and subagent `isolation: worktree`; the hook picks the path and makes any
  branch itself; Desktop's toggle is not mentioned. Desktop runs the user's hooks. Claude's and
  Antigravity's status line payloads carry `session_id`. Codex's footer has fixed items only;
  Codex and Antigravity hooks cannot change a session's folder.

## Decisions

### The flow, in a repo that is on

- **D1. A session works in its own worktree with no branch; a branch exists only for the PR.**
  While working, the worktree sits on its start commit with no local branch. When done, its
  commits are pushed as a new branch and the PR opens. Why (user): R1 needs a separate folder per
  session; R2 needs a branch name only at the end. Fork then reads: Worktrees = sessions working,
  Branches = main only, origin = one branch per open PR. Replaces the split (first session in the
  main checkout, the rest moved) and, in repos that are on, the memory rule branch-before-changes.
- **D2. The worktree is made on the session's first edit, from a freshly fetched origin/main.**
  Sessions that only read never make one. Why: the same behavior in all four CLIs with the guard
  that exists; every PR targets main, and the main checkout can lag. Accepted: Codex, Pi and
  Antigravity are steered, so their own folder stays the main checkout (D8).
- **D3. The worktree is deleted when its PR opens;** the session returns to the main checkout.
  Why (user): never a worktree and a branch for the same work at once.
- **D4. To fix an open PR, the agent names it first** (`ai-dotfiles worktree pr <n>`): a worktree
  from the PR's branch; the push updates the PR; the worktree is deleted after the push. A first
  edit with no PR named is a new task. Why: the guard cannot tell a fix from a new task, and long
  sessions move on to new tasks. Accepted: a forgotten step opens a duplicate PR, easy to close.
- **D5. One name per piece of work, `<type>/<slug>`, picked by the agent at its first edit.** The
  guard stops the first edit and asks for `ai-dotfiles worktree new <type>/<slug>`; the folder is
  `.claude/worktrees/<type>-<slug>` and the PR branch `<type>/<slug>`; a PR fix names its folder
  after the PR's branch. Why: the folder is what Fork shows while a session works, the branch what
  it shows after; one readable name links the two.
- **D6. Other tools: hook what we can, switch off what we cannot.** A Claude `WorktreeCreate` hook
  makes `-w`, `EnterWorktree` with a name and subagent worktrees our way; a `WorktreeRemove` hook
  deletes the folder. Desktop's Worktree toggle stays off (its default); the guard gives Desktop
  sessions a worktree on the first edit. The Codex and Antigravity apps keep theirs outside the
  repo: left alone, documented. Accepted: the Desktop toggle is a habit nothing can enforce.
- **D7. Leftovers: deleted automatically when nothing would be lost; the rest flagged.** When the
  guard makes a worktree, and when a session ends, it deletes worktrees whose owner is gone, with
  no uncommitted or untracked files and every commit on GitHub. The rest are flagged in
  `ai-dotfiles worktree list`; the person resumes one or runs `rm`, which archive-tags first.
- **D8. Visibility: the status line where we draw it, a notice where we cannot.** Claude and
  Antigravity run our status line script, which shows the work name (for Antigravity by asking
  the guard with the payload's `session_id`). Pi's footer status comes from our Pi extension.
  Codex gets a one-line `systemMessage` when a worktree is made or deleted; the gap is documented.
- **D9. The agent ships; the person approves by PR number.** Ship, by the agent once its task is
  done: the repo's checks, commit, push the worktree as branch `<type>/<slug>`, open the PR with
  its body, delete the worktree, report the link. Approve, when the person says "approve <n>",
  from any session: reviewer-account approval, archive tag, merge commit, remote branch deleted,
  main checkout fast-forwarded when git can do it safely. In repos that are on, replaces the
  rule "push or open a PR only when asked".

### The project switch (R3)

- **P1. The switch is a per-repo git setting,** written by `ai-dotfiles worktree on` with
  `git config --local`, removed by `off`, shown by `ai-dotfiles worktree list`. Why: the same
  place and style as `approve.reviewer`; nothing committed in each project; cloud sessions never
  see it. Rejected: an AGENTS.md line (read by cloud sessions without our hooks); a list in
  `config/` (breaks "per-project rules belong to each project"; would publish private repo names).
- **P1b. Only the person flips it.** The guard refuses `worktree on|off` from an agent, as it does
  `release` and `share`.
- **P2. A repo that is off gets nothing:** plain git; no owner, no move, no warning. The guard's
  move-on-clash and its `agent/<cli>-<id8>` worktrees are retired. Accepted: R1 is not guaranteed
  there; `worktree on` is the fix.
- **P3. The trigger is the edited file's repo:** an edit starts the flow exactly when the file
  sits in a git repo whose setting is on, wherever the session started.
- **P4. Rollout:** ai_dotfiles when the build lands; zkfy, web-clipper and CS after a few days
  without surprises.

### Confirmed with the user

- **A1.** Ship runs the repo's own checks first (its AGENTS.md "Verify"); a failure stops it.
- **A2.** Repos that are off keep today's habit: a new branch in the main checkout, edits left
  uncommitted.
- **A3.** The one-run `approve` retires once all four repos are on.
- **A4.** After the build, one cleanup by hand of today's leftover worktrees, sparing those with
  uncommitted work.
- `approve` fast-forwards the main checkout only when git can without touching uncommitted
  files; it never stashes or resets.
- **A5** (2026-11-09). Approve's last step, run in the work's own worktree, deletes it after
  the branch: only the archive tag is left. Why (user): CS PRs #11 and #12 landed through the
  one-run `approve`, which left each worktree detached on disk.

## Birdview

```
BIRDVIEW: one task in a repo with the flow on     [Dn][Pn] = decision · (R1)(R2) = goals

ANY EDIT ─► is the file in a git repo whose setting is on?                             [P3]
            no repo, or off ──► plain edit, nothing else                           [R3][P2]
            on ──► the flow below · on/off: ai-dotfiles worktree on|off, you only [P1][P1b]

YOUR MAIN CHECKOUT  always on main · your editor, Obsidian, Fork · no agent edits it     [D1]
 │  ▲
 │  └──── fast-forward after a merge, only when git can do it safely ────────────────────────┐
 ▼                                                                                           │
SESSION STARTS   reads freely in the main checkout; no worktree yet                          │
 │                                                                                           │
 ▼ 1st edit                                                                                  │
NAME + WORKTREE  the guard stops the edit: "name this work"                            [D5]  │
 │               agent: ai-dotfiles worktree new fix/prune-wt                                │
 │               git fetch → .claude/worktrees/fix-prune-wt from origin/main,                │
 │               no branch                                                         [D1][D2]  │
 │               Claude moves in · Codex, Pi, Antigravity are steered                  [D2]  │
 │               status line shows fix/prune-wt · Codex gets a notice                  [D8]  │
 ▼                                                                                           │
WORK             edit · test · commit, only in its own folder                          (R1)  │
 │                                                                                           │
 ▼ done, checks pass                                                                         │
SHIP (agent)     push as branch fix/prune-wt → PR #57 opens                       [D9] (R2)  │
 │               worktree deleted · session back in the main checkout                  [D3]  │
 ▼                                                                                           │
REVIEW (you)     on GitHub, or in Fork under origin/fix/prune-wt                             │
 │   comment? ──► FIX   ai-dotfiles worktree pr 57                                     [D4]  │
 │                      worktree from origin/fix/prune-wt · edit · commit · push             │
 │   ◄──────────────    #57 updated · worktree deleted                                       │
 ▼ you: "approve 57"                                                                         │
APPROVE          from any session: reviewer account approves · archive tag             [D9]  │
                 merge commit · origin/fix/prune-wt deleted ─────────────────────────────────┘

SIDE PATHS
 session dies mid-work ──► sweep when a worktree is made or a session ends             [D7]
                           nothing to lose → deleted
                           work at risk → flagged in `worktree list` → resume, or rm (tag)
 other creators ─────────► claude -w · EnterWorktree name · subagent isolation
                           → WorktreeCreate hook → the same shape                      [D6]
                           Desktop: Worktree toggle off → the guard handles it
                           Codex and Antigravity apps: outside the repo, left alone

FORK AT ANY MOMENT
 Worktrees ── one row per session still working, named like its future branch
 Branches ─── main only
 Remotes ──── origin/<type>/<slug>, one per open PR

ROLLOUT  ai_dotfiles on first → zkfy, web-clipper, CS after a few days                 [P4]
```

## Terms

- **Main checkout:** the repo's original folder; the one the editor, Obsidian and Fork open.
- **Worktree:** an extra working folder of the same repo (`git worktree add`), with its own files
  and current commit; ours sit in `.claude/worktrees/`.
- **Work name:** the `<type>/<slug>` an agent picks at its first edit; the worktree folder and the
  PR branch are named from it.
- **Flow switch:** the per-repo git setting that turns the flow on.
- **Owner:** the session that made a worktree and edits in it, until the session ends.
- **Ship:** the agent's last step for a task: push, open or update the PR, delete the worktree.
- **Leftover:** a worktree whose owner is gone.

## Work, in order

1. Land `feat/statusline` (D8 builds on it).
2. The switch: `ai-dotfiles worktree on|off`, person-only, shown in `list` (P1, P1b).
3. The guard: gate on the switch (P2, P3); the first edit stops and asks for `worktree new`; a
   worktree from fetched origin/main with no branch; move-on-clash retired (D1, D2, D5).
4. Ship: checks, push as `<type>/<slug>`, PR, worktree deleted (D3, D9, A1).
5. `ai-dotfiles worktree pr <n>` (D4).
6. `approve <n>`: by PR number; fast-forward when safe (D9, A3).
7. The sweep and the flags in `list` (D7).
8. Claude's `WorktreeCreate` and `WorktreeRemove` hooks (D6).
9. The status line work name, Pi's footer status, Codex's notice (D8).
10. Docs and skills: a `docs/how-it-works.md` section and glossary terms, the worktree-guard and
    approve skills, the memory rule for repos that are on (A2).
11. Rollout and the one cleanup (P4, A4).

## Open

- Agent-team teammates: parked (user).
- The ship command's name.
- Whether `WorktreeCreate` fires for Desktop's Worktree toggle (test when building).
