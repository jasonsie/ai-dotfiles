# ai-dotfiles

One repository that configures four AI coding CLIs on a Mac the same way: **Claude Code**,
**Codex CLI**, **Pi**, and **Antigravity** (CLI and IDE). You edit one set of rules, skills,
settings and MCP servers here; an installer links or merges them into each CLI's own folders.
Each CLI keeps its native format and features. Nothing is emulated: a feature one CLI lacks is
documented, not faked.

It is an opinionated personal setup, published so others can fork it. Expect to change the
rules in `config/global-agents.md`, the model defaults in `config/cli-settings.json`, and the
skill list to taste.

- How the pieces fit: [docs/how-it-works.md](docs/how-it-works.md)
- Notes for AI agents editing this repo: [AGENTS.md](AGENTS.md)
- Third-party code and docs it ships: [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)

## What it manages

| Source in this repo | What it holds | Where it lands |
|---|---|---|
| `config/ai-clis.json` | Which CLIs are on, and the path each one reads for instructions, settings, MCP, skills and hooks | Drives every step below; a CLI switched off is cleaned out |
| `config/global-agents.md` | Rules loaded in every project by every CLI | Symlinked as `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.pi/agent/AGENTS.md`, `~/.gemini/GEMINI.md` |
| `config/cli-settings.json` | `enforce`: safety settings, restored on every install. `default`: model choices, written only when the CLI has none | Merged into each CLI's settings file (never symlinked, because CLIs write to these files) |
| `config/mcp-servers.json` | MCP servers every CLI should have (today: context7 for library docs) | `claude`, `codex` and `pi mcp add`; merged into Antigravity's `mcp_config.json` |
| `skills/<name>/` | Shared skills. Skills adapted from other repos are pinned in `skills/skills.lock` with source, commit and license | Symlinked into `~/.claude/skills`, `~/.agents/skills` (Codex and Pi), `~/.gemini/config/skills` |
| `skills/daily-log/` | The `daily-log` command, which writes a daily work journal, and the day pass that writes yesterday's entries from the CLIs' sessions | `~/.local/bin/daily-log`; a LaunchAgent, `~/Library/LaunchAgents/com.ai-dotfiles.daily-log-day.plist`, that runs the pass at 04:00 |
| `skills/worktree-guard/` | A hook that moves a second session working in the same checkout into its own git worktree | Hook entries in each CLI's hook file (Codex runs it only after approval in `/hooks`); a Pi extension; `ai-dotfiles worktree` commands |
| `skills/small-commits/` | A hook that gates `git commit` on size, subject and trailers | Hook entries in each CLI's hook file (Codex runs it only after approval in `/hooks`); a Pi extension; `ai-dotfiles commit check` |
| `skills/git/` | The git skills: `approve` lands a branch the user reviewed (push, PR, approval by the repo's reviewer account, archive tag, merge, branch deleted), each step a skill of its own | Linked by name like every skill; `ai-dotfiles approve`, `ai-dotfiles git <step>`; the reviewer is cached per repo in `git config --local approve.reviewer` |
| `config/upstream-docs.json` | The documentation sources mirrored into `docs/upstream/` | Refreshed weekly by a GitHub Action |
| `docs/upstream/` | Machine-written mirrors of each CLI's official docs and of Google's and Meta's style guides, with indexes | Read by agents through the `upstream-docs` skill; never installed |

Not managed, on purpose: credentials, sessions, plugin choices, local approvals and trust
decisions, and per-project rules. Each project keeps its own `AGENTS.md`.

## Requirements

- macOS. The paths in `config/ai-clis.json` are the CLIs' macOS defaults.
- Python 3.11 or newer. The stock `/usr/bin/python3` is too old; `brew install python`.
- Any subset of the four CLIs. Switch the others off in `config/ai-clis.json`.

## Install

```bash
git clone https://github.com/jasonsie/ai-dotfiles.git
cd ai-dotfiles
bash scripts/install.sh --dry-run   # preview: what would change, nothing written
bash scripts/install.sh             # apply; every file it touches is backed up first
ai-dotfiles check                   # read the live state back
```

The first run links `ai-dotfiles` and `daily-log` into `~/.local/bin`. From then on:

```bash
ai-dotfiles [install]     # apply the setup (idempotent: a second run reports 0 changes)
ai-dotfiles update        # fast-forward this repo on main, then install
ai-dotfiles uninstall     # remove every link and hook that points into this repo
ai-dotfiles check         # healthcheck
ai-dotfiles worktree ...  # list, merge or remove agents' linked worktrees
ai-dotfiles commit check  # what the commit hook would say to a `git commit`
```

Flags for `install`: `--dry-run` previews, `--target=<cli>` limits a run to one CLI,
`--instructions-only` links only the instruction files. An existing global instruction file
the installer did not create is left alone until you pass `--replace-instructions`.
Backups go to `~/.local/state/ai-dotfiles/`.

Uninstall restores the instruction files from before the first install and removes links,
hook entries and Pi's extension. Settings keys and MCP servers stay, because they could be
yours. After an uninstall, deleting the clone breaks nothing.

## Make it yours

- **Switch a CLI on or off.** Set `on` in `config/ai-clis.json`, then run `ai-dotfiles`.
- **Change a global rule.** Edit `config/global-agents.md`. It is live in every CLI at once,
  through the symlinks. Keep only rules that hold in every repository and every CLI.
- **Change a setting.** Add the key to `config/cli-settings.json` under `enforce` (always
  restored) or `default` (first install only), then run `ai-dotfiles`.
- **Add a skill.** Create `skills/<name>/SKILL.md`, then run `ai-dotfiles`. For a skill
  adapted from another repository, add its source, commit and license to `skills/skills.lock`
  and keep its LICENSE file in the skill folder.
- **The daily log.** At 04:00, when the day closes, a LaunchAgent runs the day pass
  (`daily-log day --write`): yesterday's Claude Code, Codex and Pi sessions and git, piped
  into one `claude -p` session that writes one entry per project into
  `~/Documents/Claude/Projects/daily-logger` (or `DAILY_LOGGER_ROOT` when set). Sessions
  never log on their own. By hand any time:
  `daily-log add --done "<project>: <what>" "keyword: <tags>" "description: <one line>"`.
- **Review the weekly upstream pull request.** Every Monday a GitHub Action refreshes
  `docs/upstream/` and opens a pull request from the `upstream-sync` branch. Its description
  lists which mirrored pages changed, which changes touch this setup, and which pinned skills
  changed upstream.
- **Anything machine-specific** lives in the CLI itself. The installer leaves it alone.

## Skills included

Forty-three skills install into every CLI. Most come from
[mattpocock/skills](https://github.com/mattpocock/skills) (MIT), lightly adapted so the same
file works in all four CLIs, and one from [affaan-m/ECC](https://github.com/affaan-m/ECC)
(MIT). `skills/skills.lock` records each adaptation. The `which-skill` skill routes between
them. Skills written for this repo include `daily-log`, `worktree-guard`, `small-commits`,
the git skills (`approve` and its steps), `upstream-docs`, `collect-docs`, `house-style` and `tutor`.

## Verify a change

```bash
python3 -m unittest discover -s scripts/tests
shellcheck scripts/*.sh scripts/ai-dotfiles
bash scripts/install.sh --dry-run        # expect 0 changes on a configured Mac
bash scripts/healthcheck.sh
```

CI runs the first two on every push.

## License

MIT. See [LICENSE](LICENSE). Adapted skills keep their authors' licenses in their folders, and
the docs mirrors under `docs/upstream/` keep their sources' terms; both are listed in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). The repository began as a fork of
[zeuikli/claude-code-workspace](https://github.com/zeuikli/claude-code-workspace) (MIT); no
files from it remain.
