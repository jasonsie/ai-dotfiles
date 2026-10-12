# `ai-cli-workspace` is the single source for global CLI config; shared behavior, native differences

Status: **Accepted and executed** 2026-10-05. Manifest approved by the user; backup at
`~/.local/state/ai-cli-workspace/backup-20261005-144219/` (includes `workspace-wip.patch`).
Supersedes: [0001](0001-claude-header-scaffold-source-file.md), [0002](0002-multi-cli-parity-target.md) (full 1:1 parity), [0003](0003-portable-library-framing.md).

## Context

Claude Code, Pi, Codex, and Gemini CLI each accumulated their own config. Claude carried a
corrupted, flattened copy of everything-claude-code (ECC) rules, an ECC plugin (125 skills,
28 agents, 60 commands, 27 hook handlers), and a plaintext GitHub token in `~/.claude.json`.
Codex and Gemini still carried outputs of this repo's older project-rule generator (agents,
prompts/commands, hooks). The workspace itself had two jobs: global config and per-project
rule generation.

The decisions were made by a grilling session (Pi session `01a10a80-963f-722a-9de2-04e18b97c6c5`, continued in Claude Code on 2026-10-05).

## Decisions

| # | Question | Decision |
|---|---|---|
| Q1 | Who owns the source? | `ai-cli-workspace`. Claude is the behavioral reference, not the source. All four CLIs consume the workspace. |
| Q2 | Parity level | Same behavior where shared; each CLI keeps its native features. Document unsupported features instead of emulating them. |
| Q3 | Platforms | macOS only (any username, checkout path, Intel or Apple Silicon). No hard-coded `/Users/<name>` or `/opt/homebrew`. |
| Q4 | Workflow mandates (forced research, planning docs, TDD/80%, automatic agents) | Dropped. Work stays proportional to the task; projects may be stricter. |
| Q5 | Vault retrieval | Keep: automatic, scoped, read-only, in all four CLIs. |
| Q6 | `~/.claude/rules/` | Retire all 11 files. The shared `AGENTS.md` already covers commit style and vault retrieval. |
| Q7 | ECC plugin | Uninstall. Port no ECC skills unless the user names some. Back up `homunculus/` before deleting it. |
| Q8 | MCP | context7 is shared through `tools/mcp/servers.yaml` (Claude, Codex, Gemini; Pi has no MCP). The github MCP server is removed in favor of `gh`; rotate the PAT afterwards. |
| Q9 | Claude plugins | Keep `zkfy`, `pyright-lsp`, `typescript-lsp`. Remove `learning-output-style`, `serena`, `prisma`, `claude-md-management`, `claude-code-setup`. |
| Q10 | Personal hook and commands | Remove the session-closeout hook, `git-commit-message`, and `ecc-guide`, with no replacement. |
| Q11 | Workspace scope | Global config only. Retire the project-rule generator: `tools/rules`, `tools/hooks`, `tools/agents`, `tools/profiles`, `tools/commands`, `init-project.sh`, `load-plan.sh`. Keep the upstream doc mirrors as reference. |
| Q12 | Settings | Managed-keys merge: the template lists only keys meant to be the same on every Mac, and install merges them in with a backup. Local and runtime keys and credentials are never stored here. Settings files are never symlinked, because the CLIs write back to them. |
| Q14 | Managed keys | Models and effort, plus safety keys (approval, sandbox, permission prompts). Values were taken from the live configs, not the stale templates. Env, attribution, and statusline stay local. |
| Q13 | Shared skills | `zkfy` owns `vault-query` and the `vault-knowledge` launcher, located through `ZKFY_DIR` or a config file. Other shared skills go in `tools/skills/`. Both are linked into the Claude and Pi skill folders. |

## Target layout (after)

```
tools/instructions/AGENTS.md   → symlinked as ~/.claude/CLAUDE.md, ~/.codex/AGENTS.md,
                                  ~/.gemini/GEMINI.md, ~/.pi/agent/AGENTS.md
tools/settings/managed.json    → scripts/apply-settings.py (managed-keys merge per CLI)
tools/mcp/servers.json         → scripts/apply-mcp.py (native `<cli> mcp add`; Pi: none)
zkfy (ZKFY_DIR/ZKFY_VAULT)     → scripts/install-vault-knowledge.py (launcher + vault-query for Claude, Pi)
scripts/install.sh             → runs the four steps in order; requires Python 3.11+
scripts/healthcheck.sh         → checks live CLI state, portability, and tests
tools/skills/                  → none today; add linking when the first shared skill lands
tests/
docs/<cli>/upstream/ (reference mirrors), docs/adr/
```

## Deletion manifest (approved, executed)

Backups go to `~/.local/state/ai-cli-workspace/backup-<timestamp>/`, with mode `0700` on the
directory and `0600` on files. The `~/.claude.json` backup contains the PAT.

### Claude Code

