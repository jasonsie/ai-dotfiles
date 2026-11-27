# ai-dotfiles — maintainer notes

This repo is the single source for the owner's **global** AI CLI setup: Claude Code,
Codex CLI, Pi, and Antigravity. The mechanism and layout are in
[docs/how-it-works.md](docs/how-it-works.md); earlier decisions are in git history.
Every CLI reads this file as the project's instructions; there is no `CLAUDE.md`.

## Map

| Path | What | Applied by |
|---|---|---|
| `config/ai-clis.json` | Which CLIs are on, and where each reads things; the desired state | every step, via `lib/install/installer.py` |
| `config/global-agents.md` | Global rules for every CLI, live through links | `lib/install/instructions.py` |
| `config/cli-settings.json` | Per-CLI `enforce` keys (safety settings, the status line) and `default` keys (model choices, permission-dialog consent) | `lib/install/settings.py` |
| `config/mcp-servers.json` | Shared MCP servers | `lib/install/mcp.py` |
| `config/plugins.json` | The plugin list: each plugin's GitHub source, pin (exact version) and target CLIs | `lib/install/plugins.py` |
| `config/cloud.json` | The skills cloud sessions leave out, each with the reason | `scripts/cloud_session.py` (links the rest in a cloud session) |
| `scripts/cloud/` | A cloud environment's setup: `environment.sh`, pasted on claude.ai, clones this repo and runs `setup.sh` (`install.sh --cloud`, the plugins at their pins) | the cloud environment |
| `.claude/settings.json` | The hooks a cloud session on this repo runs ("Cloud sessions" in how-it-works) | the cloud session |
| `config/upstream-docs.json` | The documentation sources mirrored for agents: each CLI's docs, Google's and Meta's style and docs-writing guides, a `when` label per page | `scripts/upstream/sync-upstream.py` (weekly workflow) |
| `skills/` | Shared skills; `skills.lock` pins adapted upstream skills | `lib/install/skills.py` |
| `skills/daily-log/` | The `daily-log` command (the daily logger's grammar and writer) and `day_pass.py`, the day pass: the evidence and, with `--write`, the session that writes from it | `lib/install/skills.py` (links), `lib/install/launchd.py` (the 04:00 LaunchAgent) |
| `scripts/agent_sessions.py` | Every CLI's session store (transcripts) behind one interface, for the day pass and herdr-title; each store's files and lines are its adapter's | — |
| `scripts/statusline.py` | The status line Claude Code and Antigravity run as `ai-dotfiles statusline`: folder, branch and worktree, model with effort, version, context left, rate limits (asked of a gateway on this machine when the CLI sends none) and cost. Codex lists the same items in `tui.status_line`; Pi's footer has them built in | `lib/install/settings.py` (the `statusLine` keys) |
| `skills/worktree-guard/` | The hook that, in a repo switched on, keeps each task in its own worktree and each worktree to one session, and the `ai-dotfiles worktree` commands | its `feature.json`, read by the door and `lib/install/hooks.py` |
| `skills/worktree-flow/` | `/worktree-flow`, the person's toggle of a repo's flow switch, after their OK in a macOS dialog | `lib/install/skills.py` |
| `skills/small-commits/` | The hook that gates `git commit` on size (300 lines warn, 600 wall), subject and trailers, and the `ai-dotfiles commit check` command | its `feature.json`, read by the door, `lib/commands.py` and `lib/install/hooks.py` |
| `skills/herdr-title/` | The hook that, inside a Herdr pane, labels the agent's row in the sidebar type › status › result (`execute › wait › ask`) at each prompt, turn end, dialog and resume, and sorts the rows that need the person to the top: at once where a rule decides, else by Haiku through a headless `claude -p` | its `feature.json`, read by the door and `lib/install/hooks.py` |
| `config/herdr-title.json` | The ten types and their meanings, the label's words, the command words and skills that decide a type at once, how a prompt the user did not type starts, what makes a turn end ask or fail at once, and both model instructions (type, turn end) | `skills/herdr-title/scripts/herdr_title.py` (read on every call) |
| `skills/portable-plugin/` | The rules a plugin's files follow to run in all four CLIs, the check, and the release step | `lib/install/skills.py` |
| `skills/git/` | A bundle: the git step skills (`push-branch`, `open-pr`, `approve-pr`, `archive-tag`, `merge-pr`, `prune-branch`), each with its own script, `approve`, which runs them in order, and `ship-pr`, an agent's finish in its worktree (checks, push, PR, worktree deleted); `scripts/git_run.py` is the runner they share | `lib/install/skills.py` (each linked by its own name); its `feature.json` (commands only), read by `lib/commands.py` |
| `scripts/agent_hooks.py` | Every CLI's hook format behind one interface, for the door, and the Event that gives a feature the command, its folder and the files of a call; `agent_hooks.ts` is Pi's extension, which sends each event to the door | `lib/install/skills.py` (Pi's link) |
| `lib/` | What the features and the installer share: `features.py` finds each feature by the `feature.json` in its folder (its hooks per CLI, their order, budgets, the cloud answer); `door.py` is `ai-dotfiles hook`, the one call per event that runs every feature wanting it; `commands.py` runs the commands a declaration adds and prints `--help` from them; `adapters/` holds, one per CLI, what differs on the hook side (tool names, where a call names its command and files, patch headers, hook events, session store) | `scripts/ai-dotfiles` (`hook`, any other command), `lib/install/hooks.py` |
| `scripts/ai-dotfiles` | Global command: runs the door's own steps and hands every other word to `lib/commands.py`; `ai-dotfiles --help` lists them all | `lib/install/skills.py` |
| `lib/install/installer.py` | What every step shares: reading `ai-clis.json`, safe writes | — |
| `lib/install/hooks.py` | One door entry per event in each CLI's native hook file, from the features' declarations; ours are found by their command; each feature's old entries and other retired ones taken out; the door's Python linked | — |
| `lib/install/plugins.py` | Each listed plugin at its release tag through each CLI's own plugin manager, read back after; each manifest checked at its tag (name, dependencies); its bin/ commands linked into `~/.local/bin` from a checkout at the tag; a receipt tells installed from taken over; every outside command through one runner | — |
| `lib/install/launchd.py` | The daily-log pass as a LaunchAgent, `claude` path and PATH rendered at install | — |
| `docs/upstream/` | Machine-written docs mirrors with their indexes (`INDEX.md`, `MIRROR-INDEX.*`), and skill catalogs | `scripts/upstream/` (weekly workflow) |
| `docs/agents/` | Where the engineering skills (`to-spec`, `to-tickets`, `triage`) publish and read: issue tracker, triage labels, domain docs | `skills/setup-agent-skills/` (`/setup-agent-skills`) |
| `scripts/tests/` | Unit tests for the scripts and the skills' helpers | — |
| `LICENSE`, `THIRD-PARTY-NOTICES.md`, `LICENSES/` | This repo's MIT license; every other author's license (adapted skills, docs mirrors) and the license texts | — |

`scripts/install.sh` runs the seven install steps, `scripts/uninstall.sh` reverses them;
`scripts/healthcheck.sh` verifies live state. `docs/` holds `how-it-works.md`, the mirror,
and `agents/`, the engineering skills' setup.

## Rules for changes

- Shared behavior, native differences: do not emulate a feature a CLI lacks; document it.
- A feature never names a CLI: what differs is an adapter's (`lib/adapters`); the feature reads the Event and asks the adapter. `scripts/tests/test_cli_rule.py` fails on one that does and holds the short allow-list.
- `config/global-agents.md` holds only rules that apply in every repository and every CLI.
  Keep it free of `@` imports and HTML comments: Claude parses them, the other CLIs do not.
- Never symlink a CLI's settings file (the CLIs write back to them); add keys to
  `cli-settings.json`, under `enforce` for settings this repo owns (safety, the status line) or
  `default` for model choices and any value the CLI writes back (an enforced one never settles).
- Logic two skills need lives in one skill (its `scripts/`); the others import it, never copy
  it. Code every step of a bundle needs goes in the bundle's `scripts/`. A bundle
  (`skills/git/`) is this repo's grouping only: the CLIs read one level of skill folders, so
  the installer links each skill in it by its own name.
- Lists live in `config/`: CLIs and their paths in `ai-clis.json`, documentation sources in
  `upstream-docs.json`; scripts keep only how each is applied.
- Never edit `docs/upstream/` by hand; the weekly sync rebuilds it. Agents read it through
  the `upstream-docs` skill; `collect-docs` adds a source.
- A newer upstream version of a pinned skill replaces ours: remove it, add theirs, re-apply
  its `local_edits` from `skills/skills.lock`, and update `which-skill` (a test checks it).
- A skill a cloud session cannot run (it needs the Mac, or a GitHub call the cloud refuses)
  gets its reason in `config/cloud.json`.
- Keep `config/`, `lib/` and `scripts/` free of machine paths (`/Users/<name>`, `/opt/homebrew`);
  the healthcheck enforces this.
- No credentials in this repo. Per-project rules belong to each project, not here.
- A new adapted skill or docs source gets a row in `THIRD-PARTY-NOTICES.md` and, for a new
  license, its text in `LICENSES/`.
- Every installer writes by default, previews with `--dry-run`, has `--uninstall`, is
  idempotent, backs up before writing, refuses to overwrite what it did not create, and
  rolls back on failure. Keep it that way and test it.

## Verify

```bash
python3 -m unittest discover -s scripts/tests      # Python 3.11+
shellcheck scripts/*.sh scripts/cloud/*.sh scripts/ai-dotfiles
bash scripts/install.sh --dry-run                  # expect 0 changes on a configured Mac
bash scripts/healthcheck.sh
```

## Agent skills

### Issue tracker

GitHub Issues on `jasonsie/ai-dotfiles`, through `gh`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five defaults: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: the glossary and standing decisions are in `docs/how-it-works.md`; a design in progress, when there is one, is in `docs/plans/`. See `docs/agents/domain.md`.
