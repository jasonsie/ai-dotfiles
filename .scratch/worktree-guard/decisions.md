# Session branch decision: grilling state

Status: interview finished; decisions 1-17, defaults and open risks confirmed by the owner
(2026-11-02). Next: `setup-agent-skills` (no issue tracker configured), then `to-spec`,
`to-tickets`; first ticket: check whether Codex runs hooks inside its sandbox.

Feature: a new session switches to a new branch, or stays, by the model's decision.

## Priorities (user, after Q13)
1. Agents develop in the same codebase at once without interfering (no conflicts), and the
   isolation triggers automatically: no manual step by a person.
2. Then: a person can diagnose the history (who did what, where, when).
Consequence: decision 6 (restart by hand) is reopened; 8 and 10 stay (after isolation) and get
a history question.

## Terms (agreed, git's own; `git help gitglossary`)
- **worktree**: any folder where the repository's files are checked out, with its own HEAD
  and index; history (`.git`) is shared with the repository's other worktrees.
- **main worktree**: the original project folder. **linked worktree**: one added by
  `git worktree add` or a CLI's `--worktree`. **busy worktree**: owned by a live session.
- **working tree**: the checked-out files inside one worktree. Ownership is per worktree.

## Research (2026-10-30)
- native-features.md: per-CLI flags, hooks, extension events. Correction: Pi's
  `ctx.sessionManager.getBranch()` is the session-tree branch, not git.
- prior-art.md: tools, hooks, rules. Verified: mcouthon/agents ADR-017 (a SessionStart
  heuristic was removed because the model cannot see concurrent sessions);
  awesome-claude-hooks (auto-create-branch at Stop, protect-main, stash-guard).

## Facts found during the interview
- Codex `workspace-write` sandbox: `.git` is read-only, so `git worktree add` mid-session needs
  an approval; `codex --worktree` at launch works (codex/agent-approvals-security.md:292).
- Claude: `EnterWorktree` moves a live session into `.claude/worktrees/` with no prompt
  (claude/worktrees.md:47). The only CLI that can move a session mid-flight natively.
- End-of-session events: Claude/Codex `SessionEnd`, Pi `session_shutdown`; Antigravity hooks
  have none, so a crashed or Agy session must be detected by a dead PID.
- Antigravity hook input carries `conversationId`, no PID per conversation and no end event: an
  Agy claim cannot be proven dead while the app runs (antigravity/hooks.md:233,255).
- Moving a live conversation: `codex resume <id> --worktree` (or `-C <dir>`) resumes a Codex
  session in a new worktree; Pi `pi --session <path|id>` reopens a session from another cwd.

## Decisions
1. Problem reframed (user, Q1): not "which branch" but concurrent sessions in one worktree
   scrambling each other's uncommitted changes. Goal: no two live editing sessions share a
   worktree. Q1 options (hook facts + rule, rule only, hook decides, guard) rejected as
   not solving this.
2. Isolation point (Q2, recommended accepted): detect, then block. Sessions register per worktree;
   a pre-edit hook blocks a second live session's edits in a busy worktree with a message to
   move to a new linked worktree. Claude moves itself (`EnterWorktree`); others relaunch (`--worktree` or a
   helper). The first session is never disturbed; works for any launch method.
3. Ownership (Q3, recommended accepted): a session owns a worktree from its first edit until
   it ends or its process is gone; idle never releases. Read-only sessions never block. An
   Antigravity owner holds until the app quits or a manual release (so a release command is
   required).
4. What counts as an edit (Q4, recommended accepted): file-edit tools (Claude Edit/Write/
   NotebookEdit; Codex apply_patch; Pi edit/write; Agy write_to_file/replace_file_content/
   multi_replace_file_content) plus git commands that change the tree or index (checkout,
   switch, stash, reset, restore, clean, add, rm, mv, commit, merge, rebase, pull, cherry-pick,
   revert, apply). Other shell writes pass; the block message names that gap. Same list both
   claims ownership and is blocked for others.
