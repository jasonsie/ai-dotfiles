# Native branch / worktree features — Claude Code, Codex CLI, Pi, Antigravity

Research date: 2026-10-30 (a subagent wrote "2025-07"). Sources: `docs/upstream/` mirror.

> **Corrections (2026-11-02).** Written by a research subagent; where it disagrees with
> `decisions.md`, `decisions.md` wins.
> - Codex **does** have `--worktree` ("Run the session in a new managed Git worktree"), and
>   `codex resume` takes `--worktree` and `-C <dir>` (`codex --help`, `codex resume --help`).
>   The "No `--worktree` CLI flag" line and the matrix's "❌ (UI-only)" are wrong.
> - Codex hook config is `~/.codex/hooks.json` or inline `[hooks]` in `config.toml`
>   (codex/hooks.md:37-48), not `hooks.toml`.
> - Pi's `ctx.sessionManager.getBranch()` is the session tree's branch, not git's; a Pi
>   extension reads the git branch by running git.

---

## 1. Claude Code

### CLI flags
- **`--worktree <name>` / `-w <name>`** — creates isolated git worktree under
  `.claude/worktrees/<name>/` on a new branch `worktree-<name>`, then starts
  the session there.
  > `"Pass --worktree or -w with a name to create an isolated worktree and start
  > Claude in it."` — `claude/worktrees.md`
- Name is optional; Claude auto-generates one (`bright-running-fox`).
- `--worktree <name> --resume` — returns to an existing worktree session.
- `-p --worktree` (non-interactive) skips the workspace-trust check.

### Base-branch setting
- **`worktree.baseRef`** in settings:
  - `"fresh"` (default) — branches from `origin/HEAD` (fetches if >24 h stale).
  - `"head"` — branches from current local HEAD (useful when subagents must see
    in-progress work).
  > `"settings-reference.md#worktree"` — `claude/worktrees.md`

### Subagent isolation
- **`isolation: worktree`** in a subagent's frontmatter — every invocation of
  that subagent gets its own temporary worktree.
  > `"make the isolation permanent for a custom subagent by adding isolation:
  > worktree to its frontmatter."` — `claude/worktrees.md`
- `/batch <instruction>` fan-out — Claude splits work across 5–30 subagents,
  each in its own worktree automatically.
  > `"Each subagent works in its own worktree."` — `claude/best-practices.md`

### EnterWorktree / ExitWorktree tools
- Claude can call **`EnterWorktree`** (and `ExitWorktree`) mid-session to switch
  worktrees without restarting.
  > `"ask Claude to 'work in a worktree' during a session, and it creates one
  > with the EnterWorktree tool."` — `claude/worktrees.md`

### Hook events — worktree lifecycle
| Event | When it fires | Can block? | Output contract |
|---|---|---|---|
| **`WorktreeCreate`** | Before git creates worktree (via `--worktree`, `isolation: worktree`, or background session). **Replaces** default git behavior when defined. | Yes — any non-zero exit fails creation | Command hook: print absolute path to stdout. HTTP hook: `hookSpecificOutput.worktreePath`. |
| **`WorktreeRemove`** | When a hook-created worktree is being cleaned up | Yes — non-zero exit keeps worktree on disk | Exit code only; JSON output discarded |

> `"Configuring a WorktreeCreate hook replaces that default git behavior, letting
> you use a different version control system like SVN, Perforce, or Mercurial."`
> — `claude/hooks.md` §WorktreeCreate

- `WorktreeCreate` receives: `name` (slug) + common fields (`session_id`, `cwd`,
  project dir, etc.).
- A plugin's `WorktreeCreate` hook does NOT run when `--worktree --tmux` is used
  together; define it in a settings file to cover that case.

### Hook events — context injection / gating
| Event | Can inject context? | Can block? | Branch/worktree relevance |
|---|---|---|---|
| **`SessionStart`** | Yes — `additionalContext`, `initialUserMessage`, `watchPaths`, `sessionTitle`, `reloadSkills` | No | `source` field: `"startup"`, `"resume"`, `"fork"`, `"clear"`, `"compact"`. Re-runs on resume — use to inject current branch state freshly. |
| **`UserPromptSubmit`** | Yes — `additionalContext`, `sessionTitle` | Yes (exit 2) | Fires before Claude sees the prompt; can read `cwd` to detect worktree. |
| **`PreToolUse`** | Yes — `additionalContext` via `hookSpecificOutput`; `updatedInput` rewrites tool args | Yes (exit 2 or `permissionDecision: deny`) | Can block git commands, restrict which branches Claude touches. |
| **`PostToolUse`** | Yes — exit 2 surfaces stderr to Claude | No | Enforce post-edit checks (lint, test) per worktree. |

