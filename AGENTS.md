# ai-cli-workspace — maintainer notes

This repo is the single source for the owner's **global** AI CLI setup: Claude Code,
Codex CLI, Pi, and Antigravity. The mechanism is in [docs/how-it-works.md](docs/how-it-works.md);
decisions are in [docs/adr/](docs/adr/) (ADR-0005 and ADR-0006). `CLAUDE.md` links to this file.

## Map

| Path | What | Applied by |
|---|---|---|
| `tools/instructions/AGENTS.md` | Global rules for every CLI, live through links | `scripts/install-global-instructions.py` |
| `tools/settings/managed.json` | Per-CLI `enforce` and `default` keys | `scripts/apply-settings.py` |
| `tools/mcp/servers.json` | Shared MCP servers (Claude Code, Codex) | `scripts/apply-mcp.py` |
| `skills/` | Shared skills; `skills.lock` pins adapted upstream skills | `scripts/install-skills.py` |
| zkfy checkout (`ZKFY_DIR`) | `query` skill and `vault-knowledge` launcher | `scripts/install-vault-knowledge.py` |
| `upstream/` | Machine-written docs mirrors and skill catalogs | `scripts/sync-cli-docs.sh`, `scripts/report-upstream.py` (weekly workflow) |
| `docs/plans/` | Task files for work that spans sessions | — |

`scripts/install.sh` runs the five install steps; `scripts/healthcheck.sh` verifies live state.

## Rules for changes

- Shared behavior, native differences: do not emulate a feature a CLI lacks; document it.
- The global `AGENTS.md` holds only rules that apply in every repository and every CLI.
  Keep it free of `@` imports and HTML comments: Claude parses them, the other CLIs do not.
- Never symlink a CLI's settings file (the CLIs write back to them); add keys to
  `managed.json`, under `enforce` for safety settings or `default` for model choices.
- Never edit `upstream/` by hand; the weekly sync rebuilds it.
- Keep `tools/` and `scripts/` free of machine paths (`/Users/<name>`, `/opt/homebrew`);
  the healthcheck enforces this.
- No credentials in this repo. Per-project rules belong to each project, not here.
- Every installer previews by default, is idempotent, backs up before writing, refuses to
  overwrite what it did not create, and rolls back on failure. Keep it that way and test it.

## Verify

```bash
python3 -m unittest discover -s tests      # Python 3.11+
shellcheck scripts/*.sh
bash scripts/install.sh                    # preview; expect 0 changes on a configured Mac
bash scripts/healthcheck.sh
```
