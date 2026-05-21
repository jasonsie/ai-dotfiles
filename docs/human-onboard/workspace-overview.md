# Workspace Overview — claude-code-workspace

> tags: [onboarding, architecture, human-readable]
> Last updated: 2026-05-20

## What is this repo?

This is **not an application codebase**. It is a personal Claude Code configuration workspace — a self-updating set of instructions, hooks, agents, and skills that augment how Claude Code behaves across every project you open.

Think of it as your Claude Code "dotfiles". Install it once globally, and it applies to all sessions.

---

## Mental Model: The 4-Tier Load Framework

Every session loads instructions in layers. Each tier has a cost and a trigger:

```
🔴 Real-time   SessionStart hook → session-init.sh runs
                CLAUDE.md body loaded (~708 tokens raw, ~100 effective with caching)

🟡 Auto        3 rules always imported by CLAUDE.md
                core.md + subagent-strategy.md + context-management.md
                (~1,184 tokens, ~177 effective with caching)

🟢 On-demand   16 skills + 6 rules — loaded ONLY when you say the trigger keyword
                0 tokens until invoked (e.g. /debug, /deep-review, /prime)

⚪ Skip         docs/, archive/ — never loaded; read manually when needed
```

**Key design principle**: With prompt caching (85% hit rate), total fixed overhead per session is about **284 effective tokens** — the rest costs nothing until used.

---

## Directory Map

```
.
├── CLAUDE.md                   ← The root instruction file. ~/.claude/CLAUDE.md points here.
├── prompts.md                  ← Reusable prompt templates
├── Memory.md                   ← Legacy per-session memory (monitored for size limits)
├── tasks.md                    ← Current session task list
│
├── .claude/
│   ├── settings.json           ← Hook wiring, model selection, timeout env vars
│   ├── agents/                 ← 9 sub-agent definitions (researcher, implementer, etc.)
│   ├── hooks/                  ← 11 bash scripts tied to Claude Code lifecycle events
│   ├── rules/                  ← 10 rule files (3 always-on, 7 on-demand)
│   ├── skills/                 ← 16 slash-command skill definitions
│   ├── HANDOFF.md              ← Notes for resuming a paused session
│   └── REFERENCES.md           ← Official Claude Code docs cross-reference
│
├── docs/                       ← Deep-dive docs — NEVER auto-loaded, read manually
│   ├── INDEX.md                ← Docs index with "when to read" guidance
│   ├── human-onboard/          ← ← You are here
│   └── *.md                    ← Architecture decisions, research, migration guides
│
└── scripts/
    └── healthcheck.sh          ← Validates the entire workspace (run this after changes)
```

---

## How a Session Starts (Step by Step)

Steps 1–3 happen automatically before you type anything. Steps 4–7 are triggered by your actions.

**Automatic (system-driven):**

1. **`SessionStart`** fires → `session-init.sh` runs *(system)*
   - Detects local vs cloud environment
   - Checks a 300-second fetch cache (skips network call if recent)
   - Pulls latest from GitHub via sparse-checkout (only `.claude/` + root `.md` files)
   - Writes `~/.claude/CLAUDE.md` as an `@`-import pointing here
   - **DEDUP check**: if the current project *is* the workspace repo, writes a lightweight stub instead — prevents the same instructions loading twice

2. **CLAUDE.md loads** → auto-imports 3 core rules via `@` references *(system)*

3. **`UserPromptSubmit`** fires → injects a sub-agent delegation reminder into context *(system, before every prompt)*

**Human-triggered:**

4. **You (human) type a prompt** → Claude responds using the loaded instructions

5. **You (human) run `git commit`** → `PreToolUse(bash)` hook intercepts it and gates on `/deep-review`

