# ai-cli-workspace — maintainer notes

This repo is the single source for **global** AI CLI config on the owner's Macs
(Claude Code, Codex CLI, Gemini CLI, Pi). Scope and rationale:
[ADR-0005](docs/adr/0005-global-config-single-source.md). `CLAUDE.md` and `GEMINI.md`
are symlinks to this file.

## What lives here

| Source | Applied by | Lands in |
|---|---|---|
| `tools/instructions/AGENTS.md` | `scripts/install-global-instructions.py` | symlinked as each CLI's global instruction file |
| `tools/settings/managed.json` | `scripts/apply-settings.py` | only those keys, merged into live settings |
| `tools/mcp/servers.json` | `scripts/apply-mcp.py` | native `claude/codex/gemini mcp add` (Pi has no MCP) |
| zkfy checkout (`ZKFY_DIR`) | `scripts/install-vault-knowledge.py` | `vault-knowledge` launcher + `vault-query` skill (Claude, Pi) |

`scripts/install.sh` runs all four in order; `scripts/healthcheck.sh` verifies live state.

## Rules for changes

- Shared behavior, native differences: do not emulate a feature a CLI lacks; document it.
- Never symlink a CLI's settings file (the CLIs write back to them); add keys to `managed.json` instead.
- Keep `tools/` and `scripts/` free of machine paths (`/Users/<name>`, `/opt/homebrew`); the healthcheck enforces this.
- No credentials in this repo. Per-project rules belong to each project, not here.
- Every script is dry-run by default, idempotent, backs up before writing, and refuses
  to overwrite things it does not own. Keep it that way and test it.

## Verify

```bash
python3 -m unittest discover -s tests      # Python 3.11+
shellcheck scripts/*.sh
bash scripts/install.sh --dry-run          # expect 0 changes on a configured Mac
bash scripts/healthcheck.sh
```

`docs/<cli>/upstream/` are mirrored reference docs (`scripts/sync-cli-docs.sh`);
`docs/archive/` holds design notes for the retired per-project generator.
