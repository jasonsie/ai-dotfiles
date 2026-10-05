# `tools/` — canonical sources

Everything the installers apply comes from here (see [ADR-0005](../docs/adr/0005-global-config-single-source.md)).

| Path | Contents | Applied by |
|---|---|---|
| `instructions/AGENTS.md` | Shared global instructions for all four CLIs | `scripts/install-global-instructions.py` (symlinks) |
| `settings/managed.json` | Per-CLI keys that must match on every Mac (dotted keys for nested JSON; Codex keys are top-level TOML) | `scripts/apply-settings.py` (merge; other keys untouched) |
| `mcp/servers.json` | Shared MCP servers and which CLIs get them; no secrets | `scripts/apply-mcp.py` (native `mcp add`) |

Not here on purpose: credentials, machine-specific values, plugin choices, and per-project rules.
Shared skills would live in `tools/skills/<name>/SKILL.md`; there are none today
(`vault-query` is owned by zkfy and linked by `scripts/install-vault-knowledge.py`).
