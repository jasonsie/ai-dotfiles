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
| `config/upstream-docs.json` | The documentation sources mirrored for agents: each CLI's docs, Google's and Meta's style and docs-writing guides, a `when` label per page | `scripts/upstream/sync-upstream.py` (weekly workflow) |
| `skills/` | Shared skills; `skills.lock` pins adapted upstream skills | `scripts/install/skills.py` |
| `skills/daily-log/` | The `daily-log` command (the daily logger's grammar and writer), its hook, Pi's extension | `scripts/install/skills.py` (links), `scripts/install/hooks.py` (hook entries) |
| `scripts/ai-dotfiles` | Global command: `install`, `update`, `uninstall`, `check` | `scripts/install/skills.py` |
| `scripts/install/installer.py` | What every step shares: reading `ai-clis.json`, safe writes | — |
| `scripts/install/hooks.py` | One hook entry per event in each CLI's native hook file; ours are found by their command | — |
| `docs/upstream/` | Machine-written docs mirrors with their indexes (`INDEX.md`, `MIRROR-INDEX.*`), and skill catalogs | `scripts/upstream/` (weekly workflow) |
| `docs/onboarding.md` | This repo's onboarding report | `skills/onboard/` (`/onboard`) |
| `scripts/tests/` | Unit tests for the scripts and the skills' helpers | — |

`scripts/install.sh` runs the five install steps, `scripts/uninstall.sh` reverses them;
`scripts/healthcheck.sh` verifies live state. `docs/` holds `how-it-works.md`, the mirror, and
`onboarding.md`, this repo's report from `/onboard`.

## Rules for changes

- Shared behavior, native differences: do not emulate a feature a CLI lacks; document it.
- `config/global-agents.md` holds only rules that apply in every repository and every CLI.
  Keep it free of `@` imports and HTML comments: Claude parses them, the other CLIs do not.
- Never symlink a CLI's settings file (the CLIs write back to them); add keys to
  `cli-settings.json`, under `enforce` for safety settings or `default` for model choices.
- Lists live in `config/`: CLIs and their paths in `ai-clis.json`, documentation sources in
  `upstream-docs.json`; scripts keep only how each is applied.
- Never edit `docs/upstream/` by hand; the weekly sync rebuilds it. Agents read it through
  the `upstream-docs` skill; `collect-docs` adds a source.
- A newer upstream version of a pinned skill replaces ours: remove it, add theirs, re-apply
  its `local_edits` from `skills/skills.lock`, and update `which-skill` (a test checks it).
- Keep `config/` and `scripts/` free of machine paths (`/Users/<name>`, `/opt/homebrew`);
  the healthcheck enforces this.
- No credentials in this repo. Per-project rules belong to each project, not here.
- Every installer writes by default, previews with `--dry-run`, has `--uninstall`, is
  idempotent, backs up before writing, refuses to overwrite what it did not create, and
  rolls back on failure. Keep it that way and test it.

## Verify

```bash
python3 -m unittest discover -s scripts/tests      # Python 3.11+
shellcheck scripts/*.sh scripts/ai-dotfiles
bash scripts/install.sh --dry-run                  # expect 0 changes on a configured Mac
bash scripts/healthcheck.sh
```
