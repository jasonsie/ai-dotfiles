# Prior Art: AI Agent Auto-Branching / Worktree-per-Session

_Research date: 2026-10-30 (a subagent wrote "2025-07"). Sources: GitHub API, repo READMEs, source code, hook scripts._

> **Verification (2026-11-02).** Written by a research subagent. Checked against the source:
> mcouthon/agents ADR-017 and its "decided by whoever launched it" rule; the
> awesome-claude-hooks `hooks/git/` scripts. Unverified, do not rely on: the
> `stevencohn/OneMore` quote (GitHub code search finds nothing), star counts, the
> vibe-kanban "sunsetted" note.

---

## 1. Tools & Extensions

### Session managers that always create a worktree per session

- **claude-squad** — `smtg-ai/claude-squad` ★8700 <https://github.com/smtg-ai/claude-squad>  
  Terminal app managing multiple Claude Code / Codex / Aider sessions. Each task gets a dedicated git worktree; sessions are never on the same branch. Branch prefix configurable (`BranchPrefix` in `~/.claude-squad/config.json`). On creation: `NewGitWorktree(repoPath, sessionName)` generates `<prefix><sessionName>`, sanitizes slashes, appends a nanosecond timestamp to the worktree path to guarantee uniqueness. `isExistingBranch` flag preserves pre-existing branches on cleanup.  
  Source: `session/git/worktree.go`, `config/config.go`.

- **ccmanager** — `kbwo/ccmanager` ★1274 <https://github.com/kbwo/ccmanager>  
  Multi-agent session manager (Claude Code, Gemini CLI, Codex, Cursor, etc.) across git worktrees and projects. UI-driven worktree creation with `pre_creation` and `post_creation` hooks; env vars `CCMANAGER_WORKTREE_BRANCH`, `CCMANAGER_BASE_BRANCH`, `CCMANAGER_GIT_ROOT` provided to hooks. Auto-directory naming from branch name (`{branch}`, `{project}` placeholders; slash→dash, lowercase). Parent branch stored in worktree config (`extensions.worktreeConfig`) for ahead/behind tracking. `.worktreeinclude` carries gitignored files (`.env`, certs) into new worktrees.  
  Source: `docs/worktree-hooks.md`, `docs/worktree-auto-directory.md`, `docs/git-worktree-config.md`.

- **vibe-kanban** — `BloopAI/vibe-kanban` ★28514 <https://github.com/BloopAI/vibe-kanban> _(sunsetted 2025-07)_  
  Kanban + agent orchestration UI. Each "workspace" provisioned an isolated agent, branch, terminal, and dev server. Explicit branch-per-task enforced at the product level, not via hooks. Crates include `crates/git` (Rust).

- **gtr / git-worktree-runner** — `coderabbitai/git-worktree-runner` ★1800 <https://github.com/coderabbitai/git-worktree-runner>  
  Bash CLI wrapping `git worktree` for AI agent usage. `git gtr new <branch> --porcelain` returns tab-separated `path / branch / hook_status` to stdout (errors to stderr), so agents can parse creation reliably. Recommended agent lifecycle: list → create → work in returned path → report status → cleanup only on explicit user request. AGENTS.md example policy included in `docs/agent-usage.md`. Post-create hooks handle dep install, file copy, fetch; `--no-hooks --no-copy --no-fetch` for bare automation.

- **parallel-agent-worktree-skill** — `TheAhmadOsman/parallel-agent-worktree-skill` ★33  
  Agent skill for orchestrating parallel CLI agents in isolated git worktrees with review-gated integration, changelog requirements, and backup-aware workflows. Adaptable to Codex, Claude Code, Pi, Kimi, or any CLI harness.

- **open-dynamic-workflow** — `ChaosRealmsAI/open-dynamic-workflow` ★16  
  Re-implementation of Claude Code's Dynamic Workflow with git-worktree isolation, deterministic resume, and parallel execution via `agent()`, `parallel()`, `pipeline()`.

### Hooks doing auto-branch logic