- `cwd` in hook input JSON follows Claude into the worktree; `${CLAUDE_PROJECT_DIR}`
  stays at the main checkout root.
  > `"cwd follows Claude: the cwd field in the hook's input JSON is the worktree
  > root after Claude enters a worktree."` — `claude/hooks.md`

### Isolation enforcement (built-in, no hook needed)
Four automatic checks while a session is in a worktree: file-edit paths, command
working directory, git redirects, command shape. Claude is told how to rewrite a
refused command. Cannot be turned off.
> `"Claude Code applies four checks … File edits, Command working directory, Git
> redirects, Command shape."` — `claude/worktrees.md`

### Best-practice guidance
- `common-workflows.md`: "Work on a feature in one terminal while Claude fixes a
  bug in another, without the edits colliding."
- `best-practices.md`: "Name sessions with `/rename` and treat them like branches:
  each workstream gets its own persistent context."
- Parallel approaches ranked: worktrees (file isolation) → desktop sessions →
  subagent fan-out (`/batch`).
- Cleanup sweep: `cleanupPeriodDays` setting removes stale subagent/background
  worktrees automatically.

---

## 2. Codex CLI (ChatGPT)

### Native worktree support
- **Worktrees built into the app UI**: every chat can run in Local or Worktree
  mode; "Handoff" button moves a chat between them.
  > `"Use Hand off in the chat header to move a chat between your local checkout
  > and a worktree."` — `codex/environments/git-worktrees.md`
- Worktrees created under `$CODEX_HOME/worktrees` by default; override via
  **Settings › Worktrees › Worktree root**.
- **Scheduled tasks** always run in a dedicated background worktree (git repos).
  > `"scheduled tasks can run on dedicated background worktrees so they don't
  > conflict with your ongoing work."` — `codex/environments/git-worktrees.md`
- Snapshots saved before worktree deletion; restore offered on reopening chat.
- No `--worktree` CLI flag (worktrees are configured in settings / UI, not CLI).
- **No `WorktreeCreate` / `WorktreeRemove` hook events** (those are Claude Code–only).

### Hook events (config: `~/.codex/hooks.toml` or project `.codex/hooks.toml`)
| Event | Notes |
|---|---|
| **`SessionStart`** | `source` field: `startup`, `resume`, `clear`, `compact`, `fork`. Hook output can inject `systemMessage`. MCP hooks may not be ready yet. |
| **`UserPromptSubmit`** | Matcher ignored. Can block or inject context. |
| **`PreToolUse`** | Can block or rewrite via `updatedInput`. Covers Bash, `apply_patch`, file reads/writes, MCP tools. |
| **`PostToolUse`** | Observational; output written to temp file given to model. |
| `SessionEnd` | Always sync. `source: other`. |
| `SubagentStart`, `SubagentStop` | Subagent lifecycle. |

> `"PreToolUse can intercept Bash, file edits performed through apply_patch …
> inspect their JSON arguments, and block or rewrite the call."` — `codex/hooks.md`

- Hook output for `SessionStart`: `systemMessage` injected into conversation.
- Hook output for `PreToolUse`: `systemMessage`, `continue`, `updatedInput`.
- No `additionalContext` field (Claude Code–specific); context injected via
  `systemMessage` written to `<temp_dir>/hook_outputs/<session_id>/<uuid>.txt`.

### Branch / worktree via config
- `config-reference.md` references `worktree` settings (root path, enable/disable).
- No `worktree.baseRef`-equivalent documented in mirror.

---

## 3. Pi

### No native `--worktree` flag
Pi has no built-in `--worktree` CLI flag and no `WorktreeCreate`/`WorktreeRemove`
events. Worktree management must be done by the user or via extensions.

### Extension events relevant to branch/worktree decisions
| Event | Purpose | Can block? | Notes |
|---|---|---|---|
| **`session_start`** | Initialize session-scoped resources | No | `ctx.sessionManager.getBranch()` — read active branch to reconstruct branch-sensitive state. |
| **`before_agent_start`** | Mutate system prompt, active tools, add context before every run | No | Receives `event.messageType` ("user" or "custom"). Can inject `systemPromptOptions`, add guidelines, or return `systemPrompt` (replaces whole prompt for that run). |
| **`tool_call`** | Authorize or modify a tool call; block execution | **Yes — fail-closed** | `"A tool_call handler failure blocks the tool as a fail-safe."` |
| **`tool_result`** | Compose/transform tool results | No | Each handler sees prior handlers' changes. |
| `session_shutdown` | Release resources | — | — |

- Branch state:
  > `"Reconstruct branch-sensitive state from ctx.sessionManager.getBranch()
  > during session_start. Do not rebuild it from every file entry because
  > abandoned branches represent alternative histories."` — `pi/extensions.md`
- `before_agent_start` example use: detect current branch via `getBranch()` and
  inject branch-specific rules or context into every run automatically.
