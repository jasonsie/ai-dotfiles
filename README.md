# AI Dotfiles

The single source for my global AI coding setup on macOS: Claude Code, Codex CLI, Pi, and
Antigravity (CLI and IDE). Each CLI gets the same shared rules and skills through its own
native folders and keeps its native differences; missing features are documented, not
emulated. Decisions: [ADR-0005](docs/adr/0005-global-config-single-source.md) and
[ADR-0006](docs/adr/0006-redesign-round-2.md). Forked from
[zeuikli/claude-code-workspace](https://github.com/zeuikli/claude-code-workspace).

## What it manages

| Source | What it holds | Lands in |
|---|---|---|
| `tools/instructions/AGENTS.md` | Rules for every project in every CLI (today: task memory) | Linked as `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.gemini/GEMINI.md` (read by Antigravity), `~/.pi/agent/AGENTS.md` |
| `tools/settings/managed.json` | `enforce`: safety settings, put back on every install. `default`: model choices, set only while a CLI has none | Each CLI's settings file, merged (never linked) |
| `tools/mcp/servers.json` | Shared MCP servers (today: context7, library docs) | `claude`, `codex` and `pi mcp add`; merged into `~/.gemini/config/mcp_config.json` for Antigravity |
| `skills/<name>/` | Shared skills (`grilling`) | `~/.claude/skills`, `~/.agents/skills` (Codex and Pi), `~/.gemini/config/skills` (Antigravity) |
| zkfy checkout | The read-only `query` vault skill and its `vault-knowledge` launcher | The same three skill folders and `~/.local/bin` |
| `upstream/` | A weekly mirror of each CLI's official docs and the watched skill catalogs | Read on demand; never installed |

Not managed: credentials, sessions, plugin choices, local approvals and trust, and
per-project rules (each project keeps its own `AGENTS.md`).

## Set up a Mac

Requires Python 3.11+ (stock `/usr/bin/python3` is too old: `brew install python`).

```bash
git clone <this repo> && git clone https://github.com/jasonsie/zkfy.git
export ZKFY_DIR=/path/to/zkfy ZKFY_VAULT=/path/to/vault   # optional: vault retrieval
bash scripts/install.sh            # preview: writes nothing
bash scripts/install.sh --apply    # apply (backs up first)
bash scripts/healthcheck.sh        # verify live state
```

`--target=claude|codex|pi|agy` limits a run; `--instructions-only` links the instructions
only. Existing instruction files the installer does not recognize are refused until you
review them (`--replace-instructions`). Backups go to `~/.local/state/ai-dotfiles/`.

Claude plugins are a per-machine choice, not managed here. The current set:

```bash
claude plugin marketplace add https://github.com/jasonsie/zkfy.git
for p in zkfy@zkfy-marketplace pyright-lsp@claude-plugins-official typescript-lsp@claude-plugins-official; do
  claude plugin install "$p"
done
```

## Everyday changes

- **A rule for every project:** edit `tools/instructions/AGENTS.md`; it is live at once
  through the links. Keep only rules that apply in every repository and every CLI; anything
  narrower belongs in a project's `AGENTS.md` or in a skill.
- **A setting:** add it to `tools/settings/managed.json` under `enforce` (always put back)
  or `default` (first run only), then run `bash scripts/install.sh --apply`.
- **A skill:** add `skills/<name>/SKILL.md`, then run `bash scripts/install.sh --apply`.
  For a skill adapted from another repository, record its source, commit, and license in
  `skills/skills.lock` and keep its LICENSE file in the skill folder.
- **The weekly upstream pull request:** every Monday a GitHub Action refreshes `upstream/`
  and opens or refreshes a pull request from the `upstream-sync` branch. Read its "Changes
  that touch this setup" and "Skills" sections, then merge or close it.
- **Anything machine-specific:** change it in the CLI itself; the installer leaves it alone.

How it all fits together: [docs/how-it-works.md](docs/how-it-works.md). Maintainer notes
for AI tools: [AGENTS.md](AGENTS.md).

## License

MIT License