5. Subagents (Q5, recommended accepted): share their parent's ownership. Claude and Codex
   subagents carry the parent session id; a CLI started inside an owner session (`pi -p`,
   `claude -p`, `codex exec`) is matched by process ancestry. Agy `inherit` subagents cannot be
   linked: treated as separate, told to use `Workspace: branch`. Parallel children colliding is
   the parent's job.
6b. Moving, revised (Q6 reopened, recommended accepted): automatic redirect inside the session,
    only on a clash. At a session's first edit in a busy worktree the hook creates the linked
    worktree itself (from the busy branch's last commit) and points that session's tool calls
    there from then on: Claude moves with `EnterWorktree`; Codex, Pi and Agy get reads, edits
    and shell commands rewritten (Codex `updatedInput`, Pi `tool_call` input, Agy `overwrite`).
    The hook tells the model once where it now works; an unrelated task restarts its linked
    worktree from the default branch (keeps 7). A session alone never moves. No person acts.
    Ripple: 2's "block" becomes "redirect"; 4's list is what gets redirected; reads are
    redirected too once a session has moved. Risk to verify: Codex hooks inside the sandbox.
6. SUPERSEDED by 6b. Was: Moving (Q6, recommended accepted): non-Claude sessions restart in the new linked worktree,
   keeping the conversation; the block message prints the exact command (Codex `codex resume`,
   Pi `pi --session <file>` after the `ai-dotfiles worktree` helper, Agy `agy --conversation
   <id> --cwd <dir>`, unverified, else a new conversation). Claude moves itself. No in-place
   move. Exact per-CLI commands depend on Q7 (base).
7. Base (Q7, recommended accepted): the model decides per task from git facts in the block
   message: continues the busy worktree's branch -> start from that branch's last commit;
   unrelated -> start from the default branch, freshly fetched. Never copy the owner's
   uncommitted changes. Every move goes through `ai-dotfiles worktree --base <ref>`; Claude
   enters the result by path (`EnterWorktree` path form, under `.claude/worktrees/`); Codex
   reopens with `codex resume <id> -C <path>`, not `--worktree`.

## Facts for the return (Q8)
- Git refuses to move a branch checked out in another worktree: `git branch -f`, `git fetch .
  a:b`, `git push . a:b` all fail (tested). Work lands on the owner's branch only by a merge
  run inside the owner's worktree.
8. Return (Q8, recommended accepted): leave and report. The session commits on its own branch;
   its final reply gives branch, base, and the exact command to bring it back (`git merge
   <branch>` in the target worktree, or `gh pr create`). Never merged automatically.

## Facts for location and cleanup (Q9, Q10)
- Claude's `EnterWorktree` path form skips the approval prompt only under the repository's
  `.claude/worktrees/`; elsewhere it prompts every time, only `bypassPermissions` skips it.
- Claude's exit cleanup and periodic sweep cover only worktrees Claude itself created; it
  advises ignoring `.claude/worktrees/` (claude/worktrees.md:39,58,133).
- `.worktreeinclude` (gitignore syntax) copies gitignored files such as `.env` into worktrees
  Claude creates; a helper-made worktree must copy them itself (claude/worktrees.md:194).
9. Location (Q9, recommended accepted): every CLI's linked worktrees live at
   `.claude/worktrees/<name>` inside the repo; the helper adds that path to
   `.git/info/exclude` (local, never committed). Claude enters without a prompt.
10. Cleanup (Q10, recommended accepted): manual. `ai-dotfiles worktree list` (owner, branch,
    base, merged), `rm <name>` (removes worktree + branch only if nothing is lost: clean, and
    merged or pushed; else refuses with the reason; `--force` overrides), `prune` (all merged,
    clean, unowned). The session's final report puts the `rm` command after the merge command.
11. Ignored files (Q11, recommended accepted): the helper honors `.worktreeinclude` (Claude's
    gitignore-syntax rules: copy only listed files that are gitignored), nothing else. The
    session installs dependencies itself; the move message says so.
12. Leftovers (Q12, recommended accepted): a first edit in an unowned worktree that already
    has uncommitted changes goes through and claims it; the hook adds a one-time note (N files,
    last owner and when it ended; check `git status`, keep them out of commits unless the task
    is to finish them). Advice, not a block.
13. Overrides (Q13, recommended accepted): two terminal-only commands, `ai-dotfiles worktree
    release [<path>]` (clear a stale or crashed owner) and `share [<path>]` (any session may
    edit until the current owner ends). The block message names both; the guard refuses them
    when an agent runs them from its shell. No per-repo opt-out.

14. History record (Q14, user: "we use tag only"): git tags are the only record, in the
    owner's existing convention: annotated `archive/<branch name minus type prefix>` (date
    suffix when the name recurs, e.g. `archive/upstream-sync-2026-10-26`), message "Archive of
    branch <branch> (<dates>; <one-line description>), kept before the branch was merged and
    deleted.", pushed to origin (all 4 existing archive tags are on GitHub). No commit
    trailers, no git notes, no event log; Q8's merge command gets no `--no-ff`. Ripple: Q10's
    `rm`/`prune` create the archive tag before deleting a branch.
