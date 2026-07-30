# Codex CLI — Capability Catalog

> Parity catalog for the **(iii) full 1:1 parity** goal (see
> [ADR-0002](../adr/0002-multi-cli-parity-target.md)). Maps each Claude Code feature
> (`tools/<feature>/`) onto a Codex native surface, or records the shim strategy where no
> native equivalent exists. Native surfaces are cited from the mirrored upstream docs under
> `docs/codex/` — **do not treat a row as done until its output is verified end-to-end.**

## Codex native config surfaces (from mirrored upstream docs)

| Surface | Upstream doc | Notes |
|---|---|---|
| Config file | `docs/codex/config-file/config-reference.md` | `~/.codex/config.toml` (TOML, not JSON) |
| Hooks | `docs/codex/hooks.md` | Native hooks runtime — real target for Claude hooks |
| Skills | `docs/codex/skills-and-plugins.md`, `build-skills.md` | Open agent-skills standard (`agentskills.io`) — same standard Claude skills use |
| Custom prompts | `docs/codex/custom-prompts.md` | Closest analogue to Claude slash-commands |
| MCP | `docs/codex/mcp-server.md` | Native MCP support |
| Import / inlining | `docs/codex/import.md` | Codex lacks `@import`; entry context is inlined by `install.sh` |
| Agent config | `docs/codex/agent-configuration/` | Target for Claude agents |

## Claude feature → Codex mapping

| Claude feature (`tools/`) | Codex target | Status | Shim / notes |
|---|---|---|---|
| `rules/` | Inlined into `AGENTS.md` | Emitted | No `@import`; concatenated. Verify AGENTS.md ≤ 32 KiB (Codex truncates). |
| `skills/` | Codex skills (agent-skills standard) | Emitted (`codex.sh`) | **Potentially portable, not mimicked** — same standard. Verify Codex loads them. |
| `agents/` | `agent-configuration/` (`_agent_md_to_codex_yaml`) | Emitted | Verify Codex honors the emitted YAML. |
| `commands/` | `custom-prompts.md` | ❓ Unmapped | Confirm custom-prompt format, then emit. |
| `hooks/` | `~/.codex/hooks.json` (`_codex_build_hooks_json`) | Emitted | Verify events fire at runtime — the verified-parity test. |
| `mcp/` | `_codex_build_mcp_toml` | Emitted | Verify against `mcp-server.md` schema. |
| `settings/` | `config.toml` | Emitted | Verify against `config-reference.md`. |

## Open questions before Codex can be declared "complete"

1. Do the emitted hooks actually fire under Codex CLI at runtime? (necessary parity proof)
2. Are Claude skills loadable by Codex unchanged, or do they need transformation?
3. Is the `created:22` reporting quirk in `codex.sh` masking real non-idempotency? (see ONBOARDING)
4. What has *no* Codex equivalent and therefore needs a genuine shim (vs. a native mapping)?
