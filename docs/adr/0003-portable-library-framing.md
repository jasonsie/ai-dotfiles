# The project's identity is a portable capability library, not a multi-CLI workspace

> **Superseded** by [ADR-0005](0005-global-config-single-source.md) (2026-10-05).

## Context

The project began as a fork of a Claude-Code-only workspace and was repositioned as
"multi-CLI." That framing put the *CLIs* at the center of the identity and made the
content (skills/hooks/rules/agents) feel like an implementation detail. But an audit of
the actual assets showed the opposite weighting: the durable value is a **CLI-neutral
content library** (35 skills, 14 hooks, 10 rules, 9 agents, 4 commands authored as plain
Markdown/YAML under `tools/`), and the multi-CLI adapters are a comparatively thin
delivery layer (~940 lines of emitters on a 577-line `_common.sh` engine).

## Decision

Frame the project **library-first**: it *is* a portable AI-agent capability library; the
per-CLI adapters are its **delivery mechanism**, and full multi-CLI parity (ADR-0002) is
the **delivery guarantee** ("the library reaches every CLI"), not the identity itself.
`CONTEXT.md`'s "## What" leads with the library; fork lineage is demoted to a footnote.

## Considered Options

- **Multi-CLI compiler first** — lead with the SoT engine + parity goal as the headline.
  Rejected: accurate but puts the machinery ahead of the value it moves.
- **Personal Claude workspace first** — honest about present usage. Rejected: contradicts
  the active (iii) parity goal in ADR-0002 and undersells the CLI-neutral content.
- **Portable content library first** — **chosen.** The content is the crown jewel and is
  already authored neutrally, which is precisely *why* multi-CLI delivery is feasible. This
  framing makes the parity goal follow naturally rather than stand alone.

## Consequences

- Library item counts are load-bearing in the opening paragraph. Use **logical** counts
  (dirs-with-`SKILL.md`, `.md`/`.sh` files), not raw `find -type f` (which over-counts
  skill reference files — the first draft's "58 skills" was really 35). Keep them current.
- The README still leads with the old multi-CLI framing and is consumer-facing; aligning it
  is deferred (conservative consumer messaging is acceptable until parity is verified).
- If the content library ever stops being the center of gravity (e.g. the project pivots to
  being primarily an install engine others reuse), this ADR should be revisited.
