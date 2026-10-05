# Multi-CLI support target is (iii) full 1:1 parity, gated behind capability catalogs

> **Superseded** by [ADR-0005](0005-global-config-single-source.md) (2026-10-05).

## Context

This workspace is a fork of a Claude-Code-only project, repositioned as multi-CLI
(Claude / Gemini / Codex). Whether multi-CLI is an *active goal* or *inherited-but-idle
capability* was never pinned down — the `CONTEXT.md` multi-CLI section was rewritten three
times (from "Basic / Partial (TBD)", to "emitters present, not regularly exercised", to the
current parity framing) because the underlying intent kept flipping. This ADR fixes the
intent so the prose stops churning.

## Decision

Multi-CLI parity is an **active goal**, and the target is **(iii) full 1:1 parity**: every
Claude Code feature gets a working equivalent on every supported CLI, shimming where the
target CLI has no native concept. Claude Code is the reference implementation; other CLIs
are driven toward it.

Because "full parity" is undefinable without knowing each CLI's native surface, (iii) is
**gated behind a per-CLI capability catalog** (`docs/<cli>/CAPABILITIES.md`): enumerate the
CLI's native config surfaces, map each Claude feature onto one, and record an explicit shim
strategy for genuine gaps. No parity claim about a CLI is valid until its catalog exists.

## Considered Options

- **(i) Rules + entry-context parity only** — rejected: too thin; abandons skills/agents/
  hooks that the adapters already emit.
- **(ii) Native-bounded parity** (emit only what each CLI natively supports) — rejected in
  favour of the more ambitious (iii), though (iii) collapses toward (ii) in practice wherever
  a native equivalent genuinely doesn't exist (the shim *is* the honest bound).
- **(iii) Full 1:1 parity** — **chosen.** Bold, but Codex evidence supports feasibility:
  `docs/codex/hooks.md` (native hooks), `docs/codex/{skills-and-plugins,build-skills}.md`
  (skills on the same open agent-skills standard Claude uses), `import.md`, `custom-prompts.md`,
  `mcp-server.md`, `config-file/` all exist — the native concepts to map onto are largely present.

## Consequences

- **Codex** is unblocked: its upstream docs are already mirrored under `docs/codex/`, so its
  catalog can be built now.
- **Gemini** at decision time was recorded as "blocked" on a prerequisite: `docs/gemini/`
  not mirrored and `sync-cli-docs.sh` has no Gemini path.
  - **Update (mirror implemented):** the "blocker" was trivial. `google-gemini/gemini-cli`
    publishes raw-Markdown docs in-repo under `docs/` (skills via `SKILL.md`, hooks,
    subagents, commands, memory), so mirroring became a routine `sync_gemini()` task (Git Trees
    API discovery + raw fetch, ~94 files into `docs/gemini/upstream/` per ADR-0004). Gemini's
    native surfaces largely match Claude's on shared standards. Mirror now runs in
    `.github/workflows/sync-cli-docs.yml`. See [`docs/gemini/CAPABILITIES.md`](../gemini/CAPABILITIES.md).
- "Emits a file" is downgraded from evidence-of-support to a necessary-but-insufficient step.
  Parity requires end-to-end verification, which no non-Claude CLI has yet.
- Graduating a CLI from "in progress" to "complete" is itself an ADR-worthy event (records
  that verification actually happened).
