# ai-dotfiles — maintainer notes

This repo is the single source for the owner's **global** AI CLI setup: Claude Code,
Codex CLI, Pi, and Antigravity. The mechanism and layout are in
[docs/how-it-works.md](docs/how-it-works.md); earlier decisions are in git history.
`CLAUDE.md` links to this file.

## Map

| Path | What | Applied by |
|---|---|---|
| `config/ai-clis.json` | Which CLIs are on, and where each reads things; the desired state | every step, via `scripts/install/installer.py` |
| `config/global-agents.md` | Global rules for every CLI, live through links | `scripts/install/instructions.py` |
| `config/cli-settings.json` | Per-CLI `enforce` and `default` keys | `scripts/install/settings.py` |
| `config/mcp-servers.json` | Shared MCP servers | `scripts/install/mcp.py` |
| `skills/` | Shared skills; `skills.lock` pins adapted upstream skills | `scripts/install/skills.py` |
| `scripts/ai-dotfiles` | Global command: `install`, `update`, `uninstall`, `check` | `scripts/install/skills.py` |
| `scripts/install/installer.py` | What every step shares: reading `ai-clis.json`, safe writes | — |
| `docs/upstream/` | Machine-written docs mirrors and skill catalogs | `scripts/upstream/` (weekly workflow) |
| `scripts/tests/` | Unit tests for the scripts and the skills' helpers | — |

`scripts/install.sh` runs the four install steps, `scripts/uninstall.sh` reverses them;
`scripts/healthcheck.sh` verifies live state. `docs/` holds only `how-it-works.md` and the
mirror.

## Rules for changes

- Shared behavior, native differences: do not emulate a feature a CLI lacks; document it.
- `config/global-agents.md` holds only rules that apply in every repository and every CLI.
  Keep it free of `@` imports and HTML comments: Claude parses them, the other CLIs do not.
- Never symlink a CLI's settings file (the CLIs write back to them); add keys to
  `cli-settings.json`, under `enforce` for safety settings or `default` for model choices.
- CLI lists and paths live only in `config/ai-clis.json`; scripts keep only how each CLI's
  files are edited.
- Never edit `docs/upstream/` by hand; the weekly sync rebuilds it.
- Keep `config/` and `scripts/` free of machine paths (`/Users/<name>`, `/opt/homebrew`);
  the healthcheck enforces this.
- No credentials in this repo. Per-project rules belong to each project, not here.
- Every installer writes by default, previews with `--dry-run`, has `--uninstall`, is
  idempotent, backs up before writing, refuses to overwrite what it did not create, and
  rolls back on failure. Keep it that way and test it.

## Verify

```bash
python3 -m unittest discover -s scripts/tests      # Python 3.11+
shellcheck scripts/*.sh scripts/upstream/*.sh scripts/ai-dotfiles
bash scripts/install.sh --dry-run                  # expect 0 changes on a configured Mac
bash scripts/healthcheck.sh
```