| Path / item | Reason | Q | Method |
|---|---|---|---|
| ECC plugin `everything-claude-code@everything-claude-code` | Removed | Q7 | `claude plugin uninstall` |
| `learning-output-style`, `serena`, `prisma`, `claude-md-management`, `claude-code-setup` | Removed | Q9 | `claude plugin uninstall` |
| MCP `github` (user scope; plaintext PAT) | Replaced by `gh` | Q8 | `claude mcp remove github -s user` |
| `~/.claude/rules/` (11 files) | Retired | Q6 | backup → `rm` |
| `settings.json` → `hooks.UserPromptSubmit` entry | Hook removed | Q10 | JSON edit (backup) |
| `~/.claude/hooks/session-closeout.{sh,rule.md}` | Hook removed | Q10 | backup → `rm` |
| `~/.claude/commands/{ecc-guide,git-commit-message}.md` | Removed | Q7/Q10 | backup → `rm` |
| `~/.claude/homunculus/` (35 MB, ECC instincts) | ECC data | Q7 | backup → `rm` |
| `~/.claude/skills/learned/` (empty, ECC continuous-learning) | ECC leftover | Q7 | `rmdir` |
| `~/.claude/metrics/costs.jsonl`, `session-data/`, `session-aliases.json`, `codebase-maps/` | ECC hook/command output | Q7 | backup → `rm` |
| `~/.claude/session-events.log`, `user-prompts.log` (stopped 2026-05-20) | Old workspace hook output | Q11 | backup → `rm` |
| Marketplace `everything-claude-code` | Stops ECC from returning through marketplace updates | Q7 | `claude plugin marketplace remove` |
| `~/.ai-cli-workspace-path` | Read only by the retired Stage-2 launchers | Q11 | `rm` |

### Codex

| Path / item | Reason | Q | Method |
|---|---|---|---|
| `~/.codex/hooks.json` (absolute paths to retired workspace hooks) | Generator output | Q11 | backup → `rm` |
| `~/.codex/agents/*.yaml` (9) | Generator output (`tools/agents`) | Q11 | backup → `rm` |
| `~/.codex/prompts/{deep-review,healthcheck,init-project,load-plan}.md` | Generator output (`tools/commands`) | Q11 | backup → `rm` |

### Gemini CLI

| Path / item | Reason | Q | Method |
|---|---|---|---|
| `settings.json` → `hooks` (5 events) + `hooksConfig.disabled` | Retired workspace hooks | Q11 | JSON edit (backup) |
| `~/.gemini/commands/{deep-review,healthcheck,init-project,load-plan}.toml` | Generator output | Q11 | backup → `rm` |
| `~/.gemini/commands/git/git-commit-message.prompt.toml` | Removed command | Q10 | backup → `rm` |
| `~/.gemini/config/mcp_config.json` (0 bytes) | Empty | — | `rm` |

### Pi

Nothing to delete. `prompts/review.md` is Pi-native, and `bin/fd` is managed by Pi.

### Workspace repo (`ai-cli-workspace`)

