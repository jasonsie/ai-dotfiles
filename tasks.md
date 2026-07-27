# Workspace Tools Checklist

> **Archive — frozen 2026-05-21.** This file is a historical record of the one-time
> port that organised tools from the `skill` and `everything-claude-code` repos into the
> canonical `tools/` source of truth. The migration is complete. Live work is now tracked
> via the memory/session system (`MEMORY.md`, session summaries), not here.
>
> Only implanted tools are recorded below. The former "Catalogued (not yet implanted)"
> menus and the dated verification block have been removed — they were a live backlog and a
> point-in-time quality assertion, neither of which belongs in a frozen archive. ECC's
> catalogued skills remain reachable live as `everything-claude-code:*` plugins, so porting
> them into `tools/` would only duplicate them.
>
> **Status legend** — `[x]` implanted in `tools/` (canonical, cross-CLI ready).
>
> **Implanted** = file lives in `tools/<category>/<name>` (tracked in git, ships with the repo)
> and is generated/symlinked into each CLI by `scripts/install.sh`. Everything in `tools/` is the
> single source of truth — `.claude/`, `.gemini/`, `.codex/` are derived artifacts.

## Goal (as scoped for the migration)

> Customise claude-code workspace from this repo so it satisfies general software development.
> Organise tools from `skill` and `everything-claude-code` repos, categorise them, and add to
> the workspace.
>
> **Workspace must:**
> - Compatible with Codex CLI, Gemini CLI (via canonical `tools/` + per-CLI adapter)
> - Portable; plug in to different environments easily without relying on Claude's native plugin
>   system; use a config file + directory structure approach so tools can be copied across
>   environments without compatibility issues

## Implementation Snapshot (implanted at freeze)

| Category | Implanted |
|---|---|
| Skills | 35 |
| Agents | 9 |
| Commands | 4 |
| Rules | 10 |
| Hooks | 14 |
| MCP servers | 0 (registry scaffolded) |
| Adapters (Claude/Gemini/Codex/Rules) | 4 |

---

## Skills

### Engineering / Development (`tools/skills/`)
- [x] `debug` — debugging workflow
- [x] `deep-review` — pre-commit multi-dimensional review
- [x] `perf` — performance analysis
- [x] `map` — codebase map exploration
- [x] `add-skill` — scaffold new skills
- [x] `ecc-feature-guide` — ECC feature reference (stub)
- [x] `frontend-design` — frontend design guidance (anti-AI-slop)
- [x] `diagnose` — disciplined diagnosis loop for hard bugs / perf regressions
- [x] `tdd` — red-green-refactor with integration tests
- [x] `grill-with-docs` — stress-test plans against existing domain model
- [x] `improve-codebase-architecture` — refactoring, consolidating tight coupling, testability
- [x] `prototype` — throwaway prototype for design exploration
- [x] `zoom-out` — broader context on unfamiliar code

### Planning & Design (`tools/skills/`)
- [x] `spec-interview` — interactive spec gathering
- [x] `grill-me` — relentless interview to reach shared understanding
- [x] `to-prd` — turn conversation into a PRD
- [x] `to-issues` — break plan/PRD into independently-grabbable issues
- [x] `triage` — issue triage state machine
- [x] `handoff` — compact conversation into handoff document

### Productivity & Session Management (`tools/skills/`)
- [x] `prime` — workspace cold-start primer
- [x] `retro` — session retrospective
- [x] `context-report` — context usage report
- [x] `cost-tracker` — cost analysis
- [x] `load-plan` — print four-tier loading plan
- [x] `agent-team` — multi-agent coordination
- [x] `research` — research workflow
- [x] `research-best-practices` — research methodology
- [x] `blog-analyzer` — blog-content analysis
- [x] `writing` — copywriting workflow
- [x] `marketing` — marketing strategy
- [x] `pm` — sprint / status report / multi-agent PM
- [x] `caveman` — ultra-compressed communication mode (~75% token reduction)
- [x] `write-a-skill` — skill authoring with progressive disclosure
- [x] `setup-matt-pocock-skills` — bootstrap engineering-skill blocks

### Project Setup (`tools/skills/`)
- [x] `init-project` — Stage-2 project-local `.claude/CLAUDE.md` scaffolder (profile-composed)

---

## Agents (`tools/agents/`)
- [x] `architecture-explorer.md`
- [x] `code-reviewer.md`
- [x] `doc-writer.md`
- [x] `implementer.md`
- [x] `memory-compactor.md`
- [x] `researcher.md`
- [x] `reviewer.md`
- [x] `security-reviewer.md`
- [x] `test-writer.md`

---

