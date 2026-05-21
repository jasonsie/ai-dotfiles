# Workspace Tools Checklist

> **Status legend** — `[x]` implanted in `tools/` (canonical, cross-CLI ready) · `[ ]` catalogued, not yet implanted.
>
> **Implanted** = file lives in `tools/<category>/<name>` (tracked in git, ships with the repo) and is generated/symlinked into each CLI by `scripts/install.sh`. Everything in `tools/` is the single source of truth — `.claude/`, `.gemini/`, `.codex/` are derived artifacts.

## Goal

> Customise claude-code workspace from this repo so it satisfies general software development. Organise tools from `skill` and `everything-claude-code` repos, categorise them, and add to the workspace.
>
> **Workspace must:**
> - Compatible with Codex CLI, Gemini CLI (via canonical `tools/` + per-CLI adapter)
> - Portable; plug in to different environments easily without relying on Claude's native plugin system; use a config file + directory structure approach so tools can be copied across environments without compatibility issues

## Implementation Snapshot (2026-05-21)

| Category | Implanted | Catalogued only |
|---|---|---|
| Skills | 34 | ~145 |
| Agents | 9 | 23 |
| Commands | 3 | 65 |
| Rules | 10 | — |
| Hooks | 14 | — |
| MCP servers | 0 (registry scaffolded) | — |
| Adapters (Claude/Gemini/Codex/Rules) | 4 | — |

---

## Skills

### Engineering / Development

#### Implanted (`tools/skills/`)
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

#### Catalogued (in upstream repos, not implanted)
- [ ] `coding-standards` — universal TS/JS/React/Node standards
- [ ] `backend-patterns` — backend architecture, API design, DB optimisation
- [ ] `frontend-patterns` — React, Next.js, state management, perf
- [ ] `api-design` — REST API patterns (resource naming, status, pagination)
- [ ] `mcp-server-patterns` — build MCP servers with Node/TS SDK
- [ ] `database-migrations` · `postgres-patterns` · `clickhouse-io`
- [ ] `nextjs-turbopack` · `bun-runtime` · `nuxt4-patterns`
- [ ] `django-patterns` / `django-tdd` / `django-security` / `django-verification`
- [ ] `springboot-patterns` / `springboot-tdd` / `springboot-security` / `springboot-verification`
- [ ] `laravel-patterns` / `laravel-tdd` / `laravel-security` / `laravel-verification`
- [ ] `kotlin-patterns` / `kotlin-coroutines-flows` / `kotlin-ktor-patterns` / `kotlin-exposed-patterns` / `kotlin-testing`
- [ ] `swift-concurrency-6-2` / `swift-actor-persistence` / `swift-protocol-di-testing` / `swiftui-patterns`
- [ ] `golang-patterns` / `golang-testing`
- [ ] `rust-patterns` / `rust-testing`
- [ ] `perl-patterns` / `perl-security` / `perl-testing`
- [ ] `python-patterns` / `python-testing`
- [ ] `cpp-coding-standards` / `cpp-testing`
- [ ] `java-coding-standards` / `jpa-patterns`
- [ ] `pytorch-patterns`
- [ ] `android-clean-architecture` / `compose-multiplatform-patterns` / `foundation-models-on-device`
- [ ] `migrate-to-shoehorn` — TS test migration (`as` → `@total-typescript/shoehorn`)

### Planning & Design

#### Implanted (`tools/skills/`)
- [x] `spec-interview` — interactive spec gathering
- [x] `grill-me` — relentless interview to reach shared understanding
- [x] `to-prd` — turn conversation into a PRD
- [x] `to-issues` — break plan/PRD into independently-grabbable issues
- [x] `triage` — issue triage state machine
- [x] `handoff` — compact conversation into handoff document

#### Catalogued
- [ ] `blueprint` — feature blueprint
- [ ] `ralphinho-rfc-pipeline` — RFC pipeline
- [ ] `architecture-decision-records` — capture ADRs from sessions
- [ ] `strategic-compact` — manual compaction at logical intervals

### DevOps & Quality

#### Catalogued
- [ ] `docker-patterns` — containerisation patterns
- [ ] `deployment-patterns` — release strategies
- [ ] `security-review` — security checklist for auth/input/secrets/payment
- [ ] `security-scan` — automated security scanning
- [ ] `e2e-testing` — Playwright POM, CI/CD, artifacts
- [ ] `verification-loop` — comprehensive verification system
- [ ] `tdd-workflow` — TDD enforcement (80%+ coverage)
- [ ] `ai-regression-testing` — AI-aware regression suite
- [ ] `agent-eval` / `eval-harness` — evaluation harnesses
- [ ] `agent-harness-construction` — building agent harnesses
- [ ] `plankton-code-quality` — code quality checks
- [ ] `skill-comply` / `skill-stocktake` / `skill-health` — skill governance
- [ ] `setup-pre-commit` — Husky + lint-staged + Prettier
- [ ] `git-guardrails-claude-code` — block dangerous git commands via hooks

