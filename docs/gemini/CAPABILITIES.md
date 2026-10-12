# Gemini CLI — Capability Catalog

> **Superseded** by [ADR-0005](../adr/0005-global-config-single-source.md): full parity and the
> `tools/<feature>/` emitters were retired. Kept as a reference for native surfaces only.

> Parity catalog for the **(iii) full 1:1 parity** goal (see
> [ADR-0002](../adr/0002-multi-cli-parity-target.md)). Maps each Claude Code feature
> (`tools/<feature>/`) onto a Gemini CLI native surface, or records the shim strategy where
> no native equivalent exists. Native surfaces are cited from the mirrored upstream docs
> under `docs/gemini/upstream/` — **do not treat a row as done until its output is verified
> end-to-end** (no Gemini row has *verified parity* yet; see the CONTEXT.md glossary).

## Gemini native config surfaces (from mirrored upstream docs)

| Surface | Upstream doc | Notes |
|---|---|---|
| Entry context | `upstream/cli/gemini-md.md` | `GEMINI.md` — persistent workspace context (Claude `CLAUDE.md` analogue) |
| Hooks | `upstream/hooks/{index,reference,writing-hooks,best-practices}.md` | Native hooks runtime — fires synchronously in the agent loop |
| Skills | `upstream/cli/{skills,using-agent-skills,creating-skills,skills-best-practices}.md` | Open agent-skills standard (`agentskills.io`) — **same standard Claude & Codex skills use** |
| Subagents | `upstream/core/subagents.md` | Target for Claude agents |
| Custom commands | `upstream/cli/custom-commands.md`, `upstream/reference/commands.md` | Claude slash-command analogue |
| Settings | `upstream/cli/settings.md`, `upstream/reference/configuration.md` | Target for Claude settings |
| MCP | `upstream/tools/mcp-server.md` | Native MCP support |
| Extensions | `upstream/extensions/{index,reference,writing-extensions}.md` | Packaging/distribution surface |

## Claude feature → Gemini mapping

| Claude feature (`tools/`) | Gemini target | Status | Shim / notes |
|---|---|---|---|
| `rules/` | Inlined into `GEMINI.md` (`_build_rules_for_target gemini`) | Emitted (`gemini.sh`) | Gemini supports `@import`; today rules are inlined. Verify `GEMINI.md` loads. |
| `skills/` | Gemini skills (agent-skills standard) | Emitted (`_agent_md_to_gemini_skill`) | **Potentially portable across all 3 CLIs** — shared `agentskills.io` standard. Verify Gemini loads them unchanged. |
| `agents/` | `core/subagents.md` | ❓ Unmapped | Confirm subagent format, then emit. |
| `commands/` | `cli/custom-commands.md` (`_command_md_to_gemini_toml`) | Emitted | Verify custom-command TOML format matches upstream. |
| `hooks/` | Gemini hooks (`_gemini_build_hooks_json`, event-name mapping) | Emitted | Verify events fire at runtime — the verified-parity test. |
| `mcp/` | `_gemini_build_mcp_json` | Emitted | Verify against `tools/mcp-server.md` schema. |
| `settings/` | `_gemini_render_settings` | Emitted | Verify against `reference/configuration.md`. |

## Open questions before Gemini can be declared "complete"

1. Do the emitted hooks actually fire under Gemini CLI at runtime? (necessary verified-parity proof)
2. Are Claude skills loadable by Gemini unchanged? (the agentskills.io standard suggests yes — verify)
3. Does the `created:22` reporting quirk in `gemini.sh` mask real non-idempotency? (see ONBOARDING)
4. What has *no* Gemini equivalent and therefore needs a genuine emit-time shim?