- In-place mutation: later handlers see changes to `before_agent_start.systemPromptOptions`
  and `tool_call.input`.

### No hook-level worktree events
Pi extensions cannot intercept worktree creation/removal; they must shell out to
git themselves. Example `permission-gate.ts` extension in examples shows combining
`tool_call`, mode-aware UI, and fail-closed behavior.

---

## 4. Antigravity (Google / Gemini)

### Native worktree support
- **Projects natively support Git worktrees.**
  > `"Worktree support: Projects natively support Git worktrees, allowing agents
  > to operate in isolated background folders."` — `antigravity/features.md`

### Subagent workspace options
- When spawning a subagent via `invoke_subagent`, the `Workspace` field accepts:
  - **`inherit`** — subagent shares parent's workspace.
  - **`branch`** — subagent gets an **isolated Git worktree** (auto-cleaned up
    when subagent finishes).
  - **`share`** — shared directory storage.
  > `"The subagent can either inherit the same workspace as its parent (inherit),
  > create an isolated Git worktree (branch), or share directory storage (share)."`
  > — `antigravity/subagents.md`
- Parent agents retain read access to all subagent worktrees.
- Temporary worktrees are automatically cleaned up.
  > `"Any temporary Git worktrees generated for the subagent are automatically
  > cleaned up."` — `antigravity/subagents.md`
- No named `--worktree` CLI flag; worktree choice is per-`invoke_subagent` call.

### Hook events (`hooks.json` — App, CLI, IDE)
| Event | Can inject context? | Can block? | Notes |
|---|---|---|---|
| **`SessionStart`** | Yes — `injectSteps` (systemMessage, userMessage, ephemeralMessage, toolCall) | No | Fires once before first model invocation. No `source` field (no resume distinction). |
| **`PreToolUse`** | Yes — `overwrite` (shallow-merge args replacement); `permissionOverrides` | Yes — `decision: "deny"` / `"force_ask"` / `"deny_unless_prior_grant"` | Also supports `"auto_approve"`, `"ask"`. |
| **`PostToolUse`** | No | No | Observational; returns `{}`. |
| **`PreInvocation`** | Yes — `injectSteps` before model call | No | `invocationNum`, `initialNumSteps`. |
| **`PostInvocation`** | Yes — `injectSteps`; `terminationBehavior` (`"force_continue"` / `"terminate"`) | Via `terminationBehavior` | Can restart the loop. |
| `Stop` | Yes — `decision: "continue"` + `reason` (injected as system message) | Via `continue` decision | |

- **No `WorktreeCreate` / `WorktreeRemove` events** — worktree lifecycle is
  internal to the subagent call.
- A `PreToolUse` hook on `run_command` can inspect `CommandLine` and `Cwd` to
  detect branch-sensitive commands and gate them.
- `overwrite` in `PreToolUse` output can rewrite `Cwd` to redirect a command to
  a specific worktree path.

### Branch-level tooling (built-in)
- `/diff` command: "Branch diffs: Review changes made on the current branch."
- `/push` command: "Push branch commits to a remote repository."
  > `antigravity/features.md`

---

## Summary matrix

| Feature | Claude Code | Codex CLI | Pi | Antigravity |
|---|---|---|---|---|
| `--worktree` CLI flag | ✅ `--worktree <name>` | ❌ (UI-only) | ❌ | ❌ |
| Base-branch setting | ✅ `worktree.baseRef` fresh/head | ⬜ (not documented) | — | — |
| Subagent worktree isolation | ✅ `isolation: worktree` frontmatter | — | — | ✅ `Workspace: branch` in `invoke_subagent` |
| Built-in isolation enforcement | ✅ 4 automatic checks | ❌ | ❌ | ❌ |
| `WorktreeCreate` hook (replaces git) | ✅ | ❌ | ❌ | ❌ |
| `WorktreeRemove` hook | ✅ | ❌ | ❌ | ❌ |
| `SessionStart` context injection | ✅ `additionalContext` | ✅ `systemMessage` | ✅ `before_agent_start` | ✅ `injectSteps` |
| Hook can read current branch | ✅ via `cwd`/shell in hook | ✅ via shell | ✅ `ctx.sessionManager.getBranch()` | ✅ via shell in hook |
| `PreToolUse` block+rewrite | ✅ | ✅ | ✅ `tool_call` (fail-closed) | ✅ `decision` + `overwrite` |
| `UserPromptSubmit` block | ✅ | ✅ | ❌ (no direct equiv.) | ❌ |
| Auto-cleanup of temp worktrees | ✅ `cleanupPeriodDays` sweep | ✅ (snapshots saved) | — | ✅ automatic |
| Best-practice doc | `common-workflows.md`, `best-practices.md` | `git-worktrees.md` | `extensions.md` §branch state | `subagents.md` |