| Item | Reason | Q |
|---|---|---|
| `tools/rules/`, `tools/hooks/`, `tools/agents/`, `tools/profiles/`, `tools/commands/`, `tools/templates/` | Project generator retired | Q11 |
| `scripts/init-project.sh`, `scripts/load-plan.sh`, `scripts/adapters/rules.sh` | Project generator retired | Q11 |
| `_claude_link_resources` + related healthcheck checks + `.gitignore` lines (from `45ba83c`/`4ab394e`) | Link targets are retired | Q11 |
| Gemini hook-format migration in `scripts/adapters/gemini.sh` | Hooks retired | Q11 |
| The 62 already-pending deletions (`tools/skills/*`, `.claude/skills/grill-*`) | User WIP; consistent with Q11 | Q11 |
| `docs/adr/0001`, `0002`, `0003` | Marked superseded | Q2/Q11 |
| Repo `.claude/settings.json` (+`.bak`, gitignored) registering 10 hook events into `tools/hooks/` | Would error in every session once hooks were gone | Q11 |
| Shell adapters (`_common.sh`, `claude/codex/gemini/rules.sh`) and the template settings files | Replaced by `apply-settings.py` + `apply-mcp.py`; templates held stale models | Q11/Q12 |
| Hand-written docs about the generator (`HOOKS.md`, `hook-lifecycle.md`, `agents-port-decisions.md`, `human-onboard/`, `inventory/`) | Moved to `docs/archive/`, not deleted | Q11 |
| Repo-root generated `CLAUDE.md`/`AGENTS.md`/`GEMINI.md` (import all 11 `tools/rules`, including `core.md`'s "after every change YOU MUST commit and push") | Replace with one short hand-written maintainer `AGENTS.md`, plus a `CLAUDE.md` symlink to it | Q4/Q11 |
| `CONTEXT.md`, `README.md`, `tools/README.md` (describe full parity and two jobs) | Rewrite for the narrowed scope | Q2/Q11 |

### Kept, not managed here (do not delete)

Credentials and sessions (`auth.json`, `oauth_creds.json`, `google_accounts.json`, `sessions/`,
`history*`, `*.sqlite`); `~/.claude/skills/synced/` (claude.ai account sync);
`~/.claude/projects/` (memory); `~/.claude/statusline/` (active); `settings.local.json`;
Codex `[projects]` trust and `rules/default.rules` (approvals the user granted locally);
`~/.gemini/antigravity-ide/` and `~/.gemini/config/{plugins,projects,sidecars}`
(Antigravity IDE, out of scope); `~/.claude/memory/` and `~/.claude/prompts/` (user data,
can be reviewed separately).

## Results (2026-10-05)

- `healthcheck.sh` reports healthy: all four instruction links resolve, `install.sh --dry-run`
  shows 0 pending changes, context7 appears in `claude`/`codex`/`gemini mcp list`, the vault
  launcher resolves, there are no machine paths, and 38 unit tests pass.
- Enabled Claude plugins are exactly zkfy, pyright-lsp, typescript-lsp, and `claude mcp` has no github.
  Still installed but disabled, outside Q9's scope and pending a user decision: feature-dev (×2),
  figma, frontend-design, hookify (×2), playwright. `@synced` plugins come from the claude.ai account.
- Gemini lists context7 as *disabled* in untrusted folders. That is Gemini's own safety
  behavior and is not worked around (Q2).
- Under stock macOS bash 3.2, `install.sh` runs, and under Python 3.9 it fails with a clear
  message. A fresh second Mac has not been tested yet.
- The ECC plugin cache under `~/.claude/plugins/cache/` is left for Claude Code's own cleanup
  (the running session had it loaded).
- Found outside this repo and left alone: a stale allow rule mentioning `tools/hooks/memory-sync.sh` in
  `~/Developer/repo/project/ai/workspace/.claude/settings.local.json`, and 14 project skills
  in that parent folder's `.claude/skills/`. Both are project-level and outside Q11's scope.

## Follow-up (2026-10-12)

- **Plugins:** the disabled leftovers were uninstalled at every scope, including the project
  and local installs in two work repos: feature-dev (×2), figma, frontend-design, hookify (×2), playwright.
  `claude plugin list` now shows only zkfy, pyright-lsp, typescript-lsp (plus claude.ai `@synced`).
- **Serena:** Q9 removed only the plugin. The MCP server still came from `.mcp.json` files in
  parent folders (which apply to every repo below them) and from `enabledMcpjsonServers` in
  project settings. All of those entries, the `.serena/` folders, and the `serena-agent` uv tool
  were removed. Each affected repo got a local commit; nothing was pushed.
- **GitHub access (Q8 completed):** `gh` replaces the github MCP server. Two accounts are logged
  in, both in the macOS Keychain with `repo, read:org, gist, workflow`. The personal account is the
  default. A one-line `.envrc` (`export GH_TOKEN=$(gh auth token --user <account>)`, loaded
  by direnv and excluded through `.git/info/exclude`) switches `gh` per repo for the second
  account. `git` still selects accounts by SSH host aliases in `~/.ssh/config`, which `gh`
  does not use for authentication. HTTPS git uses `gh auth setup-git`. The plaintext GitHub
  token in `~/.git-credentials` and the plaintext `gh` token in `hosts.yml` were removed. An
  unused third SSH alias and its key were deleted.
- **Parent `workspace/.claude/`:** brought into scope and retired. It held a copy of the
  retired generator's output (10 hook events into `.claude/hooks/`, 34 skills, stale model
  IDs, an ECC codebase map) that loaded for any session started in the parent folder.
  Backed up as a tarball before removal.
- **Plugin cache:** the `everything-claude-code` and `claude-code-plugins` caches under
  `~/.claude/plugins/cache/` were removed; no installed plugin uses them.
- **Codex model drift** (live config differs from `managed.json`) is a known healthcheck
  failure the user accepted; it is not changed here.
- **Manual (user):** revoke the old MCP PAT, the old classic `gh` token, and the old
  `~/.git-credentials` token on GitHub; delete the retired SSH key from the account that held it.
- This is machine state, not managed by this repo (Q12): the workspace does not store tokens,
  `.envrc` files, or SSH config.

## Verification (definition of done)

- `codex mcp list` and `gemini mcp list` show context7. `claude mcp list` shows context7 and not github.
- `claude plugin list` shows only zkfy, pyright-lsp, typescript-lsp.
- Each CLI starts without config errors (`gemini --version`, `codex --version`, a Pi prompt).
- `grep -rE '/Users/|/opt/homebrew' tools scripts` returns nothing.
- Running install twice changes nothing (idempotent merge). Tests cover a missing `ZKFY_DIR` producing a clear error.
- The healthcheck checks only the narrowed scope.
- **Manual step for the user:** revoke and rotate the GitHub PAT that was stored in `~/.claude.json`.

## Consequences

- Per-project instructions are the projects' own responsibility (a small `AGENTS.md`, with `CLAUDE.md` symlinked to it).
- A second Mac needs: clone the workspace and zkfy, set `ZKFY_DIR` (or the config file), and run `scripts/install.sh`.