15. Tag content (Q15, recommended accepted): the owner's format plus one agent line:
    "Agent: <cli> <model>, session <id>; redirected from branch <busy branch>." The session
    leaves a one-line description at its end for the tag to use; no machine paths. `rm`/`prune`
    push the tag to origin when a remote exists.
16. Packaging (Q16, option 1 with a change by the user): a skill folder for the guard
    (`SKILL.md` + `which-skill` entry; `ai-dotfiles worktree ...`), installers generalized to a
    list of features, but do not copy daily-log's plumbing: extract what both features share
    into one shared module that daily-log moves onto too. Scope of that module: Q16b.

16b. Shared module (Q16b, delegated: "encapsulate the module"; option 1 chosen by the agent):
    one deep module (`scripts/agent_hooks/`, name open) hides everything CLI-specific: reading
    each CLI's hook input into one event (session, folder, tool kind edit/read/shell/other,
    target paths, shell command), writing a small reply set back in each CLI's format (none,
    note, continue the turn, deny, rewrite), per-session state, the runner with a per-feature
    failure policy, the install table (native events and matchers per CLI), and one Pi
    bridge extension. daily-log and the guard keep only their own logic and declare the
    events they want; daily-log moves onto it in this work, its tests guarding the move.

17. Guard failure (Q17, recommended accepted): fail open, visibly. The edit proceeds and the
    session gets a one-line warning ("worktree guard failed: <reason>; this edit was not
    protected"). The shared runner enforces this for every CLI (Pi's bridge catches errors).

## Defaults proposed for confirmation (not asked one by one)
- Non-git folders: the guard does nothing.
- Auto-created branch: `agent/<cli>-<session id, first 8>`; the model renames it to the repo's
  convention (e.g. `feat/<slug>`) when it settles the base.
- Claude: the clashing edit is denied with "EnterWorktree <path>" (the hook already made the
  linked worktree); no rewriting for Claude. Codex/Pi/Agy: shell commands run in the linked
  worktree; relative paths get its prefix, absolute main-worktree paths are re-pointed.
- A clash inside a linked worktree still creates the new one under the main worktree's
  `.claude/worktrees/`, never nested.
- State (operational, not a history record): `~/.local/state/ai-dotfiles/worktree-guard/`.
- Release: Claude/Codex `SessionEnd`, Pi `session_shutdown`, plus a dead-process check (CLI
  process found from the hook's parents); Agy by manual release or app quit.
- Pre-tool hook timeout 60 s (creating a worktree in a big repo), daily-log keeps 10 s.
- No rule in `config/global-agents.md`; hook messages and the guard's SKILL.md instruct.
- Codex needs a one-time hook trust review in `/hooks`, as daily-log does.
- Names: feature `worktree-guard`, shared module `scripts/agent_hooks/`.

## Open risks (verify first when building)
- Codex hooks may run inside the sandbox; then the hook cannot `git worktree add` without an
  approval, breaking priority 1 for Codex. Fallback to decide with the owner if so.
- Rewriting edge cases: shell commands naming the main worktree by absolute path, `cd ..`,
  `git -C`; Codex `apply_patch` paths live in the patch headers.

## Facts for the shared module (Q16b)
- daily_log.py's hook half (~lines 245-372) is CLI plumbing, not journal logic: per-session
  state (state_dir/state_file/load/save/prune), input reading (session_of, tool_of,
  EDIT_TOOLS per CLI), reply writing (proceed = continue the turn, quiet = no-op per CLI),
  and a never-fail runner (cmd_hook).
- hooks.py hard-codes one feature (HOOK, MARK, EVENTS, AGY_NAMES); test_hooks.py asserts the
  daily-log names. skills.py links folders with a SKILL.md, so a module folder without one is
  never linked as a skill; COMMANDS is already a table.
- daily-log.ts (47 lines) is a generic bridge: spawn the script with the event JSON, apply
  the reply. The guard needs the same bridge plus block and input rewrite.
- The guard adds to the plumbing: read and shell tools, target paths per CLI (Claude
  `file_path`, Codex patch headers, Agy `TargetFile`/`AbsolutePath`, Pi `path`), and replies
  to deny, rewrite input (Claude/Codex `updatedInput`, Agy `overwrite`, Pi input mutation),
  and add a note.

## Facts for packaging (Q15)
- daily-log precedent: `skills/daily-log/` = SKILL.md + `scripts/daily_log.py` (hook entry
  `hook <mode> --cli <cli>` and the command) + `hooks/daily-log.ts` (Pi extension delegating
  to the script); hook state in `~/.local/state/ai-dotfiles/daily-log/`.
- `scripts/install/hooks.py` and `skills.py` hard-code daily-log (HOOK, MARK, EVENTS,
  PI_EXTENSION); `scripts/ai-dotfiles` dispatches install/update/uninstall/check.
- A new skill must be added to `which-skill` (test_which_skill.py checks it).
- daily-log hooks never block; this guard must, so its failure mode is a new decision.

## Facts for an automatic move (Q6 reopened)
- Claude: the model calls `EnterWorktree` with a path under `.claude/worktrees/`; no person.
- Codex: `PreToolUse` may rewrite a call with `updatedInput`; Bash and `apply_patch` carry a
  string `command` (codex/hooks.md:771,811-828). Whether hooks run inside the sandbox (so can
  `git worktree add` without approval) is unverified.
- Pi: `tool_call` can mutate `tool_call.input` or block (pi/extensions.md:211,221).
- Agy: `PreToolUse` `overwrite` merges replacement args, e.g. `TargetFile`, `AbsolutePath`,
  `run_command`'s `Cwd`; the tool result names changed keys (antigravity/hooks.md:153-181,319).

## Facts for the move (Q6)
- Pi stores sessions per cwd; `pi --session <full path>` reopens one from any folder.
- Agy CLI scopes conversations to the cwd; `agy --conversation <id>` and `--cwd` exist, but
  resuming a conversation in another folder is unverified (antigravity/cli/reference.md:129).
- Soft-move risk: reads by relative path still hit the busy tree, so the model can copy the
  owner's uncommitted changes into its worktree with a whole-file write.

## Facts for the base (Q7)
- Claude `EnterWorktree` creates from the default branch (`origin/HEAD`) unless
  `worktree.baseRef: "head"`, a setting, not per call; its `path` form enters an existing
  worktree under `.claude/worktrees/` without a prompt (claude/tools-reference.md:34).
- Codex worktrees start from the chosen branch's HEAD, copy that branch's uncommitted changes
  (app), and are detached HEAD, no branch (codex/environments/git-worktrees.md:147). Whether
  `codex resume --worktree` copies uncommitted changes is unverified; `resume -C <dir>` exists.
