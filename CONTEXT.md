# Project Context

> Context for a portable AI-agent capability library delivered to multiple CLIs
> (Claude Code / Gemini CLI / Codex CLI). Auto-loaded at session start so the AI
> understands what this project is from the first message.

## What

`ai-cli-workspace` is a **portable library of AI-agent capabilities** — **35 skills,
14 hooks, 10 rules, 9 agents, 4 commands** — authored in CLI-neutral form under `tools/`
and compiled into each CLI's native config. The library is the product; the per-CLI
adapters are its delivery mechanism.

**Full multi-CLI parity is the delivery guarantee, not the identity** (see
[ADR-0002](docs/adr/0002-multi-cli-parity-target.md)): the goal is that the *same* library
works on **Claude Code, Gemini CLI, and Codex CLI**, not just Claude. Parity = "the library
reaches every CLI," which is why the definitions are authored neutrally in the first place.

> Originally a fork of [`zeuikli/claude-code-workspace`](https://github.com/zeuikli/claude-code-workspace)
> (Claude-Code-only); repositioned around the portable-library framing above.

## Why this structure

**Single-source-of-truth principle (load-bearing)**: `tools/` is the single source of truth.
Every per-CLI config and entry file is a **generated artifact** of that truth — there is no
exception, including the files at the repo root.

`scripts/install.sh` runs adapters (`scripts/adapters/{claude,gemini,codex,rules}.sh`) that
read `tools/` and emit:

- **Per-user configs**: `.claude/`, `~/.gemini/`, `~/.codex/`
- **Repo-root entry files**: `AGENTS.md`, `GEMINI.md`, `CLAUDE.md` — all **fully
  generated** by `rules.sh` and gitignored. `rules.sh` writes each file wholesale via
  `write_if_changed`; there is no hand-maintained region in any of them.
  - The `CLAUDE.md` scaffolding (the four-layer framework, maintainer guide, etc.) is
    **not** sourced from `tools/rules/*.md` — it lives as a heredoc literal inside
    `rules.sh` (the `claude_header`). Only the `## 常駐規則` import list is derived from
    `tools/rules/manifest.yaml`. To change the scaffolding, edit the heredoc in `rules.sh`.

**⚠️ Do not edit directly** — these are all generated artifacts and will be overwritten
on the next install:
- `.claude/`, `~/.gemini/`, `~/.codex/` (per-user)
- `AGENTS.md`, `GEMINI.md`, `CLAUDE.md` (repo root — all fully generated)

**To change anything that ends up in those files, edit the source under `tools/`** and re-run
`bash scripts/install.sh`. If `tools/` doesn't yet have the right surface for what you want
to change, extend `tools/` first — never patch the generated file as a shortcut.

## Language

Precise terms for this workspace. These distinctions have caused real confusion —
keep them sharp.

**Source of truth (SoT)**:
The canonical definition a generated artifact derives from. Almost always somewhere
under `tools/`. Editing an artifact instead of its SoT is always a bug.
_Avoid_: "the config", "the real file" (ambiguous about which layer).

**Generated (fully)**:
Written *wholesale* by `write_if_changed` — the entire file is output, with **no**
hand-maintained region. `CLAUDE.md`, `AGENTS.md`, `GEMINI.md` are all fully generated.
"Fully generated" says nothing about *which* SoT: a single generated file can draw from
several (`CLAUDE.md` = scaffold from `tools/templates/claude-header.md` + rules from
`tools/rules/*.md` + import list from `manifest.yaml`).
_Avoid_: "partially generated" (no file here is — that was a stale claim).

**Clean / delete a generated file**:
`rm`-ing a generated artifact (e.g. `AGENTS.md`) is **cosmetic** — the next
`install.sh` recreates it. The durable mechanism that keeps generated files out of
version control is `.gitignore`, not deletion. "Cleaning" the working tree of a
generated file is temporary by nature.
_Avoid_: treating `rm` as a permanent removal.

**Feature parity** (a *mapping-completeness* axis):
Every Claude feature has an *emitted* equivalent on the target CLI — the adapter
produces the right file. Says nothing about whether it works. Codex is partial here;
Gemini is at zero (no catalog yet).
_Avoid_: bare "parity" (ambiguous — see verified parity).

**Verified parity** (a *runtime-correctness* axis):
An emitted equivalent is confirmed to work end-to-end on the target CLI at runtime.
The real bar. **No non-Claude CLI has any verified parity yet** — emission is not
verification. Orthogonal to feature parity: a feature can be emitted (feature-parity ✓)
yet unverified (verified-parity ✗).
_Avoid_: treating "the adapter emits it" as proof it works.

**Full 1:1 parity** (the (iii) goal — see [ADR-0002](docs/adr/0002-multi-cli-parity-target.md)):
The **conjunction** of both axes maxed — every Claude feature emitted *and* verified on a
CLI. A CLI is "complete" only when both are true.

---

## Goal: full multi-CLI parity (active)

**The north-star is (iii) full 1:1 parity** — every Claude Code feature has a working
equivalent on every supported CLI, shimming where the target CLI has no native concept.
This is an **active goal**, not inherited baggage: Claude Code is simply the furthest-built
spoke, and Gemini/Codex are destinations we are driving toward — not "kept warm."

**Parity is gated behind a per-CLI capability catalog.** "Full parity" is undefinable
without knowing each CLI's native config surface, so the first milestone for each target
CLI is a `docs/<cli>/CAPABILITIES.md` enumerating its native surfaces and the
Claude-feature → CLI-feature mapping (with an explicit shim strategy wherever no native
equivalent exists). See [ADR-0002](docs/adr/0002-multi-cli-parity-target.md).

Status uses the two parity axes from the glossary (feature parity = emitted;
verified parity = works at runtime). "Full 1:1 parity" = both complete.

| CLI | Feature parity | Verified parity | Catalog | Entry file |
|---|---|---|---|---|
| Claude Code | ✅ baseline (reference impl) | ✅ baseline | n/a — it *is* the baseline | `CLAUDE.md` |
| Codex CLI | 🟡 partial (emitters exist) | ❌ none | [`docs/codex/CAPABILITIES.md`](docs/codex/CAPABILITIES.md) | `AGENTS.md` |
| Gemini CLI | ❌ zero (no catalog) | ❌ none | [`docs/gemini/CAPABILITIES.md`](docs/gemini/CAPABILITIES.md) — **blocked**, docs not mirrored | `GEMINI.md` |

> ⚠️ **Reality check for the impatient.** The adapters already *emit* output for all three
> CLIs, but emission ≠ verified parity. Gemini/Codex output is not yet exercised end-to-end,
> and latent bugs exist (e.g. the `created:22` reporting quirk lives in exactly these
> emitters). "Emits a file" is a necessary step toward parity, not proof of it.

## Cross-CLI terminology map

Structural facts about each CLI's config surface (accurate regardless of parity progress):

| Concept | Claude Code | Gemini CLI | Codex CLI |
|---|---|---|---|
| Session entry context | `CLAUDE.md` | `GEMINI.md` | `AGENTS.md` |
| File-import syntax | `@path/to/file.md` | `@path/to/file.md` | Not supported (inlined by `install.sh`; cf. `docs/codex/import.md`) |
| Global + project layers | `~/.claude/` + `./` | `~/.gemini/` + `./` | `~/.codex/` + directory-hierarchy concatenation |
| Skill / Agent / Hook | Native (baseline) | Emitters exist (`gemini.sh`) — verified parity: none | Native concepts exist (`docs/codex/{hooks,skills-and-plugins}.md`); emitters in `codex.sh` — verified parity: none |

## Fork boundary

- **Upstream-maintained**: Claude Code native features (skills, agents, hooks, rules core)
- **Added in this fork**: Multi-CLI adapter layer, the `tools/` canonical structure, `scripts/install.sh --target=claude|gemini|codex|all`
- Inspect upstream history: `git log upstream/main -- <path>` (requires an `upstream` remote)

## Two-stage install model

- **Stage 1** — `bash scripts/install.sh` produces global artifacts under
  `~/.claude/`, `~/.gemini/`, `~/.codex/`. Skills install as marker-tracked
  copies (`.workspace-managed` sentinel), so user-added entries survive
  re-installs and removed entries are pruned on next run.
- **Stage 2** — `bash scripts/init-project.sh` (or `/init-project` from
  any CLI) runs inside a target project and writes a project-local
  `.claude/CLAUDE.md` as a strict additive layer on top of Stage 1.
  Profiles live in `tools/profiles/<dimension>.yaml`; multi-select
  composes by union of skills. Content below the
  `<!-- USER-CONTENT-BELOW -->` sentinel is preserved across re-runs.

Adding a new dimension: drop a YAML file in `tools/profiles/` listing
the skills it surfaces. No code changes required.
