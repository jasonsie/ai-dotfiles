# AI Dotfiles

The single source for my global AI coding setup on macOS: Claude Code, Codex CLI, Pi, and
Antigravity (CLI and IDE). Each CLI gets the same shared rules and skills through its own
native folders and keeps its native differences; missing features are documented, not
emulated. How it works: [docs/how-it-works.md](docs/how-it-works.md). Forked from
[zeuikli/claude-code-workspace](https://github.com/zeuikli/claude-code-workspace).

## What it manages

| Source | What it holds | Lands in |
|---|---|---|
| `config/ai-clis.json` | Which CLIs are on, and where each reads things | Decides what every step below sets up; a CLI switched off is taken out |
| `config/global-agents.md` | Rules for every project in every CLI | Linked as `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.gemini/GEMINI.md` (read by Antigravity), `~/.pi/agent/AGENTS.md` |
| `config/cli-settings.json` | `enforce`: safety settings, put back on every install. `default`: model choices, set only while a CLI has none | Each CLI's settings file, merged (never linked) |
| `config/mcp-servers.json` | Shared MCP servers (today: context7, library docs) | `claude`, `codex` and `pi mcp add`; merged into `~/.gemini/config/mcp_config.json` for Antigravity |
| `skills/<name>/` | Shared skills; adapted ones are pinned in `skills/skills.lock` | `~/.claude/skills`, `~/.agents/skills` (Codex and Pi), `~/.gemini/config/skills` (Antigravity) |
| `config/upstream-docs.json` | The documentation sources behind `docs/upstream/` | `scripts/upstream/sync-upstream.py`, weekly |
| `skills/daily-log/` | The `daily-log` command (the daily logger's grammar and writer) and its Stop hook | `~/.local/bin/daily-log`; hook entries in `~/.claude/settings.json`, `~/.codex/hooks.json`, `~/.gemini/config/hooks.json`; Pi's `~/.pi/agent/extensions` |
| `docs/upstream/` | A weekly mirror of each CLI's official docs and of Google's and Meta's style and docs-writing guides, indexed, plus the watched skill catalogs | Read through the `upstream-docs` skill; never installed |

Not managed: credentials, sessions, plugin choices, local approvals and trust, and
per-project rules (each project keeps its own `AGENTS.md`).

## Set up a Mac

Requires Python 3.11+ (stock `/usr/bin/python3` is too old: `brew install python`).

```bash
git clone <this repo>
bash scripts/install.sh            # install (backs up first); --dry-run previews
ai-dotfiles check                  # verify live state; works from any folder now
```

The first run links `ai-dotfiles` and `daily-log` into `~/.local/bin`:

```bash
ai-dotfiles [install]    # apply the setup
ai-dotfiles update       # pull this repo (clean tree on main), then install
ai-dotfiles uninstall    # remove what points into this repo; settings keys and MCP servers stay
ai-dotfiles check        # healthcheck
```

`--dry-run` previews any of them; `--target=<cli>` limits a run to one CLI in
`config/ai-clis.json`; `--instructions-only` links the instructions only. Existing
instruction files the installer does not recognize are refused until you review them
(`--replace-instructions`). Backups go to `~/.local/state/ai-dotfiles/`.

Claude plugins are a per-machine choice, not managed here. The current set:

```bash
claude plugin marketplace add https://github.com/jasonsie/zkfy.git
for p in zkfy@zkfy-marketplace pyright-lsp@claude-plugins-official typescript-lsp@claude-plugins-official; do
  claude plugin install "$p"
done
```

## Everyday changes

- **A CLI on or off:** set its `on` in `config/ai-clis.json`, then run `ai-dotfiles`. Off
  takes out this repo's links for it; on sets it up again.
- **A rule for every project:** edit `config/global-agents.md`; it is live at once
  through the links. Keep only rules that apply in every repository and every CLI; anything
  narrower belongs in a project's `AGENTS.md` or in a skill.
- **A setting:** add it to `config/cli-settings.json` under `enforce` (always put back)
  or `default` (first run only), then run `ai-dotfiles`.
- **A skill:** add `skills/<name>/SKILL.md`, then run `ai-dotfiles`.
  For a skill adapted from another repository, record its source, commit, and license in
  `skills/skills.lock` and keep its LICENSE file in the skill folder.
- **The weekly upstream pull request:** every Monday a GitHub Action refreshes `docs/upstream/`
  and opens or refreshes a pull request from the `upstream-sync` branch. Read its "Changes
  that touch this setup" and "Skills" sections, then merge or close it.
- **The daily log:** `daily-log add --done "<label>" "<line>"` records finished work in
  `~/Documents/Claude/Projects/daily-logger`; the Stop hook asks for it once in a session that
  changed files but logged nothing. Codex runs the hook only after approval in `/hooks`.
- **Anything machine-specific:** change it in the CLI itself; the installer leaves it alone.

How it all fits together: [docs/how-it-works.md](docs/how-it-works.md). Maintainer notes
for AI tools: [AGENTS.md](AGENTS.md).

## License

MIT License
