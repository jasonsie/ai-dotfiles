# Gemini CLI — Capability Catalog

> **STATUS: BLOCKED — placeholder.** This catalog cannot be written yet.
> See [ADR-0002](../adr/0002-multi-cli-parity-target.md) for the (iii) full-parity goal.

## Why this is empty

The **(iii) full 1:1 parity** goal requires enumerating Gemini CLI's native config surfaces
before any Claude-feature → Gemini-feature mapping can be defined. That inventory does not
exist because **Gemini's upstream docs are not mirrored** into this repo:

- `docs/gemini/` contains no mirrored upstream documentation (only this placeholder).
- `scripts/sync-cli-docs.sh` has **no Gemini path** — it mirrors Claude, Codex, and
  Antigravity, but not Gemini.

Any parity claim about Gemini today is therefore **unfalsifiable**. The `gemini.sh` adapter
*emits* output (rules, hooks with event-name mapping, MCP, skills, commands), but "emits a
file" is not "verified parity," and we have no native-surface reference to check it against.

## Unblock prerequisite (the actual first task)

1. **Extend `scripts/sync-cli-docs.sh` to mirror Gemini's upstream docs** into `docs/gemini/`.
   (Precedent: the Antigravity docs turned out to be curl-able from `/assets/docs/*.md`
   despite the SPA front-end — Gemini's may be similarly reachable; investigate before
   assuming a heavier crawler is needed.)
2. Once mirrored, enumerate Gemini's native surfaces here (mirror the structure of
   `docs/codex/CAPABILITIES.md`).
3. Then build the Claude-feature → Gemini-feature mapping with per-gap shim strategies.

Until step 1 lands, this file stays a placeholder and Gemini's row in `CONTEXT.md` reads
**"Blocked."**