### Productivity & Session Management

#### Implanted (`tools/skills/`)
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

#### Catalogued
- [ ] `deep-research` — multi-source research with citations
- [ ] `market-research` — market sizing & competitor analysis
- [ ] `exa-search` — neural search via Exa
- [ ] `search-first` — research-before-coding workflow
- [ ] `documentation-lookup` — Context7-based lookup
- [ ] `claude-api` — Anthropic SDK patterns
- [ ] `prompt-optimizer` — prompt optimisation
- [ ] `prompt-optimize` — slash command variant
- [ ] `iterative-retrieval` / `cost-aware-llm-pipeline` / `regex-vs-llm-structured-text`
- [ ] `dmux-workflows` — tmux + multi-agent
- [ ] `nanoclaw-repl` / `autonomous-loops` / `continuous-agent-loop` / `continuous-learning` / `continuous-learning-v2`
- [ ] `ai-first-engineering` / `agentic-engineering` / `enterprise-agent-ops`
- [ ] `claude-devfleet` / `team-builder` / `harness-optimizer`
- [ ] `context-budget` / `agent-eval` / `learn-eval`
- [ ] `configure-ecc` / `project-guidelines-example` / `rules-distill`
- [ ] `santa-method` / `click-path-audit` / `content-hash-cache-pattern`

### Content & Media

#### Catalogued
- [ ] `content-engine` — platform-native content systems
- [ ] `article-writing` — long-form authoring
- [ ] `crosspost` — multi-platform distribution
- [ ] `frontend-slides` — HTML presentations
- [ ] `liquid-glass-design` — design system
- [ ] `video-editing` — AI-assisted video pipeline
- [ ] `fal-ai-media` — fal.ai image/video/audio generation
- [ ] `videodb` — video database integration
- [ ] `x-api` — X/Twitter API integration
- [ ] `data-scraper-agent` — data scraping
- [ ] `visa-doc-translate` — document translation
- [ ] `nutrient-document-processing` — document processing
- [ ] `edit-article` — restructure / improve articles
- [ ] `obsidian-vault` — Obsidian notes management

### Business / Vertical

#### Catalogued
- [ ] `investor-outreach` / `investor-materials` — fundraising
- [ ] `carrier-relationship-management` · `customs-trade-compliance` · `energy-procurement`
- [ ] `inventory-demand-planning` · `logistics-exception-management` · `production-scheduling`
- [ ] `quality-nonconformance` · `returns-reverse-logistics`
- [ ] `scaffold-exercises` — educational exercise scaffolding

---

## Agents

#### Local & implanted (`tools/agents/`)
- [x] `architecture-explorer.md`
- [x] `code-reviewer.md`
- [x] `doc-writer.md`
- [x] `implementer.md`
- [x] `memory-compactor.md`
- [x] `researcher.md`
- [x] `reviewer.md`
- [x] `security-reviewer.md`
- [x] `test-writer.md`

#### Catalogued (in `everything-claude-code/agents/`)
- [ ] `architect.md` — system design / architecture decisions
- [ ] `build-error-resolver.md` — generic build error diagnosis
- [ ] `chief-of-staff.md` — high-level orchestration
- [ ] `cpp-build-resolver.md` / `cpp-reviewer.md`
- [ ] `go-build-resolver.md` / `go-reviewer.md`
- [ ] `java-build-resolver.md` / `java-reviewer.md`
- [ ] `kotlin-build-resolver.md` / `kotlin-reviewer.md`
- [ ] `rust-build-resolver.md` / `rust-reviewer.md`
- [ ] `python-reviewer.md`
- [ ] `database-reviewer.md`
- [ ] `doc-updater.md` / `docs-lookup.md`
- [ ] `e2e-runner.md`
- [ ] `harness-optimizer.md`
- [ ] `loop-operator.md`
- [ ] `planner.md`
- [ ] `refactor-cleaner.md`
- [ ] `tdd-guide.md`

---

## Commands

#### Local & implanted (`tools/commands/`)
- [x] `deep-review.md` — three-dimension review before commit
- [x] `load-plan.md` — print four-tier loading plan
- [x] `healthcheck.md` — workspace integrity validator