## Commands (`tools/commands/`)
- [x] `deep-review.md` — three-dimension review before commit
- [x] `load-plan.md` — print four-tier loading plan
- [x] `healthcheck.md` — workspace integrity validator
- [x] `init-project.md` — Stage-2 project initialiser

---

## Rules (cross-CLI, `tools/rules/`)

> Manifest: `tools/rules/manifest.yaml`. Adapters concatenate into `AGENTS.md` (Codex/cross-CLI),
> `GEMINI.md`, and the 常駐規則 section of `CLAUDE.md`.

#### Portable to all three CLIs
- [x] `core.md` — language, git workflow, think-before-coding, validation
- [x] `subagent-strategy.md` — sub-agent delegation + advisor strategy
- [x] `context-management.md` — context window, prompt caching architecture
- [x] `token-efficiency.md` — efficiency tiers + compact hints
- [x] `session-management.md` — continue / rewind / clear / compact
- [x] `cli-enhancers.md` — ast-grep / shellcheck / sd / scc / yq inventory
- [x] `routines.md` — scheduled / API / webhook routines + Slack integration

#### Claude-only (kept out of AGENTS.md / GEMINI.md)
- [x] `auto-sync.md` — Claude-specific hook events and auto-sync
- [x] `opus47-best-practices.md` — Opus 4.7 effort levels + adaptive thinking
- [x] `subagent-advanced.md` — Claude Tasks API + advanced subagent coordination

---

## Hooks (cross-CLI, `tools/hooks/`)

> Manifest: `tools/hooks/manifest.yaml`. Each script reads `$WORKSPACE_CLI_NAME` and
> `$WORKSPACE_DIR` so the same script can be wired into each CLI's native event surface.

#### Lifecycle
- [x] `session-start.sh` (Claude `SessionStart` / Gemini `session-start` / Codex `pre-session`)
- [x] `session-stop.sh` (Claude `Stop` / Gemini `session-end` / Codex `post-session`)
- [x] `user-prompt.sh` (Claude `UserPromptSubmit` / Gemini `user-prompt` / Codex `pre-prompt`)

#### Tool execution
- [x] `pre-tool.sh` (Claude `PreToolUse(bash)` / Gemini `pre-tool` / Codex `pre-tool`)
- [x] `post-edit.sh` (Claude `PostToolUse(Edit|Write)` / Gemini `post-tool` / Codex `post-tool`)

#### Context (Claude-only)
- [x] `pre-compact.sh`
- [x] `post-compact.sh`
- [x] `instructions-loaded.sh`
- [x] `subagent-start.sh`
- [x] `subagent-stop.sh`

#### Memory helpers (not events; invoked by other hooks)
- [x] `memory-archive.sh`
- [x] `memory-pull.sh`
- [x] `memory-sync.sh`
- [x] `memory-update-hook.sh`

---

## MCP Servers (`tools/mcp/servers.yaml`)

> Adapters emit per-CLI native MCP config (Claude JSON `mcp_servers`, Gemini JSON `mcpServers`,
> Codex TOML `[mcp_servers.<name>]`). Registry is empty at freeze; populate manually as MCP
> servers come online.

- [x] Neutral schema scaffolded (`tools/mcp/servers.yaml`); 0 entries

---

## Settings Templates (`tools/settings/`)
- [x] `claude.json.tmpl` — Claude settings template (hooks/MCP placeholders)
- [x] `gemini.json.tmpl` — Gemini settings template
- [x] `codex.toml.tmpl` — Codex settings template

---

## Infrastructure

### Installer & adapters (`scripts/`)
- [x] `scripts/install.sh` — idempotent entry point (`--target=all|claude|gemini|codex`, `--dry-run`, `--force`)
- [x] `scripts/adapters/_common.sh` — shared helpers (log, symlink, render, summary)
- [x] `scripts/adapters/claude.sh` — Claude adapter
- [x] `scripts/adapters/gemini.sh` — Gemini adapter
- [x] `scripts/adapters/codex.sh` — Codex adapter
- [x] `scripts/adapters/rules.sh` — AGENTS.md / GEMINI.md / CLAUDE.md generator
- [x] `scripts/healthcheck.sh` — extended with `tools/` structure + symlink + installer infra checks

### Generated memory files
- [x] `AGENTS.md` (repo root) — portable rules for Codex / cross-CLI
- [x] `GEMINI.md` (repo root) — portable rules for Gemini
- [x] `CLAUDE.md` (repo root) — `@import` of portable + Claude-only rules

### Documentation
- [x] `tools/README.md` — canonical-source contract
- [x] `README.md` updated with new install flow + `tools/` structure
- [x] `tools/hooks/manifest.yaml` — per-CLI event-name mapping
- [x] `tools/rules/manifest.yaml` — per-rule CLI targeting
