# Gemini CLI — Capability Catalog

> **STATUS: READY — unblocked; docs-mirror not yet run.** No obstacle remains; the source
> is confirmed raw Markdown in `google-gemini/gemini-cli/docs/`. See
> [ADR-0002](../adr/0002-multi-cli-parity-target.md) for the (iii) full-parity goal.

## What "mirror" means here (verified)

Gemini CLI publishes structured raw-Markdown docs **in-repo** — no SPA, no crawler, no
`/assets/` archaeology (that was the Antigravity problem, not Gemini's). Mirroring =
add a `sync_gemini()` to `scripts/sync-cli-docs.sh` that fetches the `docs/` Markdown tree
from `github.com/google-gemini/gemini-cli` (raw), banner-wraps it, and writes into
`docs/gemini/` — the same shape as `sync_claude()` / `sync_codex()`.

## Discovered native surfaces (head-start — from browsing the repo `docs/` tree)

These are confirmed to exist in Gemini CLI's docs; enumerate precisely once mirrored.

| Gemini surface | Doc | Maps to Claude | Mapping kind |
|---|---|---|---|
| Agent Skills | `docs/cli/creating-skills.md` | `skills/` | **Native — same standard.** Gemini skills use `SKILL.md` + YAML frontmatter (`name`,`description`) + `scripts/`/`references/`/`assets/`, installed to `.gemini/skills/<name>/`. Likely a near-passthrough copy, **not a shim.** |
| Hooks | `docs/hooks/{reference,writing-hooks}.md` | `hooks/` | Native hooks runtime — real target (already emitted by `gemini.sh` with event-name mapping). |
| Subagents | `docs/core/subagents.md` | `agents/` | Native subagent concept. |
| Custom commands | `docs/cli/custom-commands.md` | `commands/` | Native. |
| Memory | `docs/cli/auto-memory.md` | (Claude memory) | Native. |
| Extensions | `docs/extensions/` | (no direct Claude analogue) | Gemini-specific; note for completeness. |

> **Framing correction:** Gemini is *not* the hardest parity target. Its native surfaces
> (skills/hooks/subagents/commands/memory) largely match Claude concepts on shared
> standards, so Gemini parity looks **mostly native-mapping, minimal shim** — potentially
> a richer catalog than Codex's once built.

## Next steps

1. **Add `sync_gemini()`** to `scripts/sync-cli-docs.sh` (source: `google-gemini/gemini-cli`
   `docs/` raw Markdown). Register it in the sync flow + the weekly cron workflow.
2. Enumerate the mirrored surfaces here precisely (replace the "discovered" table above with
   doc-cited detail, mirroring `docs/codex/CAPABILITIES.md`'s structure).
3. Build the Claude-feature → Gemini-feature mapping; flag any genuine gaps needing an
   emit-time shim (expected to be few).