- **awesome-claude-hooks** — `MohamedAbdallah-14/awesome-claude-hooks` ★3 <https://github.com/MohamedAbdallah-14/awesome-claude-hooks>  
  Curated Claude Code hook library. Branch-related hooks (all Bash, copy-paste installable):

  - `hooks/git/auto-create-branch.sh` — **Stop event**. After session ends, checks: (1) inside a git repo, (2) current branch is a protected branch (`main master develop`, configurable via `CLAUDE_PROTECTED_BRANCHES`), (3) uncommitted changes OR commits made this session (via reflog). If all three true, outputs a context message suggesting a feature branch name derived from recent commit messages or changed paths. Does **not** block; suggests retroactively.

  - `hooks/git/protect-main-branch.sh` — **PreToolUse(Bash)**. Blocks: `git push --force/-f` to protected branches, `git reset --hard` on protected branch, `git branch -D` or `git checkout -B` targeting protected branches. Returns `{"block": true}` JSON to stderr.

  - `hooks/git/stash-guard.sh` — **PreToolUse(Bash)**. Warns (or blocks with `CLAUDE_STASH_GUARD_BLOCK=1`) on: `git checkout <branch>`, `git switch`, `git stash pop/apply`, `git pull [--rebase]`, `git reset --hard`, `git merge` — all when the working tree is dirty.

  - `hooks/git/auto-resume-from-stash.sh` — **SessionStart(resume)**. On resume, pops the most recent stash whose message matches `claude-auto:<current-branch>`, restoring dirty state from a prior session end.

  - `hooks/session/session-name-from-branch.sh` — **SessionStart**. Slugifies current branch name and injects it as session context so the model knows which branch it is on.

- **tonyc726/china-administrative-division** `.claude/settings.json` — **PreToolUse(Write|Edit|MultiEdit)**  
  Inline hook in `settings.json` blocks all file edits on main/master: `[ "$(git branch --show-current)" != "main" ] && [ "$(git branch --show-current)" != "master" ] || { echo '{"block": true, "message": "禁止直接修改主分支，请先 git checkout -b feat/xxx"}' >&2; exit 2; }`. No script file needed; the check is embedded in the hook command string.

- **mcouthon/agents** CHANGELOG _(private or low-star repo)_  
  Previously had a `SessionStart` "worktree heuristic" hook with `AGENTS_WORKTREE=1` support that attempted LLM-side decisions on whether to create a worktree based on branch state (main/master → no action; merged branch → checkout-and-pull; active branch → inject context). **Removed** after finding the model cannot observe concurrent sessions; the changelog (ADR-017) states: _"All agent templates now carry one sentence: 'Where a session runs is decided by whoever launched it; do not create branches or worktrees unless the user asks.'"_

---

## 2. CLAUDE.md / AGENTS.md Rules (Model-Layer)

Common patterns found in public repos:

- **Blanket prohibition** — "Never commit to main/master":
  - `superfly/ltx` CLAUDE.md: _"Always create feature branches. Never commit to main. Never do anything destructive without asking."_
  - `meltylabs/chorus` CLAUDE.md: _"Create a new branch like `claude/feature-name`. NEVER commit to main. NEVER push to origin/main."_ (explicit `claude/` prefix convention)
  - `hardkoded/puppeteer-sharp` CLAUDE.md: _"Always verify which git branch you are on before making commits or creating PRs. Never commit to main/master. If the task requires a new branch, create it immediately and confirm with `git branch --show-current`."_
  - `thisuxhq/sveltednd` CLAUDE.md: _"Use feature branches, never commit to main directly."_
  - `interscript/interscript-ruby` CLAUDE.md: _"PRs only, never commit to main."_

- **Conditional branch selection** — "Use existing branch if not on main":
  - `stevencohn/OneMore` CLAUDE.md: _"Always use the current git branch if it is not `main`… Never prompt for branch selection if not on main. If on main, pause with a prompt to the user that says 'You are on the main branch. Please switch to a feature branch or create one.'"_