6. **Claude edits a file** → `PostToolUse(Edit|Write)` validates `.sh`/`.json`/`.py` syntax *(triggered by Claude's tool use, not your editor)*

7. **You (human) run `/compact`** → `PreCompact` prompts to confirm Auto Memory is preserved

---

## The 3-Tier Model Strategy

Claude Code uses three models for different jobs:

| Role | Model | Used for |
|------|-------|----------|
| **Executor** | `claude-sonnet-4-6` | Daily work: coding, testing, searching |
| **Explorer** | `claude-haiku-4-5` | Research spanning 10+ files (fast + cheap) |
| **Advisor** | `claude-opus-4-7` | Architecture decisions, security audits — only when truly needed |

The `advisor()` tool lets the current session consult Opus in a single turn without spawning a new agent. Use it sparingly — it's the expensive path.

---

## Skills (Slash Commands)

Skills are invoked with `/skill-name`. Each lives in `.claude/skills/<name>/SKILL.md`.

| Skill | When to use |
|-------|------------|
| `/prime` | Cold-start: scan a new/unfamiliar repo |
| `/load-plan` | See all available skills + their token costs |
| `/debug` | Systematic bug investigation with root-cause analysis |
| `/deep-review` | 3-dimension parallel code review (security, performance, style) — required before commit |
| `/perf` | Performance profiling and optimization workflow |
| `/map` | Generate a semantic symbol map of a codebase |
| `/spec-interview` | Interview-driven spec generation before large features |
| `/research` | Structured research workflow with source synthesis |
| `/marketing` | GTM planning, A/B testing, competitive analysis |
| `/writing` | Copywriting with AIDA/PAS/FAB frameworks |
| `/pm` | Sprint planning, prioritization, status reports |
| `/agent-team` | Fan-out to multiple parallel workers for large tasks |
| `/retro` | Session retrospective — key decisions + improvements |
| `/context-report` | Token efficiency analysis for current session |
| `/add-skill` | Guided workflow to create a new skill |
| `/blog-analyzer` | Analyze claude.com/blog articles for workspace improvements |

---

## Agents (Sub-agents)

Agents are spawned via the `Agent` tool with `subagent_type`. Each is defined in `.claude/agents/<name>.md`.

| Agent | Job |
|-------|-----|
| `researcher` | Investigate 10+ files; returns summary only (Haiku 4.5) |
| `implementer` | Writes and validates code; runs lint + tests |
| `test-writer` | Generates tests for staged changes |
| `code-reviewer` | Reviews a single file or function for quality |
| `security-reviewer` | Scans for auth, injection, and data-handling vulnerabilities |
| `reviewer` | Deep cross-module review — Opus 4.7, use sparingly |
| `architecture-explorer` | Maps API routes, schemas, module dependencies |
| `doc-writer` | Writes/updates README, CHANGELOG, API docs |
| `memory-compactor` | Compresses Memory.md when it approaches the 200-line limit |

**Delegation rule**: If a task reads 10+ files, produces heavy tool output, or can be split into 3+ independent subtasks — delegate to a sub-agent. Otherwise, handle inline.

---

## Hooks Reference

All hooks live in `.claude/hooks/` and are wired in `.claude/settings.json`.

| Hook file | Event | What it does |
|-----------|-------|-------------|
| `session-init.sh` | `SessionStart` | Fetch + DEDUP + global CLAUDE.md write |
| `user-prompt-submit.sh` | `UserPromptSubmit` | Inject sub-agent delegation reminder |
| `pre-commit-review.sh` | `PreToolUse(bash)` | Gate commits behind `/deep-review` |
| `post-edit.sh` | `PostToolUse(Edit\|Write)` | Validate `.sh`/`.json`/`.py` syntax |
| `pre-compact.sh` | `PreCompact` | Remind to confirm Auto Memory |
| `post-compact.sh` | `PostCompact` | Confirm summary quality |
| `session-stop.sh` | `Stop` | Task completion notification |
| `instructions-loaded.sh` | `InstructionsLoaded` | Debug-only (requires `CLAUDE_DEBUG=1`) |
| `subagent-start.sh` | `SubagentStart` | Debug-only (requires `CLAUDE_DEBUG=1`) |
| `subagent-stop.sh` | `SubagentStop` | Debug-only (requires `CLAUDE_DEBUG=1`) |
| `memory-sync.sh` | (manual) | Memory sync utilities |

Exit code convention: `0` = continue, `1` = warn + continue, `2` = **block** the tool call.

---

## Non-Obvious Design Decisions

### Why sparse-checkout?
`session-init.sh` only fetches `.claude/` and root `.md` files — not the full repo. This cuts initial clone time from ~1,000–1,500ms to ~500–800ms and reduces transport by 40–60%. The tradeoff: `docs/` is never available in cloud sessions unless you explicitly `git fetch`.

### Why the DEDUP stub?
When you open Claude Code *inside* this workspace repo, `session-init.sh` detects it (by checking if `CLAUDE_PROJECT_DIR/CLAUDE.md` references `zeuikli/claude-code-workspace`) and writes a stub instead of the full `@` reference. Without this, CLAUDE.md would load twice — wasting ~708 tokens per session.

### Why both skills and rules?
Rules (`rules/*.md`) define *standards* — what to do and what to avoid. Skills (`skills/*/SKILL.md`) define *workflows* — step-by-step procedures for specific tasks. Rules are always authoritative; skills are invoked on demand.

### Why `disable-model-invocation: true` on most skills?
This prevents Claude from deciding the skill content is "just documentation" and summarizing it. With this flag, the skill's markdown is injected directly as instructions — behavior is deterministic.

---

## Maintenance

### After any change to the workspace:
```bash
bash scripts/healthcheck.sh
```

This validates: JSON syntax, hook bash syntax, hook executable bits, agent/skill frontmatter, CLAUDE.md line count, git remote reachability, Memory.md size, timeout env vars, and internal `@` links.

### Adding a new skill:
Use `/add-skill` — it walks you through the correct SKILL.md format and frontmatter requirements.

### Adding a new hook:
1. Create the script in `.claude/hooks/<name>.sh`
2. Wire it in `.claude/settings.json` under the appropriate event
3. Run `bash scripts/healthcheck.sh` to verify

### Keeping docs out of Claude's context:
Never add `@docs/...` imports to `CLAUDE.md` or any rule file. Docs are in the `⚪ Skip` tier intentionally. Add a row to `docs/INDEX.md` instead.