#### Catalogued (in `everything-claude-code/commands/`)
- [ ] `aside.md` — side conversation / aside
- [ ] `build-fix.md` — build error fix workflow
- [ ] `checkpoint.md` — save session checkpoint
- [ ] `claw.md` — Claw command
- [ ] `code-review.md` — code review workflow
- [ ] `cpp-build.md` · `cpp-review.md` · `cpp-test.md`
- [ ] `go-build.md` · `go-review.md` · `go-test.md`
- [ ] `kotlin-build.md` · `kotlin-review.md` · `kotlin-test.md`
- [ ] `rust-build.md` · `rust-review.md` · `rust-test.md`
- [ ] `python-review.md`
- [ ] `gradle-build.md`
- [ ] `devfleet.md` — DevFleet management
- [ ] `docs.md` — documentation generation
- [ ] `e2e.md` — E2E runner
- [ ] `eval.md` · `learn-eval.md` · `learn.md`
- [ ] `evolve.md` — evolve / improve workflow
- [ ] `harness-audit.md` — harness audit
- [ ] `instinct-export.md` · `instinct-import.md` · `instinct-status.md`
- [ ] `loop-start.md` · `loop-status.md`
- [ ] `model-route.md` — model routing
- [ ] `multi-backend.md` · `multi-execute.md` · `multi-frontend.md` · `multi-plan.md` · `multi-workflow.md`
- [ ] `orchestrate.md` — agent orchestration
- [ ] `plan.md` · `setup-pm.md` · `projects.md` · `promote.md`
- [ ] `pm2.md` — PM2 process management
- [ ] `prompt-optimize.md`
- [ ] `quality-gate.md`
- [ ] `refactor-clean.md`
- [ ] `resume-session.md` · `save-session.md` · `sessions.md`
- [ ] `skill-create.md` · `skill-health.md`
- [ ] `tdd.md`
- [ ] `test-coverage.md`
- [ ] `update-codemaps.md` · `update-docs.md`
- [ ] `verify.md`

---

## Rules (cross-CLI, `tools/rules/`)

> Manifest: `tools/rules/manifest.yaml`. Adapters concatenate into `AGENTS.md` (Codex/cross-CLI), `GEMINI.md`, and the 常駐規則 section of `CLAUDE.md`.

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

> Manifest: `tools/hooks/manifest.yaml`. Each script reads `$WORKSPACE_CLI_NAME` and `$WORKSPACE_DIR` so the same script can be wired into each CLI's native event surface.

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

> Adapters emit per-CLI native MCP config (Claude JSON `mcp_servers`, Gemini JSON `mcpServers`, Codex TOML `[mcp_servers.<name>]`). Registry is empty by default; populate manually as MCP servers come online.

#### Registry
- [x] Neutral schema scaffolded (`tools/mcp/servers.yaml`); 0 entries
- [ ] Migrate user-level MCP servers (GitHub, Figma, Gmail, Drive, Serena, Context7, Notion) into registry
- [ ] Document per-server `enabled-for` reasoning

---

## Settings Templates (`tools/settings/`)

#### Implanted
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
- [x] `docs/2026-05-21-cross-ai-cli-workspace-research.md` — cross-CLI research report
- [x] `README.md` updated with new install flow + `tools/` structure
- [x] `tools/hooks/manifest.yaml` — per-CLI event-name mapping
- [x] `tools/rules/manifest.yaml` — per-rule CLI targeting

---

## Verification Status (2026-05-21)

- [x] `bash scripts/install.sh --target=claude` — real run, 5 files unchanged on second invocation (idempotent)
- [x] `bash scripts/install.sh --target=gemini --dry-run` — exits 0, logs 22 intended actions for `~/.gemini/`
- [x] `bash scripts/install.sh --target=codex --dry-run` — exits 0, logs 23 intended actions for `~/.codex/`
- [x] `bash scripts/healthcheck.sh` — 110 PASS / 2 WARN (pre-existing) / 0 FAIL
- [x] `.claude/` symlinks: 67 total, 0 broken
- [x] `.claude/settings.json` valid JSON, 10 hook events resolved against `tools/hooks/`
- [ ] Real `--target=gemini` run on a machine with Gemini CLI installed (deferred)
- [ ] Real `--target=codex` run on a machine with Codex CLI installed (deferred)

---

## Future Work (deferred)

- [ ] Re-introduce a lockfile mechanism (e.g. `tools/manifest.lock.json`) once we need to track upstream provenance for individual `tools/skills/` entries. `skills-lock.json` was removed on 2026-05-21 — the 14 mattpocock skills are now committed to the repo as canonical content.
- [ ] Auto-sync upstream skills (`mattpocock/skills`, `everything-claude-code`) into `tools/skills/` via lockfile executor
- [ ] GitHub `gh skill` integration for publishing
- [ ] Per-CLI hook event translation beyond manifest mapping
- [ ] Curate next-batch tools from "Catalogued" sections above
- [ ] Convert the 9 implanted agents into Codex `openai.yaml` and Gemini SKILL.md wrappers via adapters (mechanism in place; tested via dry-run)
