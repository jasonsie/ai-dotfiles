# Onboarding Guide: ai-cli-workspace

> Human maintainer cheatsheet. **Architecture lives in [`CONTEXT.md`](../../CONTEXT.md)**
> (the authoritative source, auto-loaded into every AI session) — this file deliberately
> does *not* restate it. Here you'll find only the practical, human-facing material:
> tech stack, entry points, tasks, and traps. For consumer-facing docs see `README.md`.

## One-line orientation

`ai-cli-workspace` is a **configuration generator**, not an application: one canonical
definition under `tools/` compiled into per-CLI native config for Claude Code, Gemini
CLI, and Codex CLI. The "output" is dotfiles in `$HOME`, plus the repo-root entry files.
**Why it's shaped this way → [`CONTEXT.md`](../../CONTEXT.md).**

## Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Language | **Bash** | No language manifest — no `package.json`, `go.mod`, etc. |
| Bash version | **4+ required** | `sync-cli-docs.sh` uses `mapfile`; macOS `/bin/bash` is 3.2. Use `/opt/homebrew/bin/bash`. |
| Config formats | YAML, TOML, JSON, Markdown | YAML parsed via a Python helper (`parse_yaml_with_python`) |
| CI | GitHub Actions | `shellcheck --severity=warning`, `bash -n`, markdownlint |
| Tests | **None** | No test suite exists. CI is lint + syntax + hook dry-run only. |

## Key Entry Points

| Path | Role |
|---|---|
| `scripts/install.sh` | **Stage 1.** Arg parsing, target validation, adapter dispatch. Start here. |
| `scripts/adapters/_common.sh` | The engine. Idempotency, safe-delete, pruning, templating. |
| `scripts/adapters/{claude,gemini,codex}.sh` | Per-CLI emitters. |
| `scripts/adapters/rules.sh` | Emits the three root entry files. Scaffold for `CLAUDE.md` is `tools/templates/claude-header.md` (see ADR-0001). |
| `tools/rules/manifest.yaml` | Maps each rule → target CLIs + `order`. Register new rules here. |
| `scripts/init-project.sh` | **Stage 2.** Writes project-local `.claude/CLAUDE.md`. |
| `scripts/sync-cli-docs.sh` | Mirrors upstream CLI docs into `docs/` (weekly cron). |

## Idempotency — the invariant to protect

`write_if_changed` (`_common.sh:453`) compares existing content to new and logs
`Unchanged` when equal. Verify before committing:

```bash
bash scripts/install.sh --dry-run --target=all
```

Expect `updated: 0` and a large `unchanged` count.

> **Known reporting quirk (cosmetic, not a correctness bug).** The Gemini agent-skill,
> agent, and command emitters (`gemini.sh:235/241/268/273`, `codex.sh:194/198`) call
> `summary_track created` *unconditionally* — they never diff against the destination.
> A fully-installed workspace therefore reports `created: 22` when nothing changed.
> The emitted files are still correct; only the summary line is misleading. Judge
> idempotency by `updated: 0`, not by `created`.

## Common Tasks

```bash
bash scripts/install.sh --dry-run --target=all   # preview (ALWAYS before commit)
bash scripts/install.sh --target=all             # apply
bash scripts/healthcheck.sh                      # verify install health
bash scripts/init-project.sh                     # Stage 2, from a target project
shellcheck --severity=warning scripts/**/*.sh    # match CI locally
```

## Where to Look

| I want to… | Edit… |
|---|---|
| Add/change a rule | `tools/rules/*.md` **+ register in `manifest.yaml`** |
| Add a skill | `tools/skills/<name>/SKILL.md` |
| Add an agent | `tools/agents/<name>.md` |
| Add a hook | `tools/hooks/*.sh` + `tools/hooks/manifest.yaml` |
| Change the `CLAUDE.md` scaffold | `tools/templates/claude-header.md` (see ADR-0001) |
| Change per-CLI emission | `scripts/adapters/<cli>.sh` |
| Change copy/prune/idempotency | `scripts/adapters/_common.sh` |
| Change a root entry file | ❌ Never directly — edit `tools/`, re-run `install.sh` |

## Conventions

- **Commits**: Conventional Commits with scope — `fix(sync):`, `feat(stage-2):`,
  `refactor(install):`, `ci:`. PRs squash-merge with `(#N)` appended.
- **Branches**: `fix/…`, `feat/…` (e.g. `fix/sync-script-bash32-portability`).
- **Shell style**: `set -euo pipefail`; `local` vars; `log_info/warn/ok/err` helpers,
  never bare `echo`; guard destructive ops with `_assert_safe_rm_target`.
- **Dry-run is a first-class path** — every mutating branch needs an `is_dry_run` arm.
- **Docs**: Traditional Chinese primary, English supported.

## Traps

1. **Editing generated files.** `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.claude/` are all
   output — *fully* generated (see CONTEXT.md). Changes vanish on next install. To change
   `CLAUDE.md` scaffolding edit `tools/templates/claude-header.md`, not the file itself.
2. **macOS bash 3.2.** `sync-cli-docs.sh` needs bash 4+ (`mapfile`).
3. **New rule not appearing?** You created the `.md` but forgot `manifest.yaml`.
4. **No test suite.** `--dry-run` + `healthcheck.sh` are your only safety net.
5. **CI won't catch generated-artifact drift** — those checks were deliberately removed
   in `a30c9bf` because the artifacts are gitignored.
