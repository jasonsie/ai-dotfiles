# Hooks, Memory & Session Lifecycle

Reference guide for how everything-claude-code manages persistence, memory, and hooks throughout a conversation.

---

## 1. Terminology Map

| Term | What It Means | Unit / Scope |
|------|--------------|--------------|
| **Session** | One Claude Code conversation from open to close (or context exhaustion) | A single CLI invocation; persisted as a `~/.claude/sessions/YYYY-MM-DD-<id>-session.tmp` markdown file |
| **Conversation memory** | The active context window | Ephemeral — lost on compaction or session end |
| **Session file** | Auto-generated markdown summary of a session | Written by Stop hook after every response; loaded by SessionStart hook next time |
| **Learned skill** | A reusable pattern extracted from a session | Markdown file at `~/.claude/skills/learned/*.md`; created via `/learn` or `/learn-eval` |
| **Instinct** | An atomic learned behavior with confidence scoring (v2) | YAML at `~/.claude/homunculus/`; project-scoped by git remote hash |
| **Rule** | A permanent, hand-authored guideline | Static markdown in `rules/common/` + `rules/<language>/` |
| **CLAUDE.md** | Project/user-level persistent instructions | Auto-loaded at session start; `~/.claude/CLAUDE.md` (global) + `<project>/CLAUDE.md` (project) |
| **MEMORY.md** | Claude Code's native persistent memory index | Built-in feature, not plugin-managed; referenced by `/learn-eval` for overlap checking |
| **Hook profile** | Gating tier for which hooks run | `minimal` / `standard` (default) / `strict`; set via `ECC_HOOK_PROFILE` |
| **Observation** | A captured tool-use event for learning | JSONL entry in `observations.jsonl`; captured by pre/post observe hooks |
| **State store** | Structured persistence for orchestration | SQLite at `~/.claude/ecc/state.db`; tracks multi-worker workflows |

---

## 2. Persistence Layer Hierarchy

Highest to lowest priority:

```
Conversation context (ephemeral, current window)
    ↕ SessionStart injects / PreCompact saves
Session files (~/.claude/sessions/*.tmp, 7-day lookback)
    ↕ /learn, /learn-eval extract patterns
Learned skills (~/.claude/skills/learned/)
    ↕ continuous-learning-v2 auto-captures
Instincts (~/.claude/homunculus/projects/<hash>/)
    ↕ /promote moves to global when seen in 2+ projects
Global instincts (~/.claude/homunculus/instincts/)
    ↕ /evolve clusters into higher-level structures
Rules (rules/common/ + rules/<lang>/) — permanent
CLAUDE.md — permanent project/user instructions
Settings (.claude/settings*.json) — permanent config
```

---

## 3. Conversation Lifecycle with All Hooks

```
┌─────────────────────────────────────────────────┐
│ SESSION BEGINS                                   │
├─────────────────────────────────────────────────┤
│ [SessionStart] session-start.js                  │
│   • Load last session summary (≤7 days old)      │
│   • Detect package manager, project type         │
│   • Report learned skills count & aliases        │
│   Profiles: minimal, standard, strict            │
└──────────────────┬──────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────┐
│ USER SENDS MESSAGE → CLAUDE PICKS A TOOL         │
└──────────────────┬──────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────┐
│ [PreToolUse] — before tool executes              │
├─────────────────────────────────────────────────┤
│ auto-tmux-dev.js     Bash      always  TRANSFORM │
│   → rewrites dev server cmds to run in tmux      │
│ pre-bash-tmux-reminder.js  Bash  strict  WARN    │
│   → warn if long cmd outside tmux                │
│ pre-bash-git-push-reminder.js  Bash  strict WARN │
│   → warn before git push                         │
│ doc-file-warning.js  Write  standard+  WARN      │
│   → warn on non-standard doc files               │
│ suggest-compact.js  Edit|Write  standard+  WARN  │
│   → suggest /compact every 25 calls after 50     │
│ observe.sh           ALL   standard+  ASYNC      │
│   → capture tool start → observations.jsonl      │
│ insaits-security.js  Bash|Write|Edit  OPT-IN     │
│   → security scan (requires ECC_ENABLE_INSAITS)  │
└──────────────────┬──────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────┐
│ TOOL EXECUTES                                    │
└──────────────────┬──────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────┐
│ [PostToolUse] — after tool completes             │
├─────────────────────────────────────────────────┤
│ post-bash-pr-created.js  Bash   standard+        │
│   → log PR URL after gh pr create                │
│ post-bash-build-complete.js  Bash  standard+ ASYNC│
│   → log after build commands                     │
│ quality-gate.js  Edit|Write|MultiEdit  std+ ASYNC│
│   → biome/prettier/gofmt/ruff checks             │
│ post-edit-format.js     Edit    standard+        │
│   → auto-format JS/TS (Biome or Prettier)        │
│ post-edit-typecheck.js  Edit    standard+        │
│   → tsc --noEmit on edited .ts/.tsx              │
│ post-edit-console-warn.js  Edit  standard+       │
│   → warn about console.log in edited files       │
│ observe.sh              ALL     standard+  ASYNC │
│   → capture tool result → observations.jsonl     │
└──────────────────┬──────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────┐
│ CLAUDE FINISHES RESPONSE                         │
├─────────────────────────────────────────────────┤
│ [Stop] — after every assistant turn              │
│ check-console-log.js   all  standard+            │
│   → audit git-modified files for console.log     │
│ session-end.js         all  all profiles   ASYNC │
│   → persist session summary to ~/.claude/sessions│
│ evaluate-session.js    all  all profiles   ASYNC │
│   → if 10+ messages, flag for pattern extraction │
│ cost-tracker.js        all  all profiles   ASYNC │
│   → log tokens/cost to ~/.claude/metrics/        │
└──────────────────┬──────────────────────────────┘
                   ▼
          (repeat per turn)
                   ▼
┌─────────────────────────────────────────────────┐
│ [PreCompact] — if context compaction triggered   │
│ pre-compact.js         standard+                 │
│   → timestamp to compaction log                  │
│   → append marker to active session file         │
└──────────────────┬──────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────┐
│ SESSION ENDS                                     │
├─────────────────────────────────────────────────┤
│ [SessionEnd] session-end-marker.js  all  ASYNC   │
│   → lifecycle marker (pass-through)              │
└─────────────────────────────────────────────────┘
```

---

## 4. Knowledge Promotion Path

```
Tool observations (JSONL, every tool call)
  → Instincts (project-scoped, confidence 0.3–0.9, decays over time)
    → Global instincts (/promote when seen in 2+ projects, confidence ≥0.8)
      → Evolved structures (/evolve clusters into skills/commands/agents)
```

Separately: session summaries → `/learn` or `/learn-eval` → learned skills (curated, human-approved)

---

## 5. What's NOT Plugin-Managed

- **MEMORY.md** — Claude Code's built-in auto-memory. The plugin doesn't write to it, but `/learn-eval` checks it for overlap.
- **`.claude/settings.json`** — Claude Code native config. The plugin uses `hooks/hooks.json` via the plugin system instead.
- **Context window** — managed by Claude Code itself; the plugin can only inject into it (SessionStart) or react to its loss (PreCompact).