- **Branch naming conventions** in AGENTS.md / CLAUDE.md:
  - `claude/feature-name` (chorus), `feat/xxx` (tonyc726), `update-deps-:*` (pydantic/logfire `.claude/settings.json` allow list)
  - `EstrellaXD/Auto_Bangumi` CLAUDE.md has a multi-branch strategy: bugs → current `-dev` branch, features → next `-dev` branch, plugin listings → main.

- **gtr's copy-paste AGENTS.md template** (`docs/agent-usage.md`): _"For implementation tasks, create an isolated worktree with `git gtr new <branch> --porcelain` and work only in the returned `path`. Do not remove worktrees, force cleanup, or delete branches without explicit user authorization."_

---

## 3. Decision Criteria Used

Synthesised from source code, hook logic, and CLAUDE.md rules:

| Signal | Decision | Source |
|---|---|---|
| Current branch is main/master/develop | Create / suggest a feature branch | protect-main-branch.sh, auto-create-branch.sh, CLAUDE.md rules, claude-squad |
| Dirty working tree + about to switch branch | Stash or block | stash-guard.sh |
| Parallel sessions requested | Mandatory worktree-per-session | claude-squad, ccmanager, vibe-kanban |
| `isExistingBranch == true` (branch existed pre-session) | Keep branch; don't delete on cleanup | claude-squad `worktree.go` |
| Resume event | Pop matching claude-auto stash | auto-resume-from-stash.sh |
| Detached HEAD | Abort branch operations | claude-squad (explicit exit) |
| Task type (bug vs feature) | Different branch name prefix | AGENTS.md rules (per-project) |
| LLM cannot observe other running sessions | Do NOT let LLM decide on concurrency | mcouthon/agents ADR-017 (anti-pattern) |

---

## 4. Known Pitfalls

- **Dirty tree / stash**: Switching branches with uncommitted changes silently discards or conflicts. `stash-guard.sh` addresses this; `auto-resume-from-stash.sh` handles the other side. Manual-stash advice in aider docs.
- **Detached HEAD**: `git symbolic-ref --short HEAD` returns empty; both `auto-create-branch.sh` and claude-squad exit early rather than attempting operations.
- **Dep install in new worktrees**: Node `node_modules`, Python venvs, etc. don't carry over. ccmanager's `post_creation` hook and gtr's post-create hooks are the standard solution. ccmanager's `.worktreeinclude` handles gitignored files (`.env`, certs).
- **Branch naming / filesystem safety**: Slashes (feature/foo → feature-foo), special chars, case — all tools sanitize; claude-squad appends a nanosecond timestamp to prevent path collisions.
- **Cleanup ownership**: Consensus is agents must NOT auto-delete worktrees or branches; only on explicit user request (gtr's AGENTS.md policy, ccmanager's "paused" state vs delete).
- **LLM deciding on concurrency**: Tried and abandoned (mcouthon/agents); the model cannot observe other running sessions, so worktree decisions belong to the launcher/orchestrator layer, not the model.
- **Worktree config extension**: `extensions.worktreeConfig true` required for per-worktree git config (parent branch tracking); not on by default — ccmanager documents this explicitly.
- **Force-push / reset --hard on main**: Common footgun; caught by `protect-main-branch.sh` at hook level rather than relying on model compliance.

---

## 5. Synthesis — Consensus Best Practice (5 lines)

**Separate concerns: the launcher decides where to run; the model decides what to do.**  
Orchestrators (claude-squad, ccmanager, vibe-kanban, gtr) create one isolated git worktree per session before the agent starts — the model never has to make this decision and cannot see concurrent sessions anyway.  
When no orchestrator is present, the lightest reliable approach is a `PreToolUse` hook that blocks writes on protected branches and a `Stop` hook that warns if the session ended on main with uncommitted changes, both with a suggested branch name derived from commit messages or task context.  
The two hardest pitfalls are dirty-tree state on branch switch (address with `stash-guard` + `auto-resume-from-stash`) and cleanup ownership (never auto-delete; only on explicit user request).  
Effective AGENTS.md/CLAUDE.md rules follow the pattern: _"If not on main/master, work on the current branch; if on main, pause and ask the user to create or name a feature branch before proceeding."_
